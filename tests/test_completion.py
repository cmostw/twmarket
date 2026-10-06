"""Catalogs, source events, contract specifications and batch frame semantics."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import httpx
import pytest

from twmarket import AsyncClient, Client, Contract
from twmarket.errors import NoDataError, SchemaError
from twmarket.integrations import to_pandas, to_polars
from twmarket.parsing.dates import parse_date

FIXTURES = Path(__file__).parent / "fixtures"


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "isin.twse.com.tw":
        market = {"2": "twse", "4": "tpex", "5": "esb"}[request.url.params["strMode"]]
        filename = f"catalog-{market}.fixture"
    else:
        paths = {
            "/rwd/zh/TAIEX/MI_5MINS_HIST": "twse-index-history.fixture",
            "/www/zh-tw/indexInfo/inx": "tpex-index-history.fixture",
            "/rwd/zh/afterTrading/MI_INDEX": "twse-indices.fixture",
            "/www/zh-tw/afterTrading/indexSummary": "tpex-closes.fixture",
            "/rwd/zh/exRight/TWT49U": "twse-ex-rights.fixture",
            "/www/zh-tw/bulletin/exDailyQ": "tpex-ex-rights.fixture",
            "/v1/exchangeReport/TWT48U_ALL": "twse-schedule.fixture",
            "/openapi/v1/tpex_exright_prepost": "tpex-schedule.fixture",
            "/v1/announcement/notice": "twse-warning.fixture",
            "/v1/announcement/punish": "twse-disposal.fixture",
            "/v1/exchangeReport/TWTAWU": "twse-suspended.fixture",
            "/openapi/v1/tpex_trading_warning_information": "tpex-warning.fixture",
            "/openapi/v1/tpex_disposal_information": "tpex-disposal.fixture",
            "/openapi/v1/tpex_esb_warning_information": "esb-warning.fixture",
            "/openapi/v1/tpex_esb_disposal_information": "esb-disposal.fixture",
            "/www/zh-tw/bulletin/sprc": "tpex-halt.fixture",
            "/v1/exchangeReport/TWT85U": "twse-trading-status.fixture",
            "/www/zh-tw/afterTrading/chtm": "tpex-status.fixture",
            "/cht/2/tX": "taifex-tx.fixture",
            "/cht/2/tXO": "taifex-options-spec.fixture",
            "/cht/2/sTF": "taifex-stock-spec.fixture",
            "/cht/2/sSO": "taifex-option-stock-spec.fixture",
            "/cht/2/stockLists": "taifex-stock-list.fixture",
            "/v1/IndexFuturesAndOptionsMargining": "margin-index.fixture",
            "/v1/SingleStockFuturesMargining": "margin-stock.fixture",
            "/v1/SingleStockFuturesETFMargining": "margin-etf.fixture",
            "/v1/FXFuturesAndOptionsMargining": "margin-fx.fixture",
            "/v1/GoldFuturesAndOptionsMargining": "margin-commodity.fixture",
            "/v1/InterestRateFuturesMargining": "margin-interest_rate.fixture",
            "/stock/api/getStockInfo.jsp": "stock-mis.json",
            "/exchangeReport/STOCK_DAY": "twse.json",
        }
        if request.url.path == "/futures/api/getCmdyDDLItemByKind":
            import orjson

            body = cast(dict[str, str], orjson.loads(request.content))
            filename = f"mis-products-{body['SymbolType']}.fixture"
        elif request.url.path == "/futures/api/getCmdyMonthDDLItemByKind":
            filename = "caf-months.fixture"
        elif request.url.path == "/futures/api/getQuoteList":
            filename = "caf-list.fixture"
        else:
            filename = paths[request.url.path]
    return httpx.Response(200, content=(FIXTURES / filename).read_bytes())


async def test_catalog_identifiers_and_async_equivalence() -> None:
    transport = httpx.MockTransport(handler)
    with Client(transport=transport, interval=0) as market:
        catalogs = [
            market.twse.instruments(),
            market.tpex.instruments(),
            market.esb.instruments(),
        ]
    async with AsyncClient(transport=transport, interval=0) as market:
        asynchronous = await market.esb.instruments()
    assert [row.symbol for row in catalogs[2]] == [row.symbol for row in asynchronous]
    etf = next(row for row in catalogs[0] if row.symbol == "0050")
    assert etf.category == "ETF" and etf.isin and etf.as_of == date(2026, 10, 6)
    assert etf.listed_on == date(2003, 6, 30)
    assert all(row.market == "esb" and row.category == "股票" for row in catalogs[2])


async def test_indices_events_and_market_status_semantics() -> None:
    transport = httpx.MockTransport(handler)
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    with Client(transport=transport, interval=0) as client:
        for market in [client.twse, client.tpex]:
            history = market.index_history(start=start, end=end)
            indices = market.indices(day=date(2026, 10, 5))
            events = market.ex_rights(start=start, end=end)
            assert len(history) == 20 and history[0].date == start
            assert {row.kind for row in indices} == {"price", "total_return"}
            assert any(row.change is not None and row.change < 0 for row in indices)
            assert events and all(start <= row.date <= end for row in events)
            assert market.ex_rights_schedule()
            assert market.trading_restrictions(kind="disposition")
            assert market.trading_status()
        halt = client.twse.trading_restrictions(kind="suspended")[0]
        assert halt.starts_on == date(2026, 8, 13) and halt.halted_at is not None
        assert halt.halted_at.utcoffset() is not None and halt.halted_at.hour == 8
        assert client.tpex.trading_restrictions(kind="suspended") == []
        assert client.esb.trading_restrictions(kind="attention")
        assert client.esb.trading_restrictions(kind="disposition") == []
        rights = client.tpex.ex_rights(start=start, end=end, code="4760")[0]
        assert rights.kind == "rights" and rights.bonus_shares_per_thousand == Decimal(
            "19.93215453"
        )
        assert not hasattr(rights, "reason")
    async with AsyncClient(transport=transport, interval=0) as client:
        other = await client.tpex.index_history(start=start, end=end)
        with pytest.raises(SchemaError, match="date"):
            await client.twse.indices(day=date(2026, 10, 6))
        assert await client.twse.ex_rights(start=start, end=end)
        assert await client.esb.trading_restrictions(kind="attention")
        assert len(other) == 20
        assert await client.twse.indices(day=date(2026, 10, 5))
        assert await client.tpex.ex_rights_schedule()
        assert await client.tpex.trading_status()
    assert parse_date("1150813") == date(2026, 8, 13)


async def test_derivative_specs_margin_units_and_report_code_mapping() -> None:
    transport = httpx.MockTransport(handler)
    with Client(transport=transport, interval=0) as client:
        products = client.taifex.products()
        assert len(products) == 369
        tx = client.taifex.specification("TX")
        option = client.taifex.specification("TXO", kind="option")
        normal = client.taifex.specification("CAF")
        mini = next(row for row in products if row.product == "QFF")
        assert tx.multiplier == Decimal(200) and tx.currency == "TWD"
        assert tx.ticks[0].tick == Decimal(1) and tx.settlement == "cash"
        assert option.multiplier == Decimal(50) and len(option.ticks) == 5
        assert option.ticks[0].upper == Decimal(10) and option.ticks[1].tick == Decimal(
            "0.5"
        )
        assert normal.multiplier == 2000 and normal.multiplier_source is not None
        assert mini.multiplier == 100 and mini.underlying == "2330"
        stock = client.taifex.margins(category="stock", product="CA")[0]
        assert (
            stock.initial == Decimal("20.25")
            and stock.unit == "percent"
            and stock.group == 3
        )
        assert client.taifex.margins(product="TX")[0].initial == Decimal(701000)
        assert {row.component for row in client.taifex.margins(product="TXO")} == {
            "A",
            "B",
            "C",
        }
        assert client.taifex.margins(category="etf", product="0050")
        assert client.taifex.margins(category="fx")
        assert client.taifex.margins(category="commodity")
        assert client.taifex.margins(category="interest_rate")[0].date == date(
            2019, 9, 11
        )
        resolved = client.taifex.resolve(Contract("CA", "202610"))
        assert resolved.mis_symbol == "CAFJ6-F" and resolved.expires_on == date(
            2026, 10, 21
        )
    async with AsyncClient(transport=transport, interval=0) as client:
        other = await client.taifex.specification("TX")
        assert other.multiplier == tx.multiplier
        assert await client.taifex.margins(category="stock", product="CA")
        assert (
            await client.taifex.resolve(Contract("CA", "202610"))
        ).mis_symbol == resolved.mis_symbol
    assert [leg.expiry for leg in Contract("TX", "202610/202611").legs] == [
        "202610",
        "202611",
    ]


def test_batch_frames_preserve_errors_and_request_identity() -> None:
    from twmarket import BatchResult, Quote

    with Client(transport=httpx.MockTransport(handler), interval=0) as client:
        rows = client.twse.quote_many(["2330", "0000", "2330"])
    pandas = to_pandas(rows)
    polars = to_polars(rows)
    assert pandas["requested_symbol"].tolist() == ["2330", "0000", "2330"]
    assert polars["error_type"].to_list() == [None, "NoDataError", None]
    assert polars["last"][1] is None
    failed = [BatchResult[Quote]("0000", None, NoDataError("missing"))]
    assert to_polars(failed, model=Quote).height == 1
    with pytest.raises(TypeError, match="model"):
        to_pandas(failed)


def test_non_index_contract_specifications() -> None:
    for code, size, unit, tick in [
        ("GDF", "1", "troy_ounces", "0.1"),
        ("TGF", "1", "taiwan_taels", "0.5"),
        ("RTF", "20000", "USD", "0.0001"),
        ("XEF", "20000", "EUR", "0.0001"),
        ("BRF", "200", "barrels", "0.5"),
    ]:
        from datetime import UTC, datetime

        from twmarket.models.common import SourceInfo
        from twmarket.models.derivatives import DerivativeProduct
        from twmarket.providers.taifex.metadata import specification
        from twmarket.transport.http import Payload

        source = SourceInfo(
            "taifex", "https://www.taifex.com.tw/cht/2/" + code, datetime.now(UTC)
        )
        payload = Payload(
            (FIXTURES / ("spec-" + code + ".fixture")).read_bytes(), source
        )
        row = specification(
            payload, DerivativeProduct(code, code, "future", source.url, source)
        )
        assert row.multiplier == Decimal(size) and row.multiplier_unit == unit
        assert row.ticks[0].tick == Decimal(tick)
