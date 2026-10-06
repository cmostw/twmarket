"""Failure contracts: never turn bad sources into prices, empty data or long waits."""

from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from twmarket import AsyncClient, Client, Contract
from twmarket.errors import NoDataError, SchemaError, TransportError
from twmarket.transport.http import retry_delay

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
