"""TPEx emerging-stock historical JSON and official broker-quote XML."""

from collections.abc import Iterable
from datetime import date, datetime
from xml.etree import ElementTree as ET

from twmarket.errors import NoDataError, SchemaError, SourceError
from twmarket.models.batch import BatchResult
from twmarket.models.emerging import BrokerQuote, EmergingDaily, EmergingQuote
from twmarket.models.market import Instrument, RestrictionKind, TradingRestriction
from twmarket.parsing.dates import TAIPEI, months, parse_date
from twmarket.parsing.json import decode, mapping, required, sequence, symbol
from twmarket.parsing.numbers import integer, number
from twmarket.providers import _events as events
from twmarket.providers._batch import async_batch, async_map, batch
from twmarket.providers._catalog import catalog_request, parse_catalog
from twmarket.transport.http import AsyncHttp, Http, Payload, Request

HISTORY = "https://www.tpex.org.tw/www/zh-tw/emerging/historical"
QUOTE = "https://mis.tpex.org.tw/Quote.asmx/GETQ20"
NS = "{http://otcq.daiphy.com/}"


def requests(code: str, start: date, end: date) -> list[Request]:
    code = symbol(code)
    return [
        Request(
            "esb",
            HISTORY,
            {"code": code, "date": m.strftime("%Y/%m/%d"), "response": "json"},
        )
        for m in months(start, end)
    ]


def parse_history(payload: Payload, code: str, month: date) -> list[EmergingDaily]:
    root = mapping(decode(payload.content))
    if str(required(root, "stat")).lower() != "ok":
        raise SourceError(str(root["stat"]))
    result: list[EmergingDaily] = []
    for raw_table in sequence(required(root, "tables")):
        table = mapping(raw_table)
        fields = sequence(required(table, "fields"))
        if fields[:7] != [
            "日期",
            "成交股數",
            "成交金額(元)",
            "成交最高",
            "成交最低",
            "成交均價",
            "筆數",
        ]:
            raise SchemaError("ESB historical headers changed")
        for raw in sequence(required(table, "data")):
            row = sequence(raw)
            if len(row) < 13:
                raise SchemaError("ESB row is truncated")
            day = parse_date(str(row[0]).replace("*", "").replace("＊", ""))
            if (day.year, day.month) != (month.year, month.month):
                raise SchemaError("ESB returned a different month than requested")
            result.append(
                EmergingDaily(
                    code,
                    day,
                    number(row[3]),
                    number(row[4]),
                    number(row[5]),
                    integer(row[1]),
                    number(row[2]),
                    integer(row[6]),
                    payload.source,
                    integer(row[7]),
                    number(row[8]),
                    number(row[9]),
                    number(row[10]),
                    number(row[11]),
                    integer(row[12]),
                )
            )
    return result


def quote_request(code: str) -> Request:
    return Request("esb", QUOTE, form={"SymbolID": symbol(code)}, cacheable=False)


def parse_quote(payload: Payload, code: str) -> EmergingQuote:
    try:
        root = ET.fromstring(payload.content)
    except ET.ParseError as exc:
        raise SchemaError("ESB quote is not valid XML") from exc
    if root.tag != NS + "Q20":
        raise SchemaError("Unexpected ESB quote XML root")

    def value(element: ET.Element, name: str) -> str | None:
        node = element.find(NS + name)
        return node.text.strip() if node is not None and node.text else None

    if value(root, "SymbolID") != code:
        raise NoDataError(f"No ESB quote for {code}")
    day_text = value(root, "TradeDay")
    day = parse_date(day_text) if day_text else None

    def timestamp(clock: str | None) -> datetime | None:
        if day is None or not clock:
            return None
        try:
            time = datetime.strptime(
                clock, "%H:%M:%S" if clock.count(":") == 2 else "%H:%M"
            ).time()
        except ValueError as exc:
            raise SchemaError(f"Invalid ESB quote time: {clock}") from exc
        return datetime.combine(day, time, TAIPEI)

    brokers: list[BrokerQuote] = []
    nodes = root.findall(f"{NS}list/{NS}Q20List")
    if not nodes:
        nodes = root.findall(f"{NS}quotesDetail/{NS}Q20QuotesDetail")
    for row in nodes:
        brokers.append(
            BrokerQuote(
                value(row, "BrokerName") or "",
                number(value(row, "BuyPrice")),
                integer(value(row, "BuyVol")),
                number(value(row, "SellPrice")),
                integer(value(row, "SellVol")),
                timestamp(value(row, "Time")),
            )
        )
    return EmergingQuote(
        code,
        number(value(root, "TradePrice")),
        number(value(root, "TradeStatisticHigh")),
        number(value(root, "TradeStatisticLow")),
        number(value(root, "TradeStatisticAverage")),
        integer(value(root, "TradeStatisticTtlVol")),
        number(value(root, "TradeStatisticTtlAmt")),
        timestamp(value(root, "TradeStatisticTime")),
        tuple(brokers),
        payload.source,
        value(root, "TradeStatusName"),
    )


class ESB:
    """查詢興櫃歷史資料及推薦券商個別報價.

    English:

    Emerging-stock history and individual recommending-broker quotes.

    Security codes are strings. Date ranges include both endpoints.
    """

    def __init__(self, http: Http) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http

    def history(self, code: str, *, start: date, end: date) -> list[EmergingDaily]:
        """回傳含起訖兩日的歷史資料；無符合資料時回傳空清單.

        English:

        Return date-sorted emerging-stock rows in the inclusive date range.

        code is a string. Prices include weighted_average; volume/amount use shares/TWD.
        No matching rows returns an empty list.
        """
        plan = requests(code, start, end)
        rows = [
            r
            for request, month in zip(plan, months(start, end), strict=True)
            for r in parse_history(self._http.fetch(request), symbol(code), month)
        ]
        return sorted((r for r in rows if start <= r.date <= end), key=lambda r: r.date)

    def quote(self, code: str) -> EmergingQuote:
        """取得最新報價；價格缺值為 None，查無快照時拋出 NoDataError.

        English:

        Return the latest trade statistics and individual broker quotes for code.

        Volume uses shares; missing prices are None. No snapshot raises NoDataError.
        """
        return parse_quote(self._http.fetch(quote_request(code)), symbol(code))

    def instruments(self, *, category: str | None = None) -> list[Instrument]:
        """取得最新 ISIN 目錄；category 使用來源分類名稱.

        English:

        Return the current ISIN catalog, optionally filtered by source category.

        Codes retain leading zeros. category must match a published category name.
        """
        payload = self._http.fetch(catalog_request("esb"))
        return list(
            self._http.parse_cached(
                (payload,),
                "instruments:esb:" + str(category),
                lambda: tuple(parse_catalog(payload, "esb", category)),
            )
        )

    def trading_restrictions(
        self, *, kind: RestrictionKind = "attention", code: str | None = None
    ) -> list[TradingRestriction]:
        """依 kind 查詢注意、處置或最新暫停資料；code 可篩選證券.

        English:

        Return attention, disposition or current suspension records.

        code optionally filters one emerging security.
        """
        code = symbol(code) if code is not None else None
        result = events.restrictions(
            self._http.fetch(events.restriction_request("esb", kind)), "esb", kind, code
        )
        if kind == "suspended" and result:
            codes = {item.symbol for item in self.instruments()}
            result = [row for row in result if row.symbol in codes]
        return result

    def quote_many(self, codes: Iterable[str]) -> list[BatchResult[EmergingQuote]]:
        """逐筆回傳 BatchResult，保留輸入順序、重複輸入及個別錯誤.

        English:

        Return one BatchResult per input, preserving order and duplicates.

        Individual validation, source and request failures appear in result.error.
        """
        return batch(self.quote, codes)


class AsyncESB:
    """以 await 查詢興櫃歷史資料及推薦券商個別報價.

    English:

    Awaitable emerging-stock history and recommending-broker quotes.

    Security codes are strings. Date ranges include both endpoints.
    """

    def __init__(self, http: AsyncHttp) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http

    async def history(
        self, code: str, *, start: date, end: date
    ) -> list[EmergingDaily]:
        """回傳含起訖兩日的歷史資料；無符合資料時回傳空清單.

        English:

        Return date-sorted emerging-stock rows in the inclusive date range.

        code is a string. Prices include weighted_average; volume/amount use shares/TWD.
        No matching rows returns an empty list.
        """
        plan = requests(code, start, end)

        async def fetch(item: tuple[Request, date]) -> list[EmergingDaily]:
            request, month = item
            return parse_history(await self._http.fetch(request), symbol(code), month)

        rows = [
            row
            for group in await async_map(
                fetch, zip(plan, months(start, end), strict=True)
            )
            for row in group
        ]
        return sorted((r for r in rows if start <= r.date <= end), key=lambda r: r.date)

    async def quote(self, code: str) -> EmergingQuote:
        """取得最新報價；價格缺值為 None，查無快照時拋出 NoDataError.

        English:

        Return the latest trade statistics and individual broker quotes for code.

        Volume uses shares; missing prices are None. No snapshot raises NoDataError.
        """
        return parse_quote(await self._http.fetch(quote_request(code)), symbol(code))

    async def instruments(self, *, category: str | None = None) -> list[Instrument]:
        """取得最新 ISIN 目錄；category 使用來源分類名稱.

        English:

        Return the current ISIN catalog, optionally filtered by source category.

        Codes retain leading zeros. category must match a published category name.
        """
        payload = await self._http.fetch(catalog_request("esb"))
        return list(
            self._http.parse_cached(
                (payload,),
                "instruments:esb:" + str(category),
                lambda: tuple(parse_catalog(payload, "esb", category)),
            )
        )

    async def trading_restrictions(
        self, *, kind: RestrictionKind = "attention", code: str | None = None
    ) -> list[TradingRestriction]:
        """依 kind 查詢注意、處置或最新暫停資料；code 可篩選證券.

        English:

        Return attention, disposition or current suspension records.

        code optionally filters one emerging security.
        """
        code = symbol(code) if code is not None else None
        result = events.restrictions(
            await self._http.fetch(events.restriction_request("esb", kind)),
            "esb",
            kind,
            code,
        )
        if kind == "suspended" and result:
            codes = {item.symbol for item in await self.instruments()}
            result = [row for row in result if row.symbol in codes]
        return result

    async def quote_many(
        self, codes: Iterable[str]
    ) -> list[BatchResult[EmergingQuote]]:
        """逐筆回傳 BatchResult，保留輸入順序、重複輸入及個別錯誤.

        English:

        Return one BatchResult per input, preserving order and duplicates.

        Individual validation, source and request failures appear in result.error.
        """
        return await async_batch(self.quote, codes)
