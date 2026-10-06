"""Failure contracts: never turn bad sources into prices, empty data or long waits."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import orjson
import pytest

from twmarket import AsyncClient, Client, Contract
from twmarket.errors import NoDataError, SchemaError, SourceError, TransportError
from twmarket.models.common import SourceInfo
from twmarket.providers.mops.data import parse_statement
from twmarket.transport.http import Payload, retry_delay

FIXTURES = Path(__file__).parent / "fixtures"


async def test_transport_distinguishes_retryable_permanent_and_closed_failures() -> (
    None
):
    for status, attempts in [(503, 3), (429, 3), (404, 1), (200, 1)]:
        requests = [0]

        def respond(
            request: httpx.Request, status: int = status, requests: list[int] = requests
        ) -> httpx.Response:
            requests[0] += 1
            return httpx.Response(
                status,
                content=(FIXTURES / "stock-mis.json").read_bytes(),
                headers={"Retry-After": "0"},
            )

        transport = httpx.MockTransport(respond)
        with Client(transport=transport, interval=0) as client:
            if status == 200:
                assert client.twse.quote("2330").last == Decimal("2585")
            else:
                with pytest.raises(TransportError):
                    client.twse.quote("2330")
        assert requests[0] == attempts
        with pytest.raises(TransportError, match="closed"):
            client.twse.quote("2330")
        requests[0] = 0
        async with AsyncClient(transport=transport, interval=0) as other:
            if status == 200:
                assert (await other.twse.quote("2330")).last == Decimal("2585")
            else:
                with pytest.raises(TransportError):
                    await other.twse.quote("2330")
        assert requests[0] == attempts
        with pytest.raises(TransportError, match="closed"):
            await other.twse.quote("2330")
    with pytest.raises(TransportError, match="longer than"):
        retry_delay(httpx.Response(429, headers={"Retry-After": "31"}), 0)
    assert (
        retry_delay(httpx.Response(429, headers={"Retry-After": "invalid"}), 0) == 0.25
    )
    assert retry_delay(None, 1) == 0.5
    for options in [
        {"timeout": 0},
        {"retries": -1},
        {"interval": -1},
        {"cache_ttl": float("nan")},
        {"cache_size": 0},
    ]:
        with pytest.raises(ValueError):
            Client(**options)  # type: ignore[arg-type]


def test_source_corruption_and_wrong_dates_never_become_valid_data() -> None:
    for body, expected in [
        (b"<html>maintenance</html>", SchemaError),
        (b'{"rtcode":"0000","msgArray":[]}', NoDataError),
        (b'{"rtcode":"0000"}', SchemaError),
        (b'{"rtcode":"5000","rtmessage":"maintenance"}', SourceError),
    ]:
        with Client(
            transport=httpx.MockTransport(
                lambda r, body=body: httpx.Response(200, content=body)
            ),
            interval=0,
        ) as c:
            with pytest.raises(expected):
                c.twse.quote("2330")
    # A source may return valid JSON for the wrong reporting period: reject it.
    source = SourceInfo(
        "mops", "https://mops.twse.com.tw/mops/api/t164sb04", datetime.now(UTC)
    )
    original = orjson.loads((FIXTURES / "mops-income.fixture").read_bytes())
    mutations: list[tuple[Callable[[dict[str, object]], None], type[Exception]]] = [
        (lambda root: root.update(code="406"), NoDataError),
        (lambda root: root.update(code="500"), SourceError),
    ]
    for mutate, expected in mutations:
        changed = dict(original)
        mutate(changed)
        with pytest.raises(expected):
            parse_statement(
                Payload(orjson.dumps(changed), source), "2330", "income", 2026, 2
            )
    with pytest.raises(SchemaError, match="period"):
        parse_statement(
            Payload(orjson.dumps(original), source), "2330", "income", 2025, 2
        )
    for corruption in ["account_heading", "truncated_row"]:
        changed = orjson.loads(orjson.dumps(original))
        if corruption == "account_heading":
            changed["result"]["titles"][0]["main"] = "unexpected heading"
        else:
            changed["result"]["reportList"][0].pop()
        with pytest.raises(SchemaError):
            parse_statement(
                Payload(orjson.dumps(changed), source), "2330", "income", 2026, 2
            )
    from datetime import date

    queries: list[Callable[[Client], object]] = [
        lambda c: c.esb.quote("6898"),
        lambda c: c.ndc.indicators(start=date(2026, 1, 1), end=date(2026, 9, 30)),
        lambda c: c.tdcc.distribution("2330"),
    ]
    for query in queries:
        with Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=b"<html>maintenance</html>")
            ),
            interval=0,
        ) as c:
            with pytest.raises(SchemaError):
                query(c)


async def test_contract_mapping_rejects_expired_missing_and_ambiguous_identity() -> (
    None
):
    from twmarket.providers.taifex.catalog import add_mapping, identity

    contract = Contract("TX", "202610")
    key = identity(contract)
    with pytest.raises(SchemaError, match="ambiguous"):
        add_mapping({key: "TXFJ6-F"}, key, "OTHER-F")
    with Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"RtCode": "2"})
        ),
        interval=0,
    ) as c:
        assert c.taifex.contracts(product="TX") == []
        for target in [contract, Contract("TX", "202610/202611")]:
            with pytest.raises(NoDataError):
                c.taifex.resolve(target)
    async with AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"RtCode": "2"})
        ),
        interval=0,
    ) as c:
        assert await c.taifex.contracts(product="TX") == []
        for target in [contract, Contract("TX", "202610/202611")]:
            with pytest.raises(NoDataError):
                await c.taifex.resolve(target)
