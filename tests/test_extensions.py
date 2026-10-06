"""Source semantics, exact mappings and optional DataFrame integration."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import httpx
import orjson
import pytest

from twmarket import AsyncClient, Client, Contract
from twmarket.errors import SchemaError
from twmarket.parsing.json import decode, mapping, sequence
from twmarket.providers.mops.data import financial_number

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


async def test_disclosures_preserve_periods_and_source_headings() -> None:
    transport = httpx.MockTransport(handler)
    with Client(transport=transport, interval=0) as m:
        statement = m.mops.income_statement("2330", year=2026, quarter=2)
        balance = m.mops.balance_sheet("2330", year=2026, quarter=2)
        cashflow = m.mops.cash_flow_statement("2330", year=2026, quarter=2)
        revenue = m.mops.revenue("2330", year=2026, month=8)
        dividends = m.mops.dividends("2330", start_year=2025, end_year=2026)
    async with AsyncClient(transport=transport, interval=0) as m:
        other = await m.mops.revenue("2330", year=2026, month=8)
        async_statement = await m.mops.income_statement("2330", year=2026, quarter=2)
        assert (await m.mops.balance_sheet("2330", year=2026, quarter=2)).rows[
            6
        ].value == balance.rows[6].value
        assert (await m.mops.cash_flow_statement("2330", year=2026, quarter=2)).rows[
            2
        ].value == cashflow.rows[2].value
        async_dividends = await m.mops.dividends("2330", start_year=2025, end_year=2026)
    assert (statement.year, statement.quarter, statement.report_type) == (
        2026,
        2,
        "合併",
    )
    assert statement.rows == tuple(
        replace(row, source=statement.source) for row in async_statement.rows
    )
    first = statement.rows[0]
    assert first.account == "營業收入合計" and first.value == Decimal("1270380250")
    assert (first.period_start, first.period_end) == (
        date(2026, 4, 1),
        date(2026, 6, 30),
    )
    assert statement.rows[1].measure == "percentage"
    assert statement.rows[1].value == Decimal("100.00")
    assert statement.rows[4].period_start == date(2026, 1, 1)
    assert balance.rows[0].period_start is None and balance.rows[0].is_empty
    assert balance.rows[6].value == Decimal("3134218213")
    assert cashflow.rows[2].value == Decimal("1550229773")
    assert revenue == replace(other, source=revenue.source) and revenue.month == 8
    assert revenue.current == Decimal("514805337") and revenue.unit == "thousand_TWD"
    assert revenue.change_percent == Decimal("53.32")
    assert dividends == [
        replace(other, source=row.source)
        for row, other in zip(dividends, async_dividends, strict=True)
    ]
    assert dividends[0].cash_from_earnings == Decimal("7.0")
    assert dividends[1].cash_from_earnings == Decimal("7.00000137")
    assert dividends[0].board_date == date(2026, 8, 11)
    assert dividends[0].stock_total_shares == 0 and dividends[0].par_currency == "TWD"
    assert not hasattr(dividends[0], "note") and not hasattr(m.mops, "announcements")


def test_annual_financials_and_preferred_dividends() -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        name = (
            "mops-income-annual.fixture"
            if request.url.path.endswith("t164sb04")
            else "mops-dividend-preferred.fixture"
        )
        return httpx.Response(200, content=(FIXTURES / name).read_bytes())

    with Client(transport=httpx.MockTransport(transport), interval=0) as market:
        annual = market.mops.income_statement("2330", year=2025, quarter=4)
        dividends = market.mops.dividends("2881", start_year=2025, end_year=2026)
    assert (annual.rows[0].period_start, annual.rows[0].period_end) == (
        date(2025, 1, 1),
        date(2025, 12, 31),
    )
    preferred = next(row for row in dividends if row.share_class == "preferred")
    assert preferred.share_name == "2881A 富邦特" and preferred.quarter is None
    assert preferred.cash_from_earnings == Decimal("2.74875")
    assert preferred.period_start == date(2025, 1, 1)


def test_financial_missing_sentinel_and_schema_errors() -> None:
    response = mapping(decode((FIXTURES / "mops-revenue.fixture").read_bytes()))
    rows = sequence(mapping(response["result"])["data"])
    sequence(rows[3])[1] = "999999.99"

    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=orjson.dumps(response))

    with Client(transport=httpx.MockTransport(transport), interval=0) as market:
        revenue = market.mops.revenue("2330", year=2026, month=8)
        assert revenue.change_percent is None and revenue.current == Decimal(
            "514805337"
        )
        sequence(rows[0])[1] = "invalid-number"
        with pytest.raises(SchemaError):
            market.mops.revenue("2330", year=2026, month=8)
    assert financial_number("(1,234.50)") == Decimal("-1234.50")
    assert financial_number("--") is None and financial_number("0") == Decimal(0)
    with pytest.raises(SchemaError):
        financial_number(0.1)


async def test_official_brackets_and_currency_direction() -> None:
    transport = httpx.MockTransport(handler)
    with Client(transport=transport, interval=0) as m:
        brackets = m.tdcc.distribution("000218")
        assert len(m.tdcc.distribution("2330")) == 17
        rates = m.cbc.exchange_rates(
            currency="GBP", start=date(2026, 9, 1), end=date(2026, 9, 30)
        )
        pmi = m.ndc.pmi(start=date(2026, 1, 1), end=date(2026, 9, 30))
        cycle = m.ndc.indicators(start=date(2026, 1, 1), end=date(2026, 9, 30))
    async with AsyncClient(transport=transport, interval=0) as m:
        async_brackets = await m.tdcc.distribution("000218")
        async_rates = await m.cbc.exchange_rates(
            currency="GBP", start=date(2026, 9, 1), end=date(2026, 9, 30)
        )
        async_pmi = await m.ndc.pmi(start=date(2026, 1, 1), end=date(2026, 9, 30))
        assert [
            r.value
            for r in await m.ndc.indicators(
                start=date(2026, 1, 1), end=date(2026, 9, 30)
            )
        ] == [r.value for r in cycle]
    assert len(brackets) == len(async_brackets) == 17
    assert brackets[0].symbol == "000218" and brackets[-1].level == 17
    assert rates[0].numerator == async_rates[0].numerator == "USD"
    assert rates[0].denominator == "GBP"
    assert [r.value for r in pmi] == [r.value for r in async_pmi]
    assert cycle and {r.series for r in pmi} == {"PMI", "NMI"}


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
