"""Explicit, low-rate checks against official endpoints; excluded by default."""

from datetime import date
from decimal import Decimal

import pytest

from twmarket import Client, Contract

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("market,code", [("twse", "2330"), ("tpex", "6223")])
def test_official_stock_history(market: str, code: str) -> None:
    with Client(retries=0) as client:
        provider = client.twse if market == "twse" else client.tpex
        rows = provider.history(code, start=date(2026, 9, 1), end=date(2026, 9, 30))
    assert rows and all(r.symbol == code for r in rows)


@pytest.mark.parametrize("taifex", [False, True])
def test_official_snapshot(taifex: bool) -> None:
    with Client(retries=0) as client:
        quote = client.taifex.quote("TXFJ6-F") if taifex else client.twse.quote("2330")
    assert quote.source.received_at.tzinfo is not None


@pytest.mark.parametrize("option", [False, True])
def test_official_taifex_history(option: bool) -> None:
    contract = (
        Contract("TXO", "202610W1", "option", Decimal("42800"), "put")
        if option
        else Contract("TX", "202610")
    )
    day = date(2026, 10, 5)
    with Client(retries=0) as client:
        rows = client.taifex.history(contract, start=day, end=day)
    assert rows and all(r.contract == contract and r.date == day for r in rows)


def test_official_extended_sources() -> None:
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    with Client(retries=0) as client:
        assert client.mops.income_statement("2330", year=2026, quarter=2).rows
        assert client.tdcc.distribution("2330")
        assert client.ndc.pmi(start=start, end=end)
        assert client.ndc.indicators(start=date(2026, 1, 1), end=end)
        assert client.cbc.exchange_rates(start=start, end=end, currency="NTD")
        mapped = client.taifex.resolve(Contract("CAF", "202610"))
        assert mapped.mis_symbol and client.taifex.quote(mapped).contract == mapped


def test_official_structured_financials() -> None:
    with Client(retries=0) as client:
        for statement in (
            client.mops.income_statement("2330", year=2025, quarter=4),
            client.mops.balance_sheet("2330", year=2026, quarter=2),
            client.mops.cash_flow_statement("2330", year=2026, quarter=2),
        ):
            assert statement.rows and any(
                isinstance(row.value, Decimal) for row in statement.rows
            )
        revenue = client.mops.revenue("2330", year=2026, month=8)
        assert isinstance(revenue.current, Decimal) and revenue.year == 2026
        dividends = client.mops.dividends("2881", start_year=2025, end_year=2026)
        assert any(row.share_class == "preferred" for row in dividends)
        assert all(row.quarter is None for row in dividends)


def test_official_catalog_events_and_specifications() -> None:
    with Client(retries=0, cache_ttl=60) as client:
        assert client.esb.instruments()
        for provider in (client.twse, client.tpex):
            assert provider.index_history(start=date(2026, 9, 1), end=date(2026, 9, 30))
            assert provider.indices()
            assert provider.ex_rights(start=date(2026, 9, 1), end=date(2026, 9, 30))
            assert provider.trading_status()
        assert client.taifex.specification("BRF").multiplier == Decimal(200)
        assert client.taifex.specification("RTF").multiplier == Decimal(20000)
        for category in ("index", "stock", "etf", "fx", "commodity", "interest_rate"):
            assert client.taifex.margins(category=category)
