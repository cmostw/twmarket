"""Official MIS product catalog and HTML product specifications."""

import re
from decimal import Decimal
from urllib.parse import urljoin

from twmarket.errors import NoDataError, SchemaError, SourceError
from twmarket.models.derivatives import (
    ContractSpecification,
    DerivativeProduct,
    TickSize,
)
from twmarket.models.instruments import InstrumentKind
from twmarket.parsing.json import decode, mapping, required, sequence
from twmarket.parsing.numbers import number
from twmarket.parsing.tables import cells, document
from twmarket.transport.http import Payload, Request

BASE = "https://www.taifex.com.tw"
PRODUCTS = BASE + "/cht/2/tX"
STOCKS = BASE + "/cht/2/stockLists"
ALIASES = {"TXF": "TX", "MXF": "MTX", "EXF": "TE", "FXF": "TF"}


def product_request(kind: InstrumentKind) -> Request:
    if kind not in {"future", "option"}:
        raise ValueError("Invalid instrument kind")
    return Request(
        "taifex",
        "https://mis.taifex.com.tw/futures/api/getCmdyDDLItemByKind",
        json={
            "MarketType": "0",
            "SymbolType": "F" if kind == "future" else "O",
            "KindID": "",
        },
    )


def product_links(payload: Payload) -> dict[str, tuple[str, str]]:
    root = document(payload.content)
    links: dict[str, tuple[str, str]] = {}
    for link in root.xpath('//a[starts-with(@href,"/cht/2/")][@title]'):
        title, href = link.get("title", ""), link.get("href", "")
        if (title.endswith("期貨") or title.endswith("選擇權")) and "類" not in title:
            links[href.rsplit("/", 1)[-1].upper()] = title, urljoin(BASE, href)
    if "TX" not in links or "TXO" not in links:
        raise SchemaError("TAIFEX official product navigation changed")
    return links


def stock_sizes(payload: Payload) -> dict[str, tuple[Decimal, str, str]]:
    root = document(payload.content)
    result: dict[str, tuple[Decimal, str, str]] = {}
    found = False
    for tr in root.xpath("//table//tr"):
        row = cells(tr)
        if row and row[0] == "股票期貨、選擇權商品代碼":
            if len(row) != 14 or row[11] != "標準型證券股數/受益權單位":
                raise SchemaError("Stock derivatives metadata headings changed")
            found = True
            continue
        if not found or len(row) != 14 or not row[0]:
            continue
        size = number(row[11])
        if size is None:
            raise SchemaError("Stock derivative has no contract unit")
        result[row[0]] = (
            size,
            "beneficial_units" if row[9] or row[10] else "shares",
            row[1],
        )
    if not found:
        raise SchemaError("No stock derivative metadata table")
    return result


def products(
    payload: Payload, navigation: Payload, stocks: Payload, kind: InstrumentKind
) -> list[DerivativeProduct]:
    root = mapping(decode(payload.content))
    if str(required(root, "RtCode")) != "0":
        raise SourceError(str(root.get("RtMsg", "Product catalog query failed")))
    links = product_links(navigation)
    sizes = stock_sizes(stocks)
    result: list[DerivativeProduct] = []
    for raw in sequence(required(mapping(required(root, "RtData")), "Items")):
        row = mapping(raw)
        cid = str(required(row, "CID"))
        product = ALIASES.get(cid, cid)
        underlying = str(row["SpotID"]) if row.get("SpotID") else None
        if underlying:
            suffix = "F" if kind == "future" else "O"
            size = sizes.get(cid[:-1]) if cid.endswith(suffix) else None
            result.append(
                DerivativeProduct(
                    product,
                    str(required(row, "DispCName")),
                    kind,
                    BASE + ("/cht/2/sTF" if kind == "future" else "/cht/2/sSO"),
                    payload.source,
                    underlying,
                    size[0] if size else None,
                    size[1] if size else None,
                    mis_commodity=cid,
                    multiplier_source=stocks.source if size else None,
                )
            )
        elif product in links:
            name, url = links[product]
            result.append(
                DerivativeProduct(
                    product, name, kind, url, payload.source, mis_commodity=cid
                )
            )
        else:
            raise SchemaError(f"MIS product {cid} has no official specification link")
    return result


def tick_bands(text: str) -> tuple[TickSize, ...]:
    pattern = (
        r"(?:報價|權利金|價格)?\s*(?:([\d,.]+)\s*(?:點|元)(?:以上|至))?"
        r"\s*(?:，?\s*未滿\s*([\d,.]+)\s*(?:點|元))?"
        r"者?\s*[:：]\s*([\d,.]+)\s*(?:點|元)"
    )
    result: list[TickSize] = []
    for match in re.finditer(pattern, text):
        tick = number(match[3])
        if tick is None:
            raise SchemaError("Missing tick size")
        result.append(
            TickSize(
                number(match[1]) if match[1] else None,
                number(match[2]) if match[2] else None,
                tick,
            )
        )
    if result:
        return tuple(result)
    combined = re.search(r"最小升降單位(?:為)?(?:新臺幣|新台幣)?\s*([\d,.]+)", text)
    if combined:
        tick = number(combined[1])
        if tick is not None:
            return (TickSize(None, None, tick),)
    match = re.search(r"(?:指數|每[\w]+)?\s*([\d,.]+)", text)
    if match:
        tick = number(match[1])
        if tick is not None:
            return (TickSize(None, None, tick),)
    raise SchemaError("Unrecognized official tick-size table")


def specification(
    payload: Payload, product: DerivativeProduct
) -> ContractSpecification:
    root = document(payload.content)
    values: dict[str, str] = {}
    for tr in root.xpath("//table//tr"):
        row = cells(tr)
        if len(row) == 2:
            values[row[0].replace(" ", "")] = row[1]
    if "交易標的" not in values or "英文代碼" not in values:
        raise SchemaError("No official derivative specification table")
    raw_multiplier = values.get(
        "契約乘數",
        values.get("契約價值", values.get("契約單位", values.get("契約規模", ""))),
    )
    tick_text = values.get(
        "最小升降單位",
        values.get("權利金報價單位", values.get("報價方式及最小升降單位", "")),
    )
    multiplier, unit = product.multiplier, product.multiplier_unit
    if product.underlying and "標的證券為股票者" in tick_text:
        parts = tick_text.split(
            "標的證券為指數股票型證券投資信託基金或境外指數股票型基金者："
        )
        if len(parts) != 2:
            raise SchemaError("Stock/ETF tick-size sections changed")
        tick_text = parts[1] if unit == "beneficial_units" else parts[0]
    currencies = {
        "新臺幣": "TWD",
        "新台幣": "TWD",
        "美元": "USD",
        "人民幣": "CNY",
        "日圓": "JPY",
    }
    currency = None
    quote_text = values.get(
        "交易報價", values.get("報價單位", values.get("報價方式", tick_text))
    )
    for label, code in currencies.items():
        if label in quote_text:
            currency = code
    if not product.underlying:
        match = re.search(
            r"(新臺幣|新台幣|美元|人民幣|日圓)\s*([\d,.]+)\s*元", raw_multiplier
        )
        if match:
            multiplier = number(match[2])
            unit = currencies[match[1]] + "_per_point"
            currency = currency or currencies[match[1]]
        else:
            match = re.search(
                r"([\d,.]+)\s*(金衡制盎司|台兩|桶|美元|歐元|英鎊|澳幣)", raw_multiplier
            )
            if match:
                multiplier = number(match[1])
                unit = {
                    "金衡制盎司": "troy_ounces",
                    "台兩": "taiwan_taels",
                    "桶": "barrels",
                    "美元": "USD",
                    "歐元": "EUR",
                    "英鎊": "GBP",
                    "澳幣": "AUD",
                }[match[2]]
    else:
        currency = "TWD"
    settlement = values.get("交割方式", "")
    return ContractSpecification(
        product.product,
        product.name,
        product.kind,
        product.underlying or values["交易標的"],
        multiplier,
        unit,
        currency,
        "cash"
        if "現金" in settlement
        else "physical"
        if "實物" in settlement
        else None,
        payload.source,
        tick_bands(tick_text),
        multiplier_source=product.multiplier_source
        or (payload.source if multiplier is not None else None),
    )


def select_product(items: list[DerivativeProduct], product: str) -> DerivativeProduct:
    canonical = ALIASES.get(product, product)
    found = [item for item in items if item.product == canonical]
    if not found and len(product) == 2:
        found = [
            item
            for item in items
            if item.product == product + ("F" if item.kind == "future" else "O")
        ]
    if len(found) != 1:
        raise NoDataError(f"No unique official specification for {product}")
    return found[0]
