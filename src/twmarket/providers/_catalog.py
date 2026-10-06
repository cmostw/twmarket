"""Security identifiers from the exchange ISIN catalog."""

import re

from twmarket.errors import SchemaError
from twmarket.models.market import Instrument, Market
from twmarket.parsing.dates import parse_date
from twmarket.parsing.tables import document
from twmarket.transport.http import Payload, Request

URL = "https://isin.twse.com.tw/isin/C_public.jsp"
MODES = {"twse": "2", "tpex": "4", "esb": "5"}


def catalog_request(market: Market) -> Request:
    return Request(market, URL, {"strMode": MODES[market]})


def parse_catalog(
    payload: Payload, market: Market, category: str | None
) -> list[Instrument]:
    root = document(payload.content, encoding="cp950")
    stamp = re.search(r"最近更新日期:\s*(\d{4}/\d{2}/\d{2})", root.text_content())
    as_of = parse_date(stamp[1]) if stamp else None
    result: list[Instrument] = []
    group = "股票" if market == "esb" else ""
    header_found = False
    for row in root.xpath("//tr"):
        values = ["".join(c.itertext()).strip() for c in row.xpath("./td|./th")]
        if values and "有價證券代號及名稱" in values[0]:
            if values[:6] != [
                "有價證券代號及名稱",
                "國際證券辨識號碼(ISIN Code)",
                "上市日",
                "市場別",
                "產業別",
                "CFICode",
            ]:
                raise SchemaError("ISIN catalog headings changed")
            header_found = True
            continue
        if not header_found or not values:
            continue
        if len(values) == 1:
            group = values[0].strip()
            continue
        if len(values) != 7:
            raise SchemaError("ISIN catalog row width changed")
        identity = re.fullmatch(r"([A-Za-z0-9]+)[\s\u3000]+(.+)", values[0])
        if identity is None or not group:
            raise SchemaError("Invalid ISIN security identifier/category")
        if category is not None and group != category:
            continue
        result.append(
            Instrument(
                identity[1],
                identity[2].strip(),
                market,
                group,
                values[1] or None,
                parse_date(values[2]) if values[2] else None,
                values[4] or None,
                values[5] or None,
                payload.source,
                as_of,
            )
        )
    if not header_found:
        raise SchemaError("ISIN catalog did not return a security table")
    return result
