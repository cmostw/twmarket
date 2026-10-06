"""Sync and async TAIFEX access share all request builders and parsers."""

from collections.abc import Iterable
from dataclasses import replace
from datetime import date

from twmarket.models.batch import BatchResult
from twmarket.models.daily import DerivativeDaily
from twmarket.models.derivatives import (
    ContractSpecification,
    DerivativeProduct,
    MarginCategory,
    MarginRequirement,
)
from twmarket.models.instruments import Contract, InstrumentKind, Session
from twmarket.models.quotes import Quote
from twmarket.parsing.json import symbol
from twmarket.providers._batch import async_batch, async_map, batch
from twmarket.providers._snapshots import async_snapshots, snapshots
from twmarket.transport.http import AsyncHttp, Http, Payload, Request

from . import margin, metadata
from .catalog import AsyncCatalog, Catalog
from .data import (
    daily_request,
    history_requests,
    parse_daily,
    parse_history,
    parse_quote,
    quote_request,
)


class Taifex:
    """查詢期交所契約、規格、保證金及行情.

    English:

    TAIFEX contracts, specifications, margins and market data.

    Products use official report codes; quotes also accept exact MIS SymbolIDs.
    """

    def __init__(self, http: Http) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http
        self._catalog = Catalog(http)

    def daily(
        self, *, kind: InstrumentKind = "future", product: str | None = None
    ) -> list[DerivativeDaily]:
        """取得來源目前公布的日行情；kind 選期貨／選擇權，product 可篩選商品.

        English:

        Return the source's current daily futures or options report.

        kind is future or option; product optionally filters an official report code.
        Rows retain trading date, session and separate last/settlement prices.
        """
        if product is not None:
            product = symbol(product)
        return parse_daily(self._http.fetch(daily_request(kind)), kind, product)

    def contracts(
        self,
        *,
        product: str,
        kind: InstrumentKind = "future",
        expiry: str | None = None,
        session: Session = "regular",
    ) -> list[Contract]:
        """依 product、kind、session 取得有效契約；expiry 可篩選完整到期期間.

        English:

        Return official active contracts for product, kind and session.

        expiry optionally selects an exact delivery period, including weekly series.
        Contracts retain MIS SymbolID and the published expiration date.
        """
        return self._catalog.contracts(symbol(product), kind, expiry, session)

    def history(
        self,
        contract: Contract,
        *,
        start: date,
        end: date,
        session: Session | None = None,
    ) -> list[DerivativeDaily]:
        """回傳含起訖兩日的歷史資料；無符合資料時回傳空清單.

        English:

        Return daily rows for an exact contract in the inclusive date range.

        session optionally selects regular or after_hours; None includes both.
        Night-session dates are the source volume-attribution dates.
        """
        requests = history_requests(contract, start, end, session)
        return [
            row
            for request in requests
            for row in parse_history(
                self._http.fetch(request), contract, start, end, session
            )
        ]

    def quote(
        self, contract: Contract | str, *, session: Session | None = None
    ) -> Quote:
        """取得最新報價；價格缺值為 None，查無快照時拋出 NoDataError.

        English:

        Return a MIS snapshot for an exact Contract or MIS SymbolID string.

        Contract objects are resolved against active metadata. session optionally
        validates the ID's session; absent snapshots raise NoDataError.
        """
        resolved = (
            self.resolve(contract, session=session or "regular")
            if isinstance(contract, Contract)
            else contract
        )
        quote = parse_quote(self._http.fetch(quote_request(resolved)), resolved)
        code = resolved.mis_symbol if isinstance(resolved, Contract) else resolved
        actual_session: Session = (
            "after_hours" if code and code.endswith(("-M", "-N")) else "regular"
        )
        if session is not None and session != actual_session:
            raise ValueError("SymbolID does not match requested session")
        return replace(
            quote,
            contract=resolved if isinstance(resolved, Contract) else None,
            session=actual_session,
        )

    def resolve(self, contract: Contract, *, session: Session = "regular") -> Contract:
        """依官方有效期間核對 MIS ID 及到期日；過期契約拋出 NoDataError.

        English:

        Return contract with its verified active MIS ID and expiration date.

        session is regular or after_hours. An unavailable delivery period raises
        NoDataError; ambiguous source mappings raise SchemaError.
        """
        return self._catalog.resolve(contract, session)

    def products(self, *, kind: InstrumentKind = "future") -> list[DerivativeProduct]:
        """取得最新期貨或選擇權商品目錄、規格入口與乘數來源.

        English:

        Return the current futures or options product catalog.

        Entries retain specification URLs and source-provided multipliers.
        """
        catalog = self._http.fetch(metadata.product_request(kind))
        navigation = self._http.fetch(Request("taifex", metadata.PRODUCTS))
        stocks = self._http.fetch(Request("taifex", metadata.STOCKS))
        return list(
            self._http.parse_cached(
                (catalog, navigation, stocks),
                "products:" + kind,
                lambda: tuple(metadata.products(catalog, navigation, stocks, kind)),
            )
        )

    def specification(
        self, product: str, *, kind: InstrumentKind = "future"
    ) -> ContractSpecification:
        """取得商品乘數、幣別、交割方式與 tick 級距；缺值為 None.

        English:

        Return multiplier, currency, settlement and tick bands for product.

        kind is future or option. Missing source metadata remains None.
        """
        selected = metadata.select_product(self.products(kind=kind), symbol(product))
        payload = self._http.fetch(Request("taifex", selected.specification_url))
        return self._http.parse_cached(
            (payload,),
            "specification:" + repr(selected),
            lambda: metadata.specification(payload, selected),
        )

    def margins(
        self, *, category: MarginCategory = "index", product: str | None = None
    ) -> list[MarginRequirement]:
        """依 category 與選用 product 查最新保證金，保留金額或百分數單位.

        English:

        Return the latest published margin records for category and optional product.

        Categories are index, stock, etf, fx, commodity and interest_rate.
        Stock rates retain percentages; other records retain their published units.
        """
        rows = margin.margins(
            self._http.fetch(margin.margin_request(category)), category
        )
        if product is None:
            return rows
        exact = [r for r in rows if product in {r.product, r.name, r.underlying}]
        if not exact and len(product) == 2 and category in {"stock", "etf"}:
            exact = [r for r in rows if r.product == product + "F"]
        if exact:
            return exact
        if (
            product.isascii()
            and product.isalnum()
            and category in {"index", "commodity", "fx"}
        ):
            name = metadata.select_product(
                self.products(kind="option" if product.endswith("O") else "future"),
                product,
            ).name
            return [
                r
                for r in rows
                if r.product == name or r.product.startswith(name + "風險保證金")
            ]
        return []

    def quote_many(
        self, contracts: Iterable[Contract | str], *, session: Session | None = None
    ) -> list[BatchResult[Quote]]:
        """逐筆回傳 BatchResult，保留輸入順序、重複輸入及個別錯誤.

        English:

        Return one quote BatchResult per contract or MIS SymbolID input.

        Input order, duplicates and individual errors are retained. session validates
        regular/after_hours identity; Contract inputs retain their resolved metadata.
        """
        resolved: dict[str, Contract | str] = {}
        identities: dict[Contract, Contract] = {}

        def prepare(contract: Contract | str) -> str:
            value = (
                self.resolve(contract, session=session or "regular")
                if isinstance(contract, Contract)
                else contract
            )
            quote_request(value)
            code = value if isinstance(value, str) else value.mis_symbol
            assert code is not None
            actual = "after_hours" if code.endswith(("-M", "-N")) else "regular"
            if session is not None and session != actual:
                raise ValueError("SymbolID does not match requested session")
            resolved[code] = value
            if isinstance(contract, Contract) and isinstance(value, Contract):
                identities[contract] = value
            return code

        def parse(payload: Payload, code: str, root: dict[str, object]) -> Quote:
            value = resolved[code]
            return replace(
                parse_quote(payload, value, root=root),
                contract=value if isinstance(value, Contract) else None,
                session="after_hours" if code.endswith(("-M", "-N")) else "regular",
            )

        results = snapshots(
            self._http,
            batch(prepare, contracts),
            lambda codes: Request(
                "taifex",
                quote_request(codes[0]).url,
                json={"SymbolID": codes},
                cacheable=False,
            ),
            parse,
            size=100,
        )
        return [
            replace(
                row,
                data=replace(
                    row.data,
                    contract=identities[row.instrument]
                    if isinstance(row.instrument, Contract)
                    else None,
                ),
            )
            if row.data is not None
            else row
            for row in results
        ]


class AsyncTaifex:
    """以 await 查詢期交所資料，.

    English:

    Awaitable TAIFEX queries.

    Products use official report codes; quotes also accept exact MIS SymbolIDs.
    """

    def __init__(self, http: AsyncHttp) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http
        self._catalog = AsyncCatalog(http)

    async def daily(
        self, *, kind: InstrumentKind = "future", product: str | None = None
    ) -> list[DerivativeDaily]:
        """取得來源目前公布的日行情；kind 選期貨／選擇權，product 可篩選商品.

        English:

        Return the source's current daily futures or options report.

        kind is future or option; product optionally filters an official report code.
        Rows retain trading date, session and separate last/settlement prices.
        """
        if product is not None:
            product = symbol(product)
        return parse_daily(await self._http.fetch(daily_request(kind)), kind, product)

    async def contracts(
        self,
        *,
        product: str,
        kind: InstrumentKind = "future",
        expiry: str | None = None,
        session: Session = "regular",
    ) -> list[Contract]:
        """依 product、kind、session 取得有效契約；expiry 可篩選完整到期期間.

        English:

        Return official active contracts for product, kind and session.

        expiry optionally selects an exact delivery period, including weekly series.
        Contracts retain MIS SymbolID and the published expiration date.
        """
        return await self._catalog.contracts(symbol(product), kind, expiry, session)

    async def history(
        self,
        contract: Contract,
        *,
        start: date,
        end: date,
        session: Session | None = None,
    ) -> list[DerivativeDaily]:
        """回傳含起訖兩日的歷史資料；無符合資料時回傳空清單.

        English:

        Return daily rows for an exact contract in the inclusive date range.

        session optionally selects regular or after_hours; None includes both.
        Night-session dates are the source volume-attribution dates.
        """
        requests = history_requests(contract, start, end, session)

        async def fetch(request: Request) -> list[DerivativeDaily]:
            return parse_history(
                await self._http.fetch(request), contract, start, end, session
            )

        return [row for group in await async_map(fetch, requests) for row in group]

    async def quote(
        self, contract: Contract | str, *, session: Session | None = None
    ) -> Quote:
        """取得最新報價；價格缺值為 None，查無快照時拋出 NoDataError.

        English:

        Return a MIS snapshot for an exact Contract or MIS SymbolID string.

        Contract objects are resolved against active metadata. session optionally
        validates the ID's session; absent snapshots raise NoDataError.
        """
        resolved = (
            await self.resolve(contract, session=session or "regular")
            if isinstance(contract, Contract)
            else contract
        )
        quote = parse_quote(await self._http.fetch(quote_request(resolved)), resolved)
        code = resolved.mis_symbol if isinstance(resolved, Contract) else resolved
        actual_session: Session = (
            "after_hours" if code and code.endswith(("-M", "-N")) else "regular"
        )
        if session is not None and session != actual_session:
            raise ValueError("SymbolID does not match requested session")
        return replace(
            quote,
            contract=resolved if isinstance(resolved, Contract) else None,
            session=actual_session,
        )

    async def resolve(
        self, contract: Contract, *, session: Session = "regular"
    ) -> Contract:
        """依官方有效期間核對 MIS ID 及到期日；過期契約拋出 NoDataError.

        English:

        Return contract with its verified active MIS ID and expiration date.

        session is regular or after_hours. An unavailable delivery period raises
        NoDataError; ambiguous source mappings raise SchemaError.
        """
        return await self._catalog.resolve(contract, session)

    async def products(
        self, *, kind: InstrumentKind = "future"
    ) -> list[DerivativeProduct]:
        """取得最新期貨或選擇權商品目錄、規格入口與乘數來源.

        English:

        Return the current futures or options product catalog.

        Entries retain specification URLs and source-provided multipliers.
        """
        catalog = await self._http.fetch(metadata.product_request(kind))
        navigation = await self._http.fetch(Request("taifex", metadata.PRODUCTS))
        stocks = await self._http.fetch(Request("taifex", metadata.STOCKS))
        return list(
            self._http.parse_cached(
                (catalog, navigation, stocks),
                "products:" + kind,
                lambda: tuple(metadata.products(catalog, navigation, stocks, kind)),
            )
        )

    async def specification(
        self, product: str, *, kind: InstrumentKind = "future"
    ) -> ContractSpecification:
        """取得商品乘數、幣別、交割方式與 tick 級距；缺值為 None.

        English:

        Return multiplier, currency, settlement and tick bands for product.

        kind is future or option. Missing source metadata remains None.
        """
        selected = metadata.select_product(
            await self.products(kind=kind), symbol(product)
        )
        payload = await self._http.fetch(Request("taifex", selected.specification_url))
        return self._http.parse_cached(
            (payload,),
            "specification:" + repr(selected),
            lambda: metadata.specification(payload, selected),
        )

    async def margins(
        self, *, category: MarginCategory = "index", product: str | None = None
    ) -> list[MarginRequirement]:
        """依 category 與選用 product 查最新保證金，保留金額或百分數單位.

        English:

        Return the latest published margin records for category and optional product.

        Categories are index, stock, etf, fx, commodity and interest_rate.
        Stock rates retain percentages; other records retain their published units.
        """
        rows = margin.margins(
            await self._http.fetch(margin.margin_request(category)), category
        )
        if product is None:
            return rows
        exact = [r for r in rows if product in {r.product, r.name, r.underlying}]
        if not exact and len(product) == 2 and category in {"stock", "etf"}:
            exact = [r for r in rows if r.product == product + "F"]
        if exact:
            return exact
        if (
            product.isascii()
            and product.isalnum()
            and category in {"index", "commodity", "fx"}
        ):
            name = metadata.select_product(
                await self.products(
                    kind="option" if product.endswith("O") else "future"
                ),
                product,
            ).name
            return [
                r
                for r in rows
                if r.product == name or r.product.startswith(name + "風險保證金")
            ]
        return []

    async def quote_many(
        self, contracts: Iterable[Contract | str], *, session: Session | None = None
    ) -> list[BatchResult[Quote]]:
        """逐筆回傳 BatchResult，保留輸入順序、重複輸入及個別錯誤.

        English:

        Return one quote BatchResult per contract or MIS SymbolID input.

        Input order, duplicates and individual errors are retained. session validates
        regular/after_hours identity; Contract inputs retain their resolved metadata.
        """
        resolved: dict[str, Contract | str] = {}
        identities: dict[Contract, Contract] = {}

        async def prepare(contract: Contract | str) -> str:
            value = (
                await self.resolve(contract, session=session or "regular")
                if isinstance(contract, Contract)
                else contract
            )
            quote_request(value)
            code = value if isinstance(value, str) else value.mis_symbol
            assert code is not None
            actual = "after_hours" if code.endswith(("-M", "-N")) else "regular"
            if session is not None and session != actual:
                raise ValueError("SymbolID does not match requested session")
            resolved[code] = value
            if isinstance(contract, Contract) and isinstance(value, Contract):
                identities[contract] = value
            return code

        def parse(payload: Payload, code: str, root: dict[str, object]) -> Quote:
            value = resolved[code]
            return replace(
                parse_quote(payload, value, root=root),
                contract=value if isinstance(value, Contract) else None,
                session="after_hours" if code.endswith(("-M", "-N")) else "regular",
            )

        results = await async_snapshots(
            self._http,
            await async_batch(prepare, contracts),
            lambda codes: Request(
                "taifex",
                quote_request(codes[0]).url,
                json={"SymbolID": codes},
                cacheable=False,
            ),
            parse,
            size=100,
        )
        return [
            replace(
                row,
                data=replace(
                    row.data,
                    contract=identities[row.instrument]
                    if isinstance(row.instrument, Contract)
                    else None,
                ),
            )
            if row.data is not None
            else row
            for row in results
        ]
