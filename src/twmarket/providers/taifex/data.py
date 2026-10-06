"""TAIFEX daily JSON, historical CSV, and explicit MIS-symbol quotes."""

import calendar
import csv
import io
from datetime import date
from typing import Literal

from twmarket.errors import (
    NoDataError,
    SchemaError,
    SourceError,
    UnsupportedFeatureError,
)
from twmarket.models.daily import DerivativeDaily
from twmarket.models.instruments import Contract, InstrumentKind, Session
from twmarket.models.quotes import BookLevel, Quote
from twmarket.parsing.dates import months, parse_date, quote_time
from twmarket.parsing.json import decode, mapping, required, sequence, symbol
from twmarket.parsing.numbers import integer, number
from twmarket.transport.http import Payload, Request

DAILY = "https://openapi.taifex.com.tw/v1/DailyMarketReport"
DOWNLOAD = "https://www.taifex.com.tw/cht/3/"
MIS = "https://mis.taifex.com.tw/futures/api/getQuoteDetail"
CSV_FIELDS = {
    "交易日期": "Date",
    "契約": "Contract",
    "到期月份(週別)": "ContractMonth(Week)",
    "履約價": "StrikePrice",
    "買賣權": "CallPut",
    "開盤價": "Open",
    "最高價": "High",
    "最低價": "Low",
    "收盤價": "Last",
    "成交量": "Volume",
    "結算價": "SettlementPrice",
    "未沖銷契約數": "OpenInterest",
    "交易時段": "TradingSession",
}


def validate_kind(kind: InstrumentKind) -> None:
    if kind not in {"future", "option"}:
        raise ValueError("kind must be 'future' or 'option'")


def daily_request(kind: InstrumentKind) -> Request:
    validate_kind(kind)
    return Request("taifex", DAILY + ("Fut" if kind == "future" else "Opt"))


def history_request(
    contract: Contract, start: date, end: date, session: Session | None = None
) -> Request:
    validate_kind(contract.kind)
    if session not in {None, "regular", "after_hours"}:
        raise ValueError("Invalid session")
    list(months(start, end))
    if (end - start).days > 30:
        raise ValueError("TAIFEX history accepts at most 31 calendar days per query")
    return Request(
        "taifex",
        DOWNLOAD + ("futDataDown" if contract.kind == "future" else "optDataDown"),
        form={
            "queryStartDate": start.strftime("%Y/%m/%d"),
            "queryEndDate": end.strftime("%Y/%m/%d"),
            "down_type": "1",
            "commodity_id": symbol(contract.product),
            "commodity_id2": "",
        },
    )


def history_requests(
    contract: Contract, start: date, end: date, session: Session | None
) -> list[Request]:
    """Partition long ranges into source queries of at most one calendar month."""
    return [
        history_request(
            contract,
            max(start, month),
            min(
                end, month.replace(day=calendar.monthrange(month.year, month.month)[1])
            ),
            session,
        )
        for month in months(start, end)
    ]


def parse_daily_rows(
    rows: list[object],
    source: Payload,
    kind: InstrumentKind,
    product: str | None = None,
) -> list[DerivativeDaily]:
    result: list[DerivativeDaily] = []
    for value in rows:
        row = mapping(value)
        if product is not None and str(required(row, "Contract")).strip() != product:
            continue
        session_value = required(row, "TradingSession")
        if session_value not in {"一般", "盤後"}:
            raise SchemaError(f"Unknown TAIFEX session: {session_value}")
        session: Session = "regular" if session_value == "一般" else "after_hours"
        right: Literal["call", "put"] | None = None
        if kind == "option":
            raw_right = required(row, "CallPut")
            if raw_right not in {"買權", "賣權"}:
                raise SchemaError(f"Unknown option right: {raw_right}")
            right = "call" if raw_right == "買權" else "put"
        contract = Contract(
            str(required(row, "Contract")).strip(),
            str(required(row, "ContractMonth(Week)")).strip(),
            kind,
            number(required(row, "StrikePrice")) if kind == "option" else None,
            right,
        )
        last_key = "Close" if "Close" in row else "Last"
        result.append(
            DerivativeDaily(
                contract=contract,
                date=parse_date(required(row, "Date")),
                session=session,
                open=number(required(row, "Open")),
                high=number(required(row, "High")),
                low=number(required(row, "Low")),
                last=number(required(row, last_key)),
                settlement=number(required(row, "SettlementPrice")),
                volume=integer(required(row, "Volume")),
                open_interest=integer(required(row, "OpenInterest")),
                source=source.source,
            )
        )
    return result


def parse_daily(
    payload: Payload, kind: InstrumentKind, product: str | None = None
) -> list[DerivativeDaily]:
    return parse_daily_rows(sequence(decode(payload.content)), payload, kind, product)


def parse_history(
    payload: Payload,
    contract: Contract,
    start: date,
    end: date,
    session: Session | None,
) -> list[DerivativeDaily]:
    if session not in {None, "regular", "after_hours"}:
        raise ValueError("Invalid session")
    try:
        text = payload.content.decode("cp950")
    except UnicodeError as exc:
        raise SchemaError("Invalid TAIFEX CSV encoding") from exc
    if text.lstrip().startswith("<"):
        raise SourceError("TAIFEX returned an HTML query error instead of CSV")
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None:
        raise SchemaError("TAIFEX returned an empty response")
    columns = [h.strip().lstrip("\ufeff") for h in header]
    fields = [CSV_FIELDS.get(c) for c in columns]
    required_fields = {
        "Date",
        "Contract",
        "ContractMonth(Week)",
        "Open",
        "High",
        "Low",
        "Last",
        "Volume",
        "SettlementPrice",
        "OpenInterest",
        "TradingSession",
    }
    if contract.kind == "option":
        required_fields |= {"StrikePrice", "CallPut"}
    if not required_fields <= set(fields):
        raise SchemaError("TAIFEX historical CSV headers changed")
    rows: list[object] = []
    for row in reader:
        if not row or not any(cell.strip() for cell in row):
            continue
        last_required = max(
            i for i, field in enumerate(fields) if field in required_fields
        )
        if len(row) <= last_required:
            raise SchemaError("TAIFEX CSV row is truncated")
        rows.append(
            {
                field: cell.strip()
                for field, cell in zip(fields, row, strict=False)
                if field is not None
            }
        )
    target = (contract.product, contract.expiry, contract.strike, contract.right)
    result = [
        r
        for r in parse_daily_rows(rows, payload, contract.kind)
        if (r.contract.product, r.contract.expiry, r.contract.strike, r.contract.right)
        == target
        and start <= r.date <= end
        and (session is None or r.session == session)
    ]
    return sorted(result, key=lambda r: (r.date, r.session))


def quote_request(contract: Contract | str) -> Request:
    code = contract if isinstance(contract, str) else contract.mis_symbol
    if not code:
        raise UnsupportedFeatureError(
            "Contract has no verified MIS mapping; pass its explicit MIS SymbolID"
        )
    if not code.endswith(("-F", "-M", "-O", "-N")):
        raise ValueError(
            "SymbolID must identify a derivative contract, not a reference index"
        )
    if not code.isascii() or not all(c.isalnum() or c in "-_" for c in code):
        raise ValueError("Invalid MIS SymbolID")
    return Request("taifex", MIS, json={"SymbolID": [code]}, cacheable=False)


def parse_quote(
    payload: Payload, contract: Contract | str, *, root: dict[str, object] | None = None
) -> Quote:
    code = contract if isinstance(contract, str) else contract.mis_symbol
    root = mapping(decode(payload.content)) if root is None else root
    if str(required(root, "RtCode")) != "0":
        raise SourceError(str(root.get("RtMsg", "MIS query failed")))
    rows = sequence(required(mapping(required(root, "RtData")), "QuoteList"))
    selected = [mapping(r) for r in rows if mapping(r).get("SymbolID") == code]
    if not selected:
        raise NoDataError(f"No quote for {code}")
    row = selected[0]

    def book(side: str) -> tuple[BookLevel, ...]:
        result: list[BookLevel] = []
        for i in range(1, 6):
            price = number(required(row, f"C{side}Price{i}"))
            if price is not None:
                result.append(
                    BookLevel(i, price, integer(required(row, f"C{side}Size{i}")))
                )
        return tuple(result)

    return Quote(
        symbol=str(code),
        last=number(required(row, "CLastPrice")),
        open=number(required(row, "COpenPrice")),
        high=number(required(row, "CHighPrice")),
        low=number(required(row, "CLowPrice")),
        volume=integer(required(row, "CTotalVolume")),
        volume_unit="contracts",
        bids=book("Bid"),
        asks=book("Ask"),
        quoted_at=quote_time(row.get("CDate"), row.get("CTime")),
        source_date=parse_date(row["CDate"]) if row.get("CDate") else None,
        source=payload.source,
        status=str(row["Status"]) if "Status" in row else None,
    )
