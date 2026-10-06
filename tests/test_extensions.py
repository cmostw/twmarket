"""Source semantics, exact mappings and optional DataFrame integration."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import httpx
import orjson

from twmarket import AsyncClient, Client, Contract
from twmarket.parsing.json import decode, mapping, sequence

FIXTURES = Path(__file__).parent / "fixtures"


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    names = {
        "/www/zh-tw/emerging/historical": "esb-history-correct.fixture",
        "/Quote.asmx/GETQ20": "esb-quote.fixture",
        "/getOD.ashx": "tdcc.csv",
        "/API/DataAPI/Get": "cbc.json",
        "/mops/api/t164sb04": "mops-income.fixture",
        "/mops/api/t164sb03": "mops-balance.fixture",
        "/mops/api/t164sb05": "mops-cashflow.fixture",
        "/mops/api/t05st10_ifrs": "mops-revenue.fixture",
        "/mops/api/t05st09_2": "mops-dividend.fixture",
    }
    if path in names:
        return httpx.Response(200, content=(FIXTURES / names[path]).read_bytes())
    if path == "/Download.ashx":
        filename = (
            "ndc-cycle.fixture"
            if request.url.params.get("icon") == ".zip"
            else "ndc-pmi.fixture"
        )
        return httpx.Response(200, content=(FIXTURES / filename).read_bytes())
    if path.startswith("/futures/api/"):
        body = mapping(decode(request.content))
        if path.endswith("getCmdyMonthDDLItemByKind"):
            filename = (
                "option-months.json" if body["SymbolType"] == "O" else "months.json"
            )
        elif path.endswith("getQuoteList"):
            filename = (
                "option-list.json"
                if body["SymbolType"] == "O"
                else "mapped-future.json"
            )
        else:
            codes = sequence(body["SymbolID"])
            filename = (
                "option-detail.json"
                if str(codes[0]).endswith("-O")
                else "taifex-detail.json"
            )
        response = mapping(decode((FIXTURES / filename).read_bytes()))
        if body.get("MarketType") == "1":

            def night(value: object) -> object:
                if isinstance(value, dict):
                    return {
                        k: night(v) for k, v in cast(dict[str, object], value).items()
                    }
                if isinstance(value, list):
                    return [night(v) for v in cast(list[object], value)]
                if isinstance(value, str) and value.endswith(("-F", "-O")):
                    return value[:-2] + ("-M" if value.endswith("-F") else "-N")
                return value

            response = mapping(night(response))
        return httpx.Response(200, content=orjson.dumps(response))
    raise AssertionError(f"Unexpected request: {request.url}")


async def test_emerging_market_is_not_synthetic_ohlc_or_book() -> None:
    transport = httpx.MockTransport(handler)
    with Client(transport=transport, interval=0) as m:
        rows = m.esb.history("6898", start=date(2026, 9, 1), end=date(2026, 9, 30))
        quote = m.esb.quote("6898")
        assert m.esb.quote_many(["6898"])[0].ok
    async with AsyncClient(transport=transport, interval=0) as m:
        other = await m.esb.quote("6898")
        async_rows = await m.esb.history(
            "6898", start=date(2026, 9, 1), end=date(2026, 9, 30)
        )
        assert [r.weighted_average for r in rows] == [
            r.weighted_average for r in async_rows
        ]
        assert (await m.esb.quote_many(["6898", "6898"]))[0].ok
    assert len(rows) == 20 and rows[0].weighted_average == Decimal("82.24")
    assert not hasattr(rows[0], "open") and not hasattr(rows[0], "close")
    assert quote.weighted_average == other.weighted_average == Decimal("85.7200")
    assert quote.volume == 98661 and quote.broker_quotes
    assert not hasattr(quote, "bids")
    assert quote.quoted_at is not None and quote.quoted_at.hour == 16


async def test_contract_mapping_uses_explicit_period_strike_and_right() -> None:
    transport = httpx.MockTransport(handler)
    with Client(transport=transport, interval=0) as m:
        future = m.taifex.resolve(Contract("TX", "202610"))
        put = m.taifex.resolve(
            Contract("TXO", "202610W1", "option", Decimal("42800"), "put")
        )
        call = m.taifex.resolve(
            Contract("TXO", "202610W1", "option", Decimal("42800"), "call")
        )
        night = m.taifex.resolve(Contract("TX", "202610"), session="after_hours")
        catalog = m.taifex.contracts(product="TX", expiry="202610")
        quote = m.taifex.quote(Contract("TX", "202610"))
    async with AsyncClient(transport=transport, interval=0) as m:
        other = await m.taifex.resolve(Contract("TX", "202610"))
        assert await m.taifex.contracts(product="TX", expiry="202610") == catalog
        async_put = await m.taifex.resolve(put)
        assert async_put == put
        mapped_put = await m.taifex.resolve(
            Contract("TXO", "202610W1", "option", Decimal("42800"), "put")
        )
        assert mapped_put == put
        options = await m.taifex.contracts(
            product="TXO", kind="option", expiry="202610W1"
        )
        assert set(options) == {put, call}
    assert future.mis_symbol == other.mis_symbol == "TXFJ6-F"
    assert put.mis_symbol == "TX142800V6-O" and call.mis_symbol == "TX142800J6-O"
    assert night.mis_symbol == "TXFJ6-M"
    assert catalog == [future] and quote.contract == future
