"""Async source namespaces and cancellable HTTP operations."""

from types import TracebackType
from typing import Self

import httpx

from .client import validate_options
from .providers._equities import AsyncStockMarket
from .providers.cbc.market import AsyncCBC
from .providers.esb.market import AsyncESB
from .providers.mops.market import AsyncMOPS
from .providers.ndc.market import AsyncNDC
from .providers.taifex.market import AsyncTaifex
from .providers.tdcc.market import AsyncTDCC
from .transport.http import AsyncHttp


class AsyncClient:
    """使用非同步查詢與 async context manager 管理資料連線及訂閱.

    English:

    Asynchronous market-data client; use with async with.

    Args:
        timeout: HTTP timeout in seconds; must be finite and positive.
        retries: Number of additional attempts for retryable queries.
        interval: Minimum interval between requests to each host, in seconds.
        cache_ttl: Cache lifetime in seconds; zero disables caching.
        cache_size: Maximum entries in each cache; each also has a 32 MiB limit.
        proxy: HTTP/HTTPS proxy URL for HTTP queries and TAIFEX streams.
        trust_env: Honor environment proxy and TLS settings when true.
        transport: Custom async HTTP transport; mutually exclusive with proxy.

    Await queries through twse, tpex, esb, taifex, mops, tdcc, ndc and cbc.
    Closing the client closes its HTTP pool and active TAIFEX subscriptions.
    """

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        retries: int = 2,
        interval: float = 0.5,
        cache_ttl: float = 0.0,
        cache_size: int = 128,
        proxy: str | None = None,
        trust_env: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """建立 client；參數為 keyword-only，建立時不連網.

        English:

        Initialize a client without making network requests.

        Args:
            timeout: HTTP timeout in seconds; must be finite and positive.
            retries: Number of additional attempts for retryable queries.
            interval: Minimum interval between requests to each host, in seconds.
            cache_ttl: Cache lifetime in seconds; zero disables caching.
            cache_size: Maximum entries in each cache; each also has a 32 MiB limit.
            proxy: HTTP/HTTPS proxy URL for HTTP queries and TAIFEX streams.
            trust_env: Honor environment proxy and TLS settings when true.
            transport: Custom async HTTP transport; mutually exclusive with proxy.
        """
        validate_options(timeout, retries, interval)
        self._http = AsyncHttp(
            timeout=timeout,
            retries=retries,
            interval=interval,
            cache_ttl=cache_ttl,
            cache_size=cache_size,
            proxy=proxy,
            trust_env=trust_env,
            transport=transport,
        )
        self.twse = AsyncStockMarket(self._http, "twse")
        self.tpex = AsyncStockMarket(self._http, "tpex")
        self.taifex = AsyncTaifex(self._http)
        self.mops = AsyncMOPS(self._http)
        self.tdcc = AsyncTDCC(self._http)
        self.cbc = AsyncCBC(self._http)
        self.ndc = AsyncNDC(self._http)
        self.esb = AsyncESB(self._http)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """關閉連線、清除快取；非同步 client 同時關閉串流訂閱.

        English:

        Close TAIFEX subscriptions, HTTP connections and caches.
        """
        try:
            await self.taifex.close_streams()
        finally:
            await self._http.close()
