"""Shared securities orchestration; source-specific parsing remains explicit."""

from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Literal

from twmarket.errors import NoDataError, SchemaError, SourceError
from twmarket.models.batch import BatchResult
from twmarket.models.daily import EquityDaily
from twmarket.models.market import (
    ExRight,
    ExRightSchedule,
    IndexClose,
    IndexDaily,
    Instrument,
    RestrictionKind,
    TradingRestriction,
    TradingStatus,
)
from twmarket.models.quotes import BookLevel, Quote
from twmarket.parsing.dates import TAIPEI, months, parse_date, quote_time
from twmarket.parsing.json import decode, mapping, required, sequence, symbol
from twmarket.parsing.numbers import integer, number
from twmarket.transport.http import AsyncHttp, Http, Payload, Request

from . import _events as events
from ._batch import async_map, batch
from ._catalog import catalog_request, parse_catalog
from ._snapshots import async_snapshots, snapshots

Market = Literal["twse", "tpex"]
TWSE_HISTORY = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
TPEX_HISTORY = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"


def history_requests(
    market: Market, code: str, start: date, end: date
) -> list[Request]:
    code = symbol(code)
    return [
        Request(
            market,
            TWSE_HISTORY if market == "twse" else TPEX_HISTORY,
            {"response": "json", "date": month.strftime("%Y%m%d"), "stockNo": code}
            if market == "twse"
            else {"response": "json", "date": month.strftime("%Y/%m/%d"), "code": code},
        )
        for month in months(start, end)
    ]


def parse_history(payload: Payload, code: str, month: date) -> list[EquityDaily]:
    root = mapping(decode(payload.content))
    tpex = payload.source.provider == "tpex"
    if not tpex:
        status = str(required(root, "stat"))
        if "沒有符合" in status or "查無資料" in status:
            return []
        if status != "OK":
            raise SourceError(status)
        fields = sequence(required(root, "fields"))
        if fields[:7] != [
            "日期",
            "成交股數",
            "成交金額",
            "開盤價",
            "最高價",
            "最低價",
            "收盤價",
        ]:
            raise SchemaError("TWSE historical table headers changed")
        data = sequence(required(root, "data"))
    else:
        tables = sequence(required(root, "tables"))
        if not tables:
            return []
        table = mapping(tables[0])
        data = sequence(required(table, "data"))
    result: list[EquityDaily] = []
    for item in data:
        row = sequence(item)
        if len(row) < 9:
            raise SchemaError("Historical price row has fewer than nine fields")
        day = parse_date(row[0])
        if (day.year, day.month) != (month.year, month.month):
            raise SchemaError("Source returned a different month than requested")
        result.append(
            EquityDaily(
                symbol=code,
                date=day,
                open=number(row[3]),
                high=number(row[4]),
                low=number(row[5]),
                close=number(row[6]),
                volume=integer(row[1]),
                amount=number(row[2]),
                volume_unit="lots" if tpex else "shares",
                amount_unit="thousand_TWD" if tpex else "TWD",
                source=payload.source,
                change=None if str(row[7]).startswith("X") else number(row[7]),
                transactions=integer(row[8]),
                raw_change=str(row[7]),
                change_basis_reset=str(row[7]).startswith("X"),
            )
        )
    return result


def quote_request(market: Market, code: str) -> Request:
    code = symbol(code)
    exchange = "tse" if market == "twse" else "otc"
    return Request(
        market,
        MIS,
        {"ex_ch": f"{exchange}_{code}.tw", "json": "1", "delay": "0"},
        cacheable=False,
    )


def stock_book(
    row: dict[str, object], prices: str, sizes: str
) -> tuple[BookLevel, ...]:
    price_values = str(required(row, prices)).rstrip("_").split("_")
    size_values = str(required(row, sizes)).rstrip("_").split("_")
    if len(price_values) != len(size_values):
        raise SchemaError("MIS book price/size lengths differ")
    levels: list[BookLevel] = []
    for index, (price_value, size_value) in enumerate(
        zip(price_values, size_values, strict=True), 1
    ):
        price = number(price_value)
        if price is not None:
            levels.append(BookLevel(index, price, integer(size_value)))
    return tuple(levels)


def parse_quote(
    payload: Payload, code: str, *, root: dict[str, object] | None = None
) -> Quote:
    root = mapping(decode(payload.content)) if root is None else root
    if str(required(root, "rtcode")) != "0000":
        raise SourceError(str(root.get("rtmessage", "MIS query failed")))
    rows = sequence(required(root, "msgArray"))
    exchange = "tse" if payload.source.provider == "twse" else "otc"
    selected = [
        mapping(r)
        for r in rows
        if mapping(r).get("c") == code and mapping(r).get("ex") == exchange
    ]
    if not selected:
        raise NoDataError(f"No quote for {code}")
    row = selected[0]
    day = parse_date(required(row, "d"))
    stamp = integer(row.get("tlong"))
    quoted_at = (
        datetime.fromtimestamp(stamp / 1000, UTC).astimezone(TAIPEI)
        if stamp is not None
        else quote_time(row.get("d"), row.get("t"))
    )
    return Quote(
        symbol=code,
        last=number(required(row, "z")),
        open=number(required(row, "o")),
        high=number(required(row, "h")),
        low=number(required(row, "l")),
        volume=integer(required(row, "v")),
        volume_unit="lots",
        bids=stock_book(row, "b", "g"),
        asks=stock_book(row, "a", "f"),
        quoted_at=quoted_at,
        source_date=day,
        source=payload.source,
    )


class StockMarket:
    """查詢 TWSE 或 TPEx 的證券、指數與交易狀態.

    English:

    TWSE or TPEx queries through the owning client.

    Security codes are strings. Date ranges include both endpoints.
    """

    def __init__(self, http: Http, market: Market) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http
        self._market: Market = market

    def history(self, code: str, *, start: date, end: date) -> list[EquityDaily]:
        """回傳含起訖兩日的歷史資料；無符合資料時回傳空清單.

        English:

        Return date-sorted daily rows for code within inclusive start/end dates.

        code is a string. Volume/amount units are shares/TWD for TWSE and
        lots/thousand_TWD for TPEx. No matching rows returns an empty list.
        """
        requests = history_requests(self._market, code, start, end)
        rows = [
            row
            for request, month in zip(requests, months(start, end), strict=True)
            for row in parse_history(self._http.fetch(request), symbol(code), month)
        ]
        return sorted((r for r in rows if start <= r.date <= end), key=lambda r: r.date)

    def quote(self, code: str) -> Quote:
        """取得最新報價；價格缺值為 None，查無快照時拋出 NoDataError.

        English:

        Return the latest MIS snapshot for a security code string.

        Quote volume uses lots. Missing prices are None; no snapshot raises NoDataError.
        """
        return parse_quote(
            self._http.fetch(quote_request(self._market, code)), symbol(code)
        )

    def instruments(self, *, category: str | None = None) -> list[Instrument]:
        """取得最新 ISIN 目錄；category 使用來源分類名稱.

        English:

        Return the current ISIN catalog, optionally filtered by source category.

        Codes retain leading zeros. category must match a published category name.
        """
        payload = self._http.fetch(catalog_request(self._market))
        return list(
            self._http.parse_cached(
                (payload,),
                "instruments:" + self._market + ":" + str(category),
                lambda: tuple(parse_catalog(payload, self._market, category)),
            )
        )

    def index_history(self, *, start: date, end: date) -> list[IndexDaily]:
        """回傳含起訖兩日的每日指數 OHLC，依日期排序.

        English:

        Return daily index OHLC rows within the inclusive start/end dates.

        TWSE returns TAIEX and TPEx returns the OTC index; rows are date-sorted.
        """
        rows: list[IndexDaily] = []
        for request, month in zip(
            events.index_requests(self._market, start, end),
            months(start, end),
            strict=True,
        ):
            rows.extend(events.index_history(self._http.fetch(request), month))
        return sorted((r for r in rows if start <= r.date <= end), key=lambda r: r.date)

    def indices(self, *, day: date | None = None) -> list[IndexClose]:
        """取得價格／報酬指數收盤板；day 省略時查來源最新公布資料.

        English:

        Return published price/total-return index closing levels.

        Omit day for the current source board; pass a date for its historical query.
        """
        return events.index_closes(
            self._http.fetch(events.indices_request(self._market, day)), day
        )

    def ex_rights(
        self, *, start: date, end: date, code: str | None = None
    ) -> list[ExRight]:
        """依含起訖兩日的日期區間查詢歷史除權息；code 可篩選證券.

        English:

        Return historical ex-rights/dividend events in the inclusive date range.

        code optionally filters one security; share-allocation units follow the source.
        """
        code = symbol(code) if code is not None else None
        return events.ex_rights(
            self._http.fetch(events.events_request(self._market, start, end)),
            start,
            end,
            code,
        )

    def ex_rights_schedule(self, *, code: str | None = None) -> list[ExRightSchedule]:
        """取得最新除權息預告；code 可篩選證券，未公告值為 None.

        English:

        Return the current upcoming ex-rights/dividend schedule.

        code optionally filters one security; absent announced values are None.
        """
        code = symbol(code) if code is not None else None
        return events.schedules(
            self._http.fetch(events.schedule_request(self._market)), code
        )

    def trading_restrictions(
        self, *, kind: RestrictionKind = "attention", code: str | None = None
    ) -> list[TradingRestriction]:
        """依 kind 查詢注意、處置或最新暫停資料；code 可篩選證券.

        English:

        Return published restrictions, optionally filtered by code.

        kind is attention, disposition or suspended. Suspensions are the current list.
        """
        code = symbol(code) if code is not None else None
        return events.restrictions(
            self._http.fetch(events.restriction_request(self._market, kind)),
            self._market,
            kind,
            code,
        )

    def trading_status(self, *, code: str | None = None) -> list[TradingStatus]:
        """取得最新交易方式及狀態；來源無發布日期時為 None.

        English:

        Return the current trading-method/status list, optionally filtered by code.

        Publication dates are None when the source does not supply them.
        """
        code = symbol(code) if code is not None else None
        return events.trading_status(
            self._http.fetch(events.status_request(self._market)), self._market, code
        )

    def quote_many(self, codes: Iterable[str]) -> list[BatchResult[Quote]]:
        """逐筆回傳 BatchResult，保留輸入順序、重複輸入及個別錯誤.

        English:

        Return one BatchResult per input, preserving order and duplicates.

        Individual validation, source and request failures appear in result.error.
        """
        return snapshots(
            self._http,
            batch(symbol, codes),
            self._batch_request,
            lambda p, c, r: parse_quote(p, c, root=r),
            size=50,
        )

    def _batch_request(self, codes: list[str]) -> Request:
        exchange = "tse" if self._market == "twse" else "otc"
        return Request(
            self._market,
            MIS,
            {
                "ex_ch": "|".join(f"{exchange}_{c}.tw" for c in codes),
                "json": "1",
                "delay": "0",
            },
            cacheable=False,
        )


class AsyncStockMarket:
    """以 await 查詢 TWSE 或 TPEx 證券、指數與交易狀態.

    English:

    Awaitable TWSE or TPEx queries through the owning client.

    Security codes are strings. Date ranges include both endpoints.
    """

    def __init__(self, http: AsyncHttp, market: Market) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http
        self._market: Market = market

    async def history(self, code: str, *, start: date, end: date) -> list[EquityDaily]:
        """回傳含起訖兩日的歷史資料；無符合資料時回傳空清單.

        English:

        Return date-sorted daily rows for code within inclusive start/end dates.

        code is a string. Volume/amount units are shares/TWD for TWSE and
        lots/thousand_TWD for TPEx. No matching rows returns an empty list.
        """
        requests = history_requests(self._market, code, start, end)

        async def fetch(item: tuple[Request, date]) -> list[EquityDaily]:
            request, month = item
            return parse_history(await self._http.fetch(request), symbol(code), month)

        rows = [
            row
            for group in await async_map(
                fetch, zip(requests, months(start, end), strict=True)
            )
            for row in group
        ]
        return sorted((r for r in rows if start <= r.date <= end), key=lambda r: r.date)

    async def quote(self, code: str) -> Quote:
        """取得最新報價；價格缺值為 None，查無快照時拋出 NoDataError.

        English:

        Return the latest MIS snapshot for a security code string.

        Quote volume uses lots. Missing prices are None; no snapshot raises NoDataError.
        """
        return parse_quote(
            await self._http.fetch(quote_request(self._market, code)), symbol(code)
        )

    async def instruments(self, *, category: str | None = None) -> list[Instrument]:
        """取得最新 ISIN 目錄；category 使用來源分類名稱.

        English:

        Return the current ISIN catalog, optionally filtered by source category.

        Codes retain leading zeros. category must match a published category name.
        """
        payload = await self._http.fetch(catalog_request(self._market))
        return list(
            self._http.parse_cached(
                (payload,),
                "instruments:" + self._market + ":" + str(category),
                lambda: tuple(parse_catalog(payload, self._market, category)),
            )
        )

    async def index_history(self, *, start: date, end: date) -> list[IndexDaily]:
        """回傳含起訖兩日的每日指數 OHLC，依日期排序.

        English:

        Return daily index OHLC rows within the inclusive start/end dates.

        TWSE returns TAIEX and TPEx returns the OTC index; rows are date-sorted.
        """

        async def fetch(item: tuple[Request, date]) -> list[IndexDaily]:
            request, month = item
            return events.index_history(await self._http.fetch(request), month)

        rows = [
            row
            for group in await async_map(
                fetch,
                zip(
                    events.index_requests(self._market, start, end),
                    months(start, end),
                    strict=True,
                ),
            )
            for row in group
        ]
        return sorted((r for r in rows if start <= r.date <= end), key=lambda r: r.date)

    async def indices(self, *, day: date | None = None) -> list[IndexClose]:
        """取得價格／報酬指數收盤板；day 省略時查來源最新公布資料.

        English:

        Return published price/total-return index closing levels.

        Omit day for the current source board; pass a date for its historical query.
        """
        return events.index_closes(
            await self._http.fetch(events.indices_request(self._market, day)), day
        )

    async def ex_rights(
        self, *, start: date, end: date, code: str | None = None
    ) -> list[ExRight]:
        """依含起訖兩日的日期區間查詢歷史除權息；code 可篩選證券.

        English:

        Return historical ex-rights/dividend events in the inclusive date range.

        code optionally filters one security; share-allocation units follow the source.
        """
        code = symbol(code) if code is not None else None
        return events.ex_rights(
            await self._http.fetch(events.events_request(self._market, start, end)),
            start,
            end,
            code,
        )

    async def ex_rights_schedule(
        self, *, code: str | None = None
    ) -> list[ExRightSchedule]:
        """取得最新除權息預告；code 可篩選證券，未公告值為 None.

        English:

        Return the current upcoming ex-rights/dividend schedule.

        code optionally filters one security; absent announced values are None.
        """
        code = symbol(code) if code is not None else None
        return events.schedules(
            await self._http.fetch(events.schedule_request(self._market)), code
        )

    async def trading_restrictions(
        self, *, kind: RestrictionKind = "attention", code: str | None = None
    ) -> list[TradingRestriction]:
        """依 kind 查詢注意、處置或最新暫停資料；code 可篩選證券.

        English:

        Return published restrictions, optionally filtered by code.

        kind is attention, disposition or suspended. Suspensions are the current list.
        """
        code = symbol(code) if code is not None else None
        return events.restrictions(
            await self._http.fetch(events.restriction_request(self._market, kind)),
            self._market,
            kind,
            code,
        )

    async def trading_status(self, *, code: str | None = None) -> list[TradingStatus]:
        """取得最新交易方式及狀態；來源無發布日期時為 None.

        English:

        Return the current trading-method/status list, optionally filtered by code.

        Publication dates are None when the source does not supply them.
        """
        code = symbol(code) if code is not None else None
        return events.trading_status(
            await self._http.fetch(events.status_request(self._market)),
            self._market,
            code,
        )

    async def quote_many(self, codes: Iterable[str]) -> list[BatchResult[Quote]]:
        """逐筆回傳 BatchResult，保留輸入順序、重複輸入及個別錯誤.

        English:

        Return one BatchResult per input, preserving order and duplicates.

        Individual validation, source and request failures appear in result.error.
        """
        return await async_snapshots(
            self._http,
            batch(symbol, codes),
            self._batch_request,
            lambda p, c, r: parse_quote(p, c, root=r),
            size=50,
        )

    def _batch_request(self, codes: list[str]) -> Request:
        exchange = "tse" if self._market == "twse" else "otc"
        return Request(
            self._market,
            MIS,
            {
                "ex_ch": "|".join(f"{exchange}_{c}.tw" for c in codes),
                "json": "1",
                "delay": "0",
            },
            cacheable=False,
        )
