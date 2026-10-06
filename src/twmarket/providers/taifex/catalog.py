"""Map exact delivery periods through the official MIS filters and detail labels."""

import re
from collections import OrderedDict
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Literal

from twmarket.errors import NoDataError, SchemaError
from twmarket.models.instruments import Contract, InstrumentKind, Session
from twmarket.parsing.dates import parse_date
from twmarket.parsing.json import decode, mapping, required, sequence
from twmarket.parsing.numbers import number
from twmarket.transport.http import AsyncHttp, Http, Payload, Request

from .metadata import product_request

BASE = "https://mis.taifex.com.tw/futures/api/"
# Report product codes map to MIS commodity IDs.
PRODUCT_IDS = {"TX": "TXF", "MTX": "MXF", "TE": "EXF", "TF": "FXF"}
Identity = tuple[
    str, str, InstrumentKind, Decimal | None, Literal["call", "put"] | None
]


def identity(contract: Contract) -> Identity:
    return (
        contract.product,
        contract.expiry,
        contract.kind,
        contract.strike,
        contract.right,
    )


def listing_request(contract: Contract, session: Session = "regular") -> Request:
    if session not in {"regular", "after_hours"}:
        raise ValueError("Invalid session")
    if contract.kind not in {"future", "option"}:
        raise ValueError("Invalid instrument kind")
    return Request(
        "taifex",
        BASE + "getQuoteList",
        json={
            "MarketType": "0" if session == "regular" else "1",
            "SymbolType": "F" if contract.kind == "future" else "O",
            "KindID": "",
            "CID": PRODUCT_IDS.get(contract.product, contract.product),
            "ExpireMonth": contract.expiry,
            "RowSize": "全部",
            "PageNo": "",
            "SortColumn": "",
            "AscDesc": "A",
        },
        cacheable=False,
    )


def rows(payload: Payload) -> list[dict[str, object]]:
    root = mapping(decode(payload.content))
    if str(required(root, "RtCode")) == "2":
        return []
    if str(required(root, "RtCode")) != "0":
        from twmarket.errors import SourceError

        raise SourceError(str(root.get("RtMsg", "MIS catalog query failed")))
    return [
        mapping(r)
        for r in sequence(required(mapping(required(root, "RtData")), "QuoteList"))
    ]


def candidates(
    payload: Payload, kind: InstrumentKind, session: Session = "regular"
) -> list[str]:
    suffix = (
        ("-F" if kind == "future" else "-O")
        if session == "regular"
        else ("-M" if kind == "future" else "-N")
    )
    return [
        str(required(r, "SymbolID"))
        for r in rows(payload)
        if str(required(r, "SymbolID")).endswith(suffix)
    ]


def detail_requests(codes: list[str]) -> list[Request]:
    return [
        Request(
            "taifex",
            BASE + "getQuoteDetail",
            json={"SymbolID": codes[i : i + 100]},
            cacheable=False,
        )
        for i in range(0, len(codes), 100)
    ]


def option_identity(row: dict[str, object], template: Contract) -> Identity:
    # Detail labels contain strike and option right.
    match = re.search(r";([\d,.]+)(買權|賣權)$", str(required(row, "DispCName")))
    if match is None:
        raise SchemaError("MIS option detail no longer contains strike and right")
    return (
        template.product,
        template.expiry,
        template.kind,
        number(match[1]),
        "call" if match[2] == "買權" else "put",
    )


def add_mapping(target: dict[Identity, str], key: Identity, code: str) -> None:
    if key in target and target[key] != code:
        raise SchemaError(
            "MIS returned ambiguous contract identities for an exact expiry"
        )
    target[key] = code


def months_request(contract: Contract, session: Session = "regular") -> Request:
    listing = listing_request(contract, session)
    return replace(listing, url=BASE + "getCmdyMonthDDLItemByKind")


def periods(payload: Payload) -> dict[str, str]:
    root = mapping(decode(payload.content))
    status = str(required(root, "RtCode"))
    if status == "2":
        return {}
    if status != "0":
        raise SchemaError("MIS delivery-period metadata query failed")
    result: dict[str, str] = {}
    for raw in sequence(required(mapping(required(root, "RtData")), "Items")):
        item = mapping(raw)
        expiry = str(required(item, "item"))
        if expiry != "現貨":
            result[expiry] = str(required(item, "dispName"))
    return result


def contracts_from_mapping(found: dict[Identity, str]) -> list[Contract]:
    return [
        Contract(key[0], key[1], key[2], key[3], key[4], code)
        for key, code in found.items()
    ]


def expiry_date(label: str) -> date:
    match = re.search(r"\((\d{4}/\d{2}/\d{2})\)", label)
    if match is None:
        raise SchemaError("MIS period has no exact expiration date")
    return parse_date(match[1])


class Catalog:
    def __init__(self, http: Http) -> None:
        self._http = http
        self._commodities: dict[InstrumentKind, set[str]] = {}
        self._periods: OrderedDict[
            tuple[str, str, InstrumentKind, Session], dict[Identity, str]
        ] = OrderedDict()

    def _request(
        self, contract: Contract, session: Session, *, month_list: bool = False
    ) -> Request:
        commodity = contract.product
        if len(commodity) == 2 and commodity not in PRODUCT_IDS:
            if contract.kind not in self._commodities:
                root = mapping(
                    decode((self._http.fetch(product_request(contract.kind))).content)
                )
                if str(required(root, "RtCode")) != "0":
                    raise SchemaError("MIS commodity identity query failed")
                self._commodities[contract.kind] = {
                    str(required(mapping(item), "CID"))
                    for item in sequence(
                        required(mapping(required(root, "RtData")), "Items")
                    )
                }
            candidate = commodity + ("F" if contract.kind == "future" else "O")
            if candidate not in self._commodities[contract.kind]:
                raise NoDataError(f"No verified MIS commodity for {contract.product}")
            commodity = candidate
        template = replace(contract, product=commodity)
        return (
            months_request(template, session)
            if month_list
            else listing_request(template, session)
        )

    def _load(
        self, contract: Contract, session: Session = "regular"
    ) -> dict[Identity, str]:
        key = contract.product, contract.expiry, contract.kind, session
        if key not in self._periods:
            codes = candidates(
                self._http.fetch(self._request(contract, session)),
                contract.kind,
                session,
            )
            found: dict[Identity, str] = {}
            if contract.kind == "future":
                if len(codes) > 1:
                    raise SchemaError(
                        "MIS returned multiple futures for one delivery period"
                    )
                if codes:
                    found[identity(contract)] = codes[0]
            else:
                for request in detail_requests(codes):
                    for row in rows(self._http.fetch(request)):
                        add_mapping(
                            found,
                            option_identity(row, contract),
                            str(required(row, "SymbolID")),
                        )
            self._periods[key] = found
            if len(self._periods) > 128:
                self._periods.popitem(last=False)
        self._periods.move_to_end(key)
        return self._periods[key]

    def resolve(self, contract: Contract, session: Session = "regular") -> Contract:
        listing_request(contract, session)  # Validate even when a mapping is supplied.
        if contract.mis_symbol and contract.mis_symbol.endswith(
            ("-F", "-O") if session == "regular" else ("-M", "-N")
        ):
            return contract
        if "/" in contract.expiry:
            raise NoDataError("Spread contracts require a source-provided MIS symbol")
        active = periods(
            self._http.fetch(self._request(contract, session, month_list=True))
        )
        if contract.expiry not in active:
            raise NoDataError(f"No active delivery period for {contract}")
        code = self._load(contract, session).get(identity(contract))
        if code is None:
            self._periods.pop(
                (contract.product, contract.expiry, contract.kind, session), None
            )
            code = self._load(contract, session).get(identity(contract))
        if code is None:
            raise NoDataError(f"No active MIS mapping for {contract}")
        return replace(
            contract, mis_symbol=code, expires_on=expiry_date(active[contract.expiry])
        )

    def contracts(
        self,
        product: str,
        kind: InstrumentKind,
        expiry: str | None,
        session: Session = "regular",
    ) -> list[Contract]:
        template = Contract(product, "", kind)
        active = periods(
            self._http.fetch(self._request(template, session, month_list=True))
        )
        if expiry is not None and expiry not in active:
            return []
        return [
            replace(c, expires_on=expiry_date(active[period]))
            for period in active
            if expiry is None or period == expiry
            for c in contracts_from_mapping(
                self._load(replace(template, expiry=period), session)
            )
        ]


class AsyncCatalog:
    def __init__(self, http: AsyncHttp) -> None:
        self._http = http
        self._commodities: dict[InstrumentKind, set[str]] = {}
        self._periods: OrderedDict[
            tuple[str, str, InstrumentKind, Session], dict[Identity, str]
        ] = OrderedDict()

    async def _request(
        self, contract: Contract, session: Session, *, month_list: bool = False
    ) -> Request:
        commodity = contract.product
        if len(commodity) == 2 and commodity not in PRODUCT_IDS:
            if contract.kind not in self._commodities:
                root = mapping(
                    decode(
                        (await self._http.fetch(product_request(contract.kind))).content
                    )
                )
                if str(required(root, "RtCode")) != "0":
                    raise SchemaError("MIS commodity identity query failed")
                self._commodities[contract.kind] = {
                    str(required(mapping(item), "CID"))
                    for item in sequence(
                        required(mapping(required(root, "RtData")), "Items")
                    )
                }
            candidate = commodity + ("F" if contract.kind == "future" else "O")
            if candidate not in self._commodities[contract.kind]:
                raise NoDataError(f"No verified MIS commodity for {contract.product}")
            commodity = candidate
        template = replace(contract, product=commodity)
        return (
            months_request(template, session)
            if month_list
            else listing_request(template, session)
        )

    async def _load(
        self, contract: Contract, session: Session = "regular"
    ) -> dict[Identity, str]:
        key = contract.product, contract.expiry, contract.kind, session
        if key not in self._periods:
            codes = candidates(
                await self._http.fetch(await self._request(contract, session)),
                contract.kind,
                session,
            )
            found: dict[Identity, str] = {}
            if contract.kind == "future":
                if len(codes) > 1:
                    raise SchemaError(
                        "MIS returned multiple futures for one delivery period"
                    )
                if codes:
                    found[identity(contract)] = codes[0]
            else:
                for request in detail_requests(codes):
                    for row in rows(await self._http.fetch(request)):
                        add_mapping(
                            found,
                            option_identity(row, contract),
                            str(required(row, "SymbolID")),
                        )
            self._periods[key] = found
            if len(self._periods) > 128:
                self._periods.popitem(last=False)
        self._periods.move_to_end(key)
        return self._periods[key]

    async def resolve(
        self, contract: Contract, session: Session = "regular"
    ) -> Contract:
        listing_request(contract, session)  # Validate even when a mapping is supplied.
        if contract.mis_symbol and contract.mis_symbol.endswith(
            ("-F", "-O") if session == "regular" else ("-M", "-N")
        ):
            return contract
        if "/" in contract.expiry:
            raise NoDataError("Spread contracts require a source-provided MIS symbol")
        active = periods(
            await self._http.fetch(
                await self._request(contract, session, month_list=True)
            )
        )
        if contract.expiry not in active:
            raise NoDataError(f"No active delivery period for {contract}")
        code = (await self._load(contract, session)).get(identity(contract))
        if code is None:
            self._periods.pop(
                (contract.product, contract.expiry, contract.kind, session), None
            )
            code = (await self._load(contract, session)).get(identity(contract))
        if code is None:
            raise NoDataError(f"No active MIS mapping for {contract}")
        return replace(
            contract, mis_symbol=code, expires_on=expiry_date(active[contract.expiry])
        )

    async def contracts(
        self,
        product: str,
        kind: InstrumentKind,
        expiry: str | None,
        session: Session = "regular",
    ) -> list[Contract]:
        template = Contract(product, "", kind)
        active = periods(
            await self._http.fetch(
                await self._request(template, session, month_list=True)
            )
        )
        if expiry is not None and expiry not in active:
            return []
        result: list[Contract] = []
        for period in active:
            if expiry is None or period == expiry:
                result.extend(
                    replace(contract, expires_on=expiry_date(active[period]))
                    for contract in contracts_from_mapping(
                        await self._load(replace(template, expiry=period), session)
                    )
                )
        return result
