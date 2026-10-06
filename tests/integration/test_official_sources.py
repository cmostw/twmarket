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
