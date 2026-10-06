"""MOPS query contracts and source-owned table schemas."""

import re
from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Literal

from twmarket.errors import NoDataError, SchemaError, SourceError
from twmarket.models.disclosures import (
    Dividend,
    FinancialStatement,
    FinancialValue,
    Revenue,
)
from twmarket.parsing.dates import parse_date
from twmarket.parsing.json import decode, mapping, required, sequence, symbol
from twmarket.parsing.numbers import integer, number
from twmarket.transport.http import Payload, Request

BASE = "https://mops.twse.com.tw/mops/api/"
STATEMENTS = {"income": "t164sb04", "balance": "t164sb03", "cashflow": "t164sb05"}


def year_value(year: int) -> str:
    if type(year) is not int or year < 1912:
        raise ValueError("year must be a Gregorian year, at least 1912")
    return str(year - 1911)


def statement_request(
    code: str, kind: str, year: int | None, quarter: int | None
) -> Request:
    if (year is None) != (quarter is None):
        raise ValueError("Specify both year and quarter, or neither")
    if quarter is not None and quarter not in {1, 2, 3, 4}:
        raise ValueError("quarter must be 1..4")
    return Request(
        "mops",
        BASE + STATEMENTS[kind],
        json={
            "companyId": symbol(code),
            "dataType": "1" if year is None else "2",
            "year": "" if year is None else year_value(year),
            "season": "" if quarter is None else str(quarter),
            "subsidiaryCompanyId": "",
        },
    )


def revenue_request(code: str, year: int | None, month: int | None) -> Request:
    if (year is None) != (month is None):
        raise ValueError("Specify both year and month, or neither")
    if month is not None and month not in range(1, 13):
        raise ValueError("month must be 1..12")
    return Request(
        "mops",
        BASE + "t05st10_ifrs",
        json={
            "companyId": symbol(code),
            "dataType": "1" if year is None else "2",
            "year": "" if year is None else year_value(year),
            "month": "" if month is None else str(month),
            "subsidiaryCompanyId": "",
        },
    )


def result(payload: Payload) -> dict[str, object] | None:
    root = mapping(decode(payload.content, exact_numbers=True))
    code = str(required(root, "code"))
    if code == "406":
        return None
    if code != "200":
        raise SourceError(str(root.get("message", f"MOPS code {code}")))
    return mapping(required(root, "result"))


def headings(titles: object, prefix: str = "") -> list[str]:
    names: list[str] = []
    for raw in sequence(titles):
        node = mapping(raw)
        label = " ".join(filter(None, [prefix, str(required(node, "main"))]))
        children = sequence(node.get("sub", []))
        names.extend(headings(children, label) if children else [label])
    return names


def financial_period(label: str) -> tuple[date | None, date]:
    annual = re.fullmatch(r"(\d+)年度?", label)
    if annual:
        year = int(annual[1]) + 1911
        return date(year, 1, 1), date(year, 12, 31)
    dates = re.findall(r"(\d+)年(\d+)月(\d+)日", label)
    if dates:
        parsed = [parse_date(f"{y}/{m}/{d}") for y, m, d in dates]
        if len(parsed) == 1:
            return None, parsed[0]
        if len(parsed) == 2 and parsed[0] <= parsed[1]:
            return parsed[0], parsed[1]
    quarter = re.fullmatch(r"(\d+)年第([1-4])季", label)
    if quarter:
        year, month = int(quarter[1]) + 1911, int(quarter[2]) * 3
        return date(year, month - 2, 1), date(year, month, monthrange(year, month)[1])
    raise SchemaError(f"Unknown MOPS financial period: {label!r}")


def financial_number(value: object) -> Decimal | None:
    if isinstance(value, bool) or isinstance(value, float):
        raise SchemaError(f"Expected an exact financial number, got {value!r}")
    text = str(value).strip() if value is not None else ""
    if text in {"不適用", "尚未決議", "無", "無。"}:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    return number(text)


def source_rows(data: dict[str, object], key: str) -> list[list[object]]:
    width = len(headings(required(data, "titles")))
    rows = [sequence(value) for value in sequence(required(data, key))]
    if any(len(row) != width for row in rows):
        raise SchemaError("MOPS table width differs from its source headings")
    return rows


def parse_statement(
    payload: Payload, code: str, kind: str, year: int | None, quarter: int | None
) -> FinancialStatement:
    data = result(payload)
    if data is None:
        raise NoDataError(f"No {kind} statement for {code}")
    actual_year = int(str(required(data, "year"))) + 1911
    actual_quarter = int(str(required(data, "season")))
    if actual_quarter not in {1, 2, 3, 4}:
        raise SchemaError("Invalid MOPS reporting quarter")
    if (year is not None and year != actual_year) or (
        quarter is not None and quarter != actual_quarter
    ):
        raise SchemaError("MOPS returned a different reporting period")
    titles = sequence(required(data, "titles"))
    if not titles or str(required(mapping(titles[0]), "main")) != "會計項目":
        raise SchemaError("Unknown MOPS financial account heading")
    columns: list[tuple[str, date | None, date, Literal["amount", "percentage"]]] = []
    for raw in titles[1:]:
        node = mapping(raw)
        label = str(required(node, "main"))
        start, end = financial_period(label)
        children = sequence(node.get("sub", []))
        for child in children or [{"main": "金額"}]:
            measure = str(required(mapping(child), "main"))
            if measure not in {"金額", "%"}:
                raise SchemaError(f"Unknown MOPS financial measure: {measure}")
            columns.append(
                (label, start, end, "percentage" if measure == "%" else "amount")
            )
    report_type = str(data["reportType"]) if data.get("reportType") else None
    records: list[FinancialValue] = []
    for row in source_rows(data, "reportList"):
        if len(row) != len(columns) + 1:
            raise SchemaError("MOPS financial column descriptors differ from row width")
        raw_account = str(row[0])
        values = [financial_number(cell) for cell in row[1:]]
        for (label, start, end, measure), value in zip(columns, values, strict=True):
            records.append(
                FinancialValue(
                    code,
                    kind,
                    actual_year,
                    actual_quarter,
                    report_type,
                    raw_account.strip(),
                    len(raw_account) - len(raw_account.lstrip()),
                    all(v is None for v in values),
                    start,
                    end,
                    label,
                    measure,
                    value,
                    "%" if measure == "percentage" else None,
                    payload.source,
                )
            )
    return FinancialStatement(
        code,
        kind,
        actual_year,
        actual_quarter,
        report_type,
        tuple(records),
        payload.source,
    )


def parse_revenue(
    payload: Payload, code: str, year: int | None, month: int | None
) -> Revenue:
    data = result(payload)
    if data is None:
        raise NoDataError(f"No revenue for {code}")
    period = str(required(data, "yymm"))
    try:
        actual_year, actual_month = int(period[:-2]) + 1911, int(period[-2:])
        date(actual_year, actual_month, 1)
    except ValueError as exc:
        raise SchemaError("Invalid MOPS revenue period") from exc
    if (year is not None and year != actual_year) or (
        month is not None and month != actual_month
    ):
        raise SchemaError("MOPS returned a different revenue month")
    if headings(required(data, "titles")) != ["項目", "營業收入淨額"]:
        raise SchemaError("Unknown MOPS revenue headings")
    numeric_rows: list[list[object]] = []
    for row in source_rows(data, "data"):
        if row[0] == "備註/營收變化原因說明":
            continue
        numeric_rows.append(row)
    labels = [
        "本月",
        "去年同期",
        "增減金額",
        "增減百分比",
        "本年累計",
        "去年累計",
        "增減金額",
        "增減百分比",
    ]
    if [row[0] for row in numeric_rows] != labels:
        raise SchemaError("Unknown MOPS revenue item layout")
    values = [financial_number(row[1]) for row in numeric_rows]
    # Official sentinel means undefined/overflow, not a 999999.99% growth rate.
    for i in (3, 7):
        if values[i] == Decimal("999999.99"):
            values[i] = None
    return Revenue(
        code,
        actual_year,
        actual_month,
        values[0],
        values[1],
        values[2],
        values[3],
        values[4],
        values[5],
        values[6],
        values[7],
        "thousand_TWD",
        payload.source,
    )


def dividends_request(code: str, start_year: int, end_year: int) -> Request:
    if start_year > end_year:
        raise ValueError("start_year must not be after end_year")
    return Request(
        "mops",
        BASE + "t05st09_2",
        json={
            "companyId": symbol(code),
            "dataType": "2",
            "firstYear": year_value(start_year),
            "lastYear": year_value(end_year),
            "queryType": "1",
        },
    )


def optional_date(value: object) -> date | None:
    if value is None or str(value).strip() in {
        "",
        "-",
        "--",
        "不適用",
        "尚未決議",
        "尚未公告",
    }:
        return None
    return parse_date(value)


def dividend_period(value: object) -> tuple[int, int | None]:
    match = re.fullmatch(r"(\d+)年(?:年度|度|第([1-4])季)?", str(value).strip())
    if match is None:
        raise SchemaError(f"Invalid dividend reporting period: {value!r}")
    return int(match[1]) + 1911, int(match[2]) if match[2] else None


DIVIDEND_HEADINGS = [
    "決議（擬議）進度",
    "股利所屬年（季）度",
    "股利所屬期間",
    "期別",
    "董事會決議（擬議）股利分派日",
    "股東會日期",
    "期初未分配盈餘/待彌補虧損（元）",
    "本期淨利（淨損）（元）",
    "可分配盈餘（元）",
    "分配後期未分配盈餘（元）",
    "股東配發內容 盈餘分配之現金股利（元/股）",
    "股東配發內容 法定盈餘公積發放之現金（元/股）",
    "股東配發內容 資本公積發放之現金（元/股）",
    "股東配發內容 股東配發之現金（股利）總金額（元）",
    "股東配發內容 盈餘轉增資配股（元/股）",
    "股東配發內容 法定盈餘公積轉增資配股（元/股）",
    "股東配發內容 資本公積轉增資配股（元/股）",
    "股東配發內容 股東配股總股數（股）",
    "股利分派之公司章程",
    "備註",
    "普通股每股面額",
]


def parse_dividends(payload: Payload, code: str) -> list[Dividend]:
    data = result(payload)
    if data is None:
        return []
    records: list[Dividend] = []
    for key in ("commonStock", "specialStock"):
        stock = mapping(data.get(key, {}))
        if not stock.get("data"):
            continue
        preferred = key == "specialStock"
        expected = (["特別股代號/名稱"] if preferred else []) + DIVIDEND_HEADINGS
        if headings(required(stock, "titles")) != expected:
            raise SchemaError("Unknown MOPS dividend headings")
        for raw in source_rows(stock, "data"):
            row = raw[1:] if preferred else raw
            year, quarter = dividend_period(row[1])
            interval = str(row[2]).split("~")
            if len(interval) == 2:
                start, end = parse_date(interval[0]), parse_date(interval[1])
                if start > end:
                    raise SchemaError("Reversed dividend period")
            elif row[2] in {"", "-", "不適用", None}:
                start, end = None, None
            else:
                raise SchemaError("Invalid dividend date range")
            par = re.fullmatch(
                r"(新台幣|美元|人民幣|港幣)([\d,.]+)元", str(row[20]).strip()
            )
            if par:
                par_value = financial_number(par[2])
                currency = {
                    "新台幣": "TWD",
                    "美元": "USD",
                    "人民幣": "CNY",
                    "港幣": "HKD",
                }[par[1]]
            elif str(row[20]).strip() in {"", "-", "不適用", "無票面金額"}:
                par_value, currency = None, None
            else:
                raise SchemaError(f"Unknown dividend par value: {row[20]!r}")
            records.append(
                Dividend(
                    code,
                    "preferred" if preferred else "common",
                    str(raw[0]) if preferred else None,
                    str(row[0]),
                    year,
                    quarter,
                    start,
                    end,
                    integer(row[3]),
                    optional_date(row[4]),
                    optional_date(row[5]),
                    financial_number(row[6]),
                    financial_number(row[7]),
                    financial_number(row[8]),
                    financial_number(row[9]),
                    financial_number(row[10]),
                    financial_number(row[11]),
                    financial_number(row[12]),
                    financial_number(row[13]),
                    financial_number(row[14]),
                    financial_number(row[15]),
                    financial_number(row[16]),
                    integer(row[17]),
                    par_value,
                    currency,
                    payload.source,
                )
            )
    return records
