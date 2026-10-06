"""Latest published margin amounts and stock percentage rates, kept distinct."""

import re

from twmarket.errors import SchemaError
from twmarket.models.derivatives import MarginCategory, MarginRequirement
from twmarket.parsing.dates import parse_date
from twmarket.parsing.json import decode, mapping, required, sequence
from twmarket.parsing.numbers import integer, number
from twmarket.transport.http import Payload, Request

PATHS = {
    "index": "IndexFuturesAndOptionsMargining",
    "stock": "SingleStockFuturesMargining",
    "etf": "SingleStockFuturesETFMargining",
    "fx": "FXFuturesAndOptionsMargining",
    "commodity": "GoldFuturesAndOptionsMargining",
    "interest_rate": "InterestRateFuturesMargining",
}


def margin_request(category: MarginCategory) -> Request:
    if category not in PATHS:
        raise ValueError("Invalid margin category")
    return Request("taifex", "https://openapi.taifex.com.tw/v1/" + PATHS[category])


def margins(payload: Payload, category: MarginCategory) -> list[MarginRequirement]:
    result: list[MarginRequirement] = []
    rates = category == "stock"
    for raw in sequence(decode(payload.content)):
        row = mapping(raw)
        name = str(required(row, "Contracts" if category == "fx" else "Contract"))
        fields = [
            required(row, key + ("Rate" if rates else ""))
            for key in ["ClearingMargin", "MaintenanceMargin", "InitialMargin"]
        ]
        if rates and any(not str(v).endswith("%") for v in fields):
            raise SchemaError("Stock margins no longer have explicit percentage units")
        component = re.search(r"\(([ABC])\)值$", name)
        level = (
            re.fullmatch(r"級距(\d+)", str(row["GroupLevel"]))
            if "GroupLevel" in row
            else None
        )
        result.append(
            MarginRequirement(
                name,
                str(row.get("ContractName", name)),
                category,
                parse_date(required(row, "Date")),
                number(str(fields[0]).removesuffix("%")),
                number(str(fields[1]).removesuffix("%")),
                number(str(fields[2]).removesuffix("%")),
                "percent" if rates else "source_currency_units",
                payload.source,
                str(row["UnderlyingSecurityCode"])
                if row.get("UnderlyingSecurityCode")
                else None,
                integer(level[1]) if level else None,
                component[1] if component else None,
            )
        )
    return result
