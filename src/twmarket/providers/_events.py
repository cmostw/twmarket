"""Official index series, ex-rights events and structured trading restrictions."""

import re
from datetime import date
from typing import Literal

from twmarket.errors import SchemaError, SourceError
from twmarket.models.market import (
    EventKind,
    ExRight,
    ExRightSchedule,
    IndexClose,
    IndexDaily,
    Market,
    RestrictionKind,
    TradingRestriction,
    TradingStatus,
)
from twmarket.parsing.dates import months, parse_date, quote_time
from twmarket.parsing.json import decode, mapping, required, sequence
from twmarket.parsing.numbers import integer, number
from twmarket.parsing.tables import document
from twmarket.transport.http import Payload, Request

TWSE = "https://www.twse.com.tw/rwd/zh/"
TPEX = "https://www.tpex.org.tw/www/zh-tw/"
TPEX_API = "https://www.tpex.org.tw/openapi/v1/"
TWSE_API = "https://openapi.twse.com.tw/v1/"


def rows_status(root: dict[str, object]) -> None:
    status = str(root.get("stat", "ok"))
    if status.lower() != "ok" and not any(
        v in status for v in ("沒有符合", "查無資料", "無資料", "本日無暫停/恢復交易")
    ):
        raise SourceError(status)


def index_requests(
    market: Literal["twse", "tpex"], start: date, end: date
) -> list[Request]:
    return [
        Request(
            market,
            TWSE + "TAIEX/MI_5MINS_HIST"
            if market == "twse"
            else TPEX + "indexInfo/inx",
            {
                "date": month.strftime("%Y%m%d" if market == "twse" else "%Y/%m/%d"),
                "response": "json",
            },
        )
        for month in months(start, end)
    ]


def index_history(payload: Payload, month: date) -> list[IndexDaily]:
    root = mapping(decode(payload.content))
    rows_status(root)
    tpex = payload.source.provider == "tpex"
    if tpex:
        tables = sequence(required(root, "tables"))
        if not tables:
            return []
        table = mapping(tables[0])
        expected = ["日期", "開市", "最高", "最低", "收市", "漲/跌"]
    else:
        if "data" not in root:
            return []
        table = root
        expected = ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"]
    if sequence(required(table, "fields")) != expected:
        raise SchemaError("Index history headings changed")
    result: list[IndexDaily] = []
    for value in sequence(required(table, "data")):
        row = sequence(value)
        if len(row) != len(expected):
            raise SchemaError("Index history row width changed")
        day = parse_date(row[0])
        if (day.year, day.month) != (month.year, month.month):
            raise SchemaError("Index source returned a different month")
        result.append(
            IndexDaily(
                "TPEX" if tpex else "TAIEX",
                day,
                number(row[1]),
                number(row[2]),
                number(row[3]),
                number(row[4]),
                payload.source,
                number(row[5]) if tpex else None,
            )
        )
    return result


def indices_request(market: Literal["twse", "tpex"], day: date | None) -> Request:
    if market == "tpex":
        params = {"response": "json"}
        if day is not None:
            params["date"] = day.strftime("%Y/%m/%d")
        return Request(market, TPEX + "afterTrading/indexSummary", params)
    params = {"type": "IND", "response": "json"}
    if day is not None:
        params["date"] = day.strftime("%Y%m%d")
    return Request(market, TWSE + "afterTrading/MI_INDEX", params)


def index_closes(payload: Payload, day: date | None) -> list[IndexClose]:
    root = mapping(decode(payload.content))
    rows_status(root)
    if "tables" not in root:
        return []
    actual = parse_date(required(root, "date"))
    if day is not None and actual != day:
        raise SchemaError("Index source returned a different date")
    result: list[IndexClose] = []
    if payload.source.provider == "tpex":
        for raw in sequence(root["tables"]):
            table = mapping(raw)
            fields = sequence(required(table, "fields"))
            if (
                len(fields) != 5
                or fields[0] not in {"指數", "報酬指數"}
                or fields[1:]
                != [
                    "收市指數",
                    "漲跌",
                    "漲跌幅度(%)",
                    "大盤資訊連結",
                ]
            ):
                raise SchemaError("TPEx index close headings changed")
            for value in sequence(required(table, "data")):
                row = sequence(value)
                if len(row) != 5:
                    raise SchemaError("TPEx index close row width changed")
                result.append(
                    IndexClose(
                        str(row[0]),
                        actual,
                        "total_return" if fields[0] == "報酬指數" else "price",
                        "櫃買中心",
                        number(row[1]),
                        number(row[2]),
                        number(row[3]),
                        payload.source,
                    )
                )
        return result
    for raw in sequence(required(root, "tables")):
        table = mapping(raw)
        if "fields" not in table:
            continue
        fields = sequence(table["fields"])
        if len(fields) != 6 or fields[0] not in {"指數", "報酬指數"}:
            raise SchemaError("Index close headings changed")
        title = str(required(table, "title"))
        match = re.search(r"[（(](.+)[）)]", title)
        if match is None:
            raise SchemaError("Index table has no publisher")
        for value in sequence(required(table, "data")):
            row = sequence(value)
            if len(row) != 6:
                raise SchemaError("Index close row width changed")
            sign = (
                document(str(row[2]).encode()).text_content().strip() if row[2] else ""
            )
            change = number(row[3])
            if sign not in {"", "+", "-"}:
                raise SchemaError("Unknown index change sign")
            if change is not None and sign == "-":
                change = -abs(change)
            result.append(
                IndexClose(
                    str(row[0]),
                    actual,
                    "total_return" if fields[0] == "報酬指數" else "price",
                    match[1],
                    number(row[1]),
                    change,
                    number(row[4]),
                    payload.source,
                    bool(row[5]),
                )
            )
    return result


def event_kind(value: object) -> EventKind:
    kinds: dict[str, EventKind] = {
        "息": "dividend",
        "除息": "dividend",
        "權": "rights",
        "除權": "rights",
        "權息": "rights_and_dividend",
        "除權息": "rights_and_dividend",
        "權+息": "rights_and_dividend",
    }
    try:
        return kinds[str(value).strip()]
    except KeyError as exc:
        raise SchemaError(f"Unknown ex-rights event kind: {value!r}") from exc


def events_request(market: Literal["twse", "tpex"], start: date, end: date) -> Request:
    list(months(start, end))  # Shared date-range/type validation.
    fmt = "%Y%m%d" if market == "twse" else "%Y/%m/%d"
    return Request(
        market,
        TWSE + "exRight/TWT49U" if market == "twse" else TPEX + "bulletin/exDailyQ",
        {
            "startDate": start.strftime(fmt),
            "endDate": end.strftime(fmt),
            "response": "json",
        },
    )


def ex_rights(
    payload: Payload, start: date, end: date, code: str | None
) -> list[ExRight]:
    root = mapping(decode(payload.content))
    rows_status(root)
    tpex = payload.source.provider == "tpex"
    if tpex:
        tables = sequence(required(root, "tables"))
        if not tables:
            return []
        table = mapping(tables[0])
        expected = [
            "除權息日期",
            "代號",
            "名稱",
            "除權息前收盤價",
            "除權息參考價",
            "權值",
            "息值",
            "權值+息值",
            "權/息",
            "漲停價",
            "跌停價",
            "開始交易基準價",
            "減除股利參考價",
            "現金股利",
            "每仟股無償配股",
            "現金增資股數",
            "現金增資認購價",
            "公開承銷股數",
            "員工認購股數",
            "原股東認購股數",
            "按持股比例仟股認購",
        ]
    else:
        if "data" not in root:
            return []
        table = root
        expected = [
            "資料日期",
            "股票代號",
            "股票名稱",
            "除權息前收盤價",
            "除權息參考價",
            "權值+息值",
            "權/息",
            "漲停價格",
            "跌停價格",
            "開盤競價基準",
            "減除股利參考價",
            "詳細資料",
            "最近一次申報資料 季別/日期",
            "最近一次申報每股 (單位)淨值",
            "最近一次申報每股 (單位)盈餘",
        ]
    if sequence(required(table, "fields")) != expected:
        raise SchemaError("Ex-rights headings changed")
    result: list[ExRight] = []
    for value in sequence(required(table, "data")):
        row = sequence(value)
        if len(row) != len(expected):
            raise SchemaError("Ex-rights row width changed")
        day = parse_date(re.sub(r"年|月", "/", str(row[0])).replace("日", ""))
        if not start <= day <= end:
            raise SchemaError(
                "Ex-rights source returned a date outside the requested range"
            )
        if code is not None and str(row[1]).strip() != code:
            continue
        result.append(
            ExRight(
                str(row[1]).strip(),
                day,
                str(row[2]).strip(),
                event_kind(row[8 if tpex else 6]),
                number(row[3]),
                number(row[4]),
                number(row[7 if tpex else 5]),
                number(row[9 if tpex else 7]),
                number(row[10 if tpex else 8]),
                number(row[11 if tpex else 9]),
                number(row[12 if tpex else 10]),
                payload.source,
                number(row[5]) if tpex else None,
                number(row[6]) if tpex else None,
                number(row[13]) if tpex else None,
                number(row[14]) if tpex else None,
                integer(row[15]) if tpex else None,
                number(row[16]) if tpex else None,
                integer(row[17]) if tpex else None,
                integer(row[18]) if tpex else None,
                integer(row[19]) if tpex else None,
                number(row[20]) if tpex else None,
            )
        )
    return result


def schedule_request(market: Literal["twse", "tpex"]) -> Request:
    return Request(
        market,
        TWSE_API + "exchangeReport/TWT48U_ALL"
        if market == "twse"
        else TPEX_API + "tpex_exright_prepost",
    )


def schedules(payload: Payload, code: str | None) -> list[ExRightSchedule]:
    tpex = payload.source.provider == "tpex"
    keys = (
        [
            "SecuritiesCompanyCode",
            "ExRrightsExDividendDate",
            "CompanyName",
            "ExRrightsExDividend",
            "CashDividend",
            "StockDividendRatio",
            "SubscriptionRatioToNewSharesIssued",
            "SubscriptionPricePerShare",
            "AllocatedForPublicUnderwriting",
            "SubscribedByEmployees",
            "SubscribedByExistingShareholders",
            "SubscribedProRataInThousandShares",
        ]
        if tpex
        else [
            "Code",
            "Date",
            "Name",
            "Exdividend",
            "CashDividend",
            "StockDividendRatio",
            "SubscriptionRatio",
            "SubscriptionPricePerShare",
            "SharesOffered",
            "SharesEmpOwner",
            "SharesholderOwner",
            "StockHoldingRatio",
        ]
    )
    result: list[ExRightSchedule] = []
    for value in sequence(decode(payload.content)):
        row = mapping(value)
        values = [required(row, key) for key in keys]
        values = [None if v == "尚未公告" else v for v in values]
        if not values[0] or (code is not None and values[0] != code):
            continue
        result.append(
            ExRightSchedule(
                str(values[0]),
                parse_date(values[1]),
                str(values[2]),
                event_kind(values[3]),
                number(values[4]),
                number(values[5]),
                number(values[6]),
                number(values[7]),
                integer(values[8]),
                integer(values[9]),
                integer(values[10]),
                number(values[11]),
                payload.source,
            )
        )
    return result


def restriction_request(market: Market, kind: RestrictionKind) -> Request:
    paths = {
        "twse": {
            "attention": TWSE_API + "announcement/notice",
            "disposition": TWSE_API + "announcement/punish",
            "suspended": TWSE_API + "exchangeReport/TWTAWU",
        },
        "tpex": {
            "attention": TPEX_API + "tpex_trading_warning_information",
            "disposition": TPEX_API + "tpex_disposal_information",
        },
        "esb": {
            "attention": TPEX_API + "tpex_esb_warning_information",
            "disposition": TPEX_API + "tpex_esb_disposal_information",
        },
    }
    if kind not in {"attention", "disposition", "suspended"}:
        raise ValueError("Invalid restriction kind")
    if kind not in paths[market]:
        return Request(market, TPEX + "bulletin/sprc", {"response": "json"})
    return Request(market, paths[market][kind])


def restrictions(
    payload: Payload, market: Market, kind: RestrictionKind, code: str | None
) -> list[TradingRestriction]:
    result: list[TradingRestriction] = []
    decoded = decode(payload.content)
    if kind == "suspended" and market != "twse":
        root = mapping(decoded)
        rows_status(root)
        for raw in sequence(required(root, "tables")):
            table = mapping(raw)
            if sequence(required(table, "fields")) != [
                "有價證券類別",
                "有價證券代號",
                "有價證券名稱",
                "暫停交易",
                "恢復交易",
            ]:
                raise SchemaError("TPEx suspension headings changed")
            for value in sequence(required(table, "data")):
                row = sequence(value)
                if len(row) != 5:
                    raise SchemaError("TPEx suspension row width changed")
                if code is not None and row[1] != code:
                    continue
                result.append(
                    TradingRestriction(
                        str(row[1]),
                        str(row[2]),
                        market,
                        kind,
                        None,
                        restriction_date(row[3]),
                        restriction_date(row[4]),
                        payload.source,
                    )
                )
        return result
    for value in sequence(decoded):
        row = mapping(value)
        symbol_key = (
            "Code"
            if market == "twse"
            else "證券代號"
            if market == "esb"
            else "SecuritiesCompanyCode"
        )
        instrument = str(required(row, symbol_key)).strip()
        if not instrument or (code is not None and instrument != code):
            continue
        name = str(
            required(
                row,
                "Name"
                if market == "twse"
                else "證券名稱"
                if market == "esb"
                else "CompanyName",
            )
        )
        stamp = (
            row.get("Date")
            if market != "esb"
            else row.get("公布日期", row.get("公告日期"))
        )
        announced = parse_date(stamp) if stamp else None
        start, end, halted_at, resumed_at = None, None, None, None
        if kind == "disposition":
            interval = str(
                required(
                    row, "處置起訖時間" if market == "esb" else "DispositionPeriod"
                )
            )
            parts = re.split(r"[~～至]", interval)
            if len(parts) != 2:
                raise SchemaError("Invalid disposition period")
            start, end = parse_date(parts[0].strip()), parse_date(parts[1].strip())
        elif kind == "suspended":
            start = parse_date(required(row, "TradingHaltDate"))
            resume = required(row, "TradingResumptionDate")
            end = parse_date(resume) if resume else None
            halted_at = quote_time(row["TradingHaltDate"], row.get("TradingHaltTime"))
            resumed_at = quote_time(resume, row.get("TradingResumptionTime"))
        result.append(
            TradingRestriction(
                instrument,
                name,
                market,
                kind,
                announced,
                start,
                end,
                payload.source,
                halted_at,
                resumed_at,
                number(
                    row.get(
                        "ClosingPrice"
                        if market == "twse"
                        else "收盤價"
                        if market == "esb"
                        else "ClosePrice"
                    )
                ),
                number(row.get("PE" if market == "twse" else "PriceEarningRatio")),
            )
        )
    return result


def restriction_date(value: object) -> date | None:
    if not value or str(value).strip() in {"-", "--"}:
        return None
    return parse_date(str(value).strip())


def status_request(market: Literal["twse", "tpex"]) -> Request:
    return Request(
        market,
        TWSE_API + "exchangeReport/TWT85U"
        if market == "twse"
        else TPEX + "afterTrading/chtm",
        {"response": "json"} if market == "tpex" else None,
    )


def trading_status(
    payload: Payload, market: Literal["twse", "tpex"], code: str | None
) -> list[TradingStatus]:
    decoded = decode(payload.content)
    result: list[TradingStatus] = []
    if market == "twse":
        for raw in sequence(decoded):
            row = mapping(raw)
            instrument = str(required(row, "Code"))
            if not instrument or (code is not None and instrument != code):
                continue
            flag = str(required(row, "PeriodicCallAuctionTrading")).strip()
            if flag not in {"", "Y", "N", "是", "否", "Ｙ", "Ｎ", "**"}:
                raise SchemaError("Unknown periodic-auction flag")
            result.append(
                TradingStatus(
                    instrument,
                    str(required(row, "Name")),
                    market,
                    None,
                    True,
                    flag in {"Y", "Ｙ", "是", "**"},
                    None,
                    None,
                    None,
                    payload.source,
                )
            )
        return result
    root = mapping(decoded)
    rows_status(root)
    actual = parse_date(required(root, "date"))
    for raw in sequence(required(root, "tables")):
        table = mapping(raw)
        if sequence(required(table, "fields")) != [
            "證券代號",
            "證券名稱",
            "變更交易",
            "分盤交易",
            "屬管理股票",
            "分盤或管理股票撮合循環時間(分鐘)",
            "停止交易",
            "財務資訊重點專區",
            "公告連結",
            "財務重點專區連結",
        ]:
            raise SchemaError("TPEx trading-status headings changed")
        for raw in sequence(required(table, "data")):
            row = sequence(raw)
            if len(row) != 10:
                raise SchemaError("TPEx trading-status width changed")
            if code is not None and row[0] != code:
                continue
            flags = [str(row[i]).strip() for i in [2, 3, 4, 6]]
            if any(flag not in {"", "Y", "Ｙ", "N", "Ｎ"} for flag in flags):
                raise SchemaError("Unknown trading-status flag")
            result.append(
                TradingStatus(
                    str(row[0]),
                    str(row[1]),
                    market,
                    actual,
                    flags[0] in {"Y", "Ｙ"},
                    flags[1] in {"Y", "Ｙ"},
                    flags[2] in {"Y", "Ｙ"},
                    flags[3] in {"Y", "Ｙ"},
                    integer(row[5]),
                    payload.source,
                )
            )
    return result
