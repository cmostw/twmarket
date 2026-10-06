"""Focused public-API tests against recorded official responses."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from twmarket import AsyncClient, Client, Contract
from twmarket.errors import SchemaError
from twmarket.parsing.numbers import integer, number

FIXTURES = Path(__file__).parent / "fixtures"
START = date(2026, 9, 1)
END = date(2026, 9, 30)


def response(name: str) -> httpx.Response:
    return httpx.Response(200, content=(FIXTURES / name).read_bytes())


async def test_history_sync_async_and_units() -> None:
    for market, code, volume, unit, amount_unit in [
        ("twse", "2330", 31855287, "shares", "TWD"),
        ("tpex", "6223", 1649, "lots", "thousand_TWD"),
    ]:

        def handler(
            request: httpx.Request, code: str = code, market: str = market
        ) -> httpx.Response:
            assert (
                request.url.params.get("stockNo", request.url.params.get("code"))
                == code
            )
            return response(f"{market}.json")

        transport = httpx.MockTransport(handler)
        with Client(transport=transport, interval=0) as client:
            provider = client.twse if market == "twse" else client.tpex
            rows = provider.history(code, start=START, end=END)
        async with AsyncClient(transport=transport, interval=0) as client:
            async_provider = client.twse if market == "twse" else client.tpex
            async_rows = await async_provider.history(code, start=START, end=END)
        assert len(rows) == len(async_rows) == 20
        assert [(r.date, r.close, r.volume) for r in rows] == [
            (r.date, r.close, r.volume) for r in async_rows
        ]
        assert rows[0].volume == volume
        assert rows[0].volume_unit == unit
        assert rows[0].amount_unit == amount_unit
        assert isinstance(rows[0].close, Decimal)
        if market == "twse":
            reset = next(r for r in rows if r.change_basis_reset)
            assert reset.raw_change == "X0.00" and reset.change is None
        assert rows[0].source.received_at.tzinfo is not None


def test_history_range_and_invalid_input() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return response("twse.json")

    with Client(transport=httpx.MockTransport(handler), interval=0) as client:
        rows = client.twse.history("2330", start=date(2026, 9, 2), end=date(2026, 9, 4))
        assert [r.date.day for r in rows] == [2, 3, 4]
        with pytest.raises(ValueError):
            client.twse.history("2330", start=END, end=START)
        with pytest.raises(TypeError):
            client.twse.quote(2330)  # type: ignore[arg-type]
    for value in [None, "", "-", "--", "NULL"]:
        assert number(value) is None
    assert number("0") == Decimal(0)
    assert number("1,234.0100") == Decimal("1234.0100")
    for value in [True, 0.1, "NaN", "Infinity", "invalid"]:
        with pytest.raises(SchemaError):
            number(value)
    with pytest.raises(SchemaError):
        integer("1.5")


async def test_taifex_daily_identity_and_missing_values() -> None:
    for name, kind in [("futures", "future"), ("options", "option")]:
        transport = httpx.MockTransport(
            lambda request, name=name: response(f"taifex-{name}.json")
        )
        with Client(transport=transport, interval=0) as client:
            rows = client.taifex.daily(kind=kind)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, interval=0) as client:
            async_rows = await client.taifex.daily(kind=kind)  # type: ignore[arg-type]
        assert [r.contract for r in rows] == [r.contract for r in async_rows]
        if kind == "future":
            assert rows[1].session == "after_hours"
            assert rows[1].settlement is None
            assert rows[3].volume == 0 and rows[3].last is None
            assert "/" in rows[-1].contract.expiry
        else:
            assert rows[0].last is None and rows[0].volume == 0
            assert rows[0].settlement == Decimal("96")
            assert rows[0].contract.expiry.endswith("W1")
            assert rows[0].contract.right == "call" and rows[1].contract.right == "put"
            assert rows[0].contract != rows[1].contract


async def test_taifex_historical_csv_preserves_sessions() -> None:
    day = date(2026, 10, 5)
    contract = Contract("TX", "202610")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert b"commodity_id=TX" in request.content
        return response("taifex-history.csv")

    transport = httpx.MockTransport(handler)
    with Client(transport=transport, interval=0) as client:
        rows = client.taifex.history(contract, start=day, end=day)
    async with AsyncClient(transport=transport, interval=0) as client:
        async_rows = await client.taifex.history(contract, start=day, end=day)
    assert len(rows) == len(async_rows) == 2
    assert {r.session for r in rows} == {"regular", "after_hours"}
    regular = next(r for r in rows if r.session == "regular")
    assert regular.last == Decimal("49949")
    assert regular.settlement == Decimal("49944")
    assert all(r.contract == contract and r.date == day for r in rows)
    option = Contract("TXO", "202610W1", "option", Decimal("42800"), "put")
    with Client(
        transport=httpx.MockTransport(lambda r: response("taifex-option-history.csv")),
        interval=0,
    ) as client:
        rows = client.taifex.history(option, start=day, end=day, session="regular")
    assert len(rows) == 1 and rows[0].contract == option
    assert rows[0].last == rows[0].settlement == Decimal("0.2")
