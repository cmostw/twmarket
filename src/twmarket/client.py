"""Client ownership and public source namespaces."""

import math
from types import TracebackType
from typing import Self

import httpx

from .providers._equities import StockMarket
from .providers.cbc.market import CBC
from .providers.esb.market import ESB
from .providers.mops.market import MOPS
from .providers.ndc.market import NDC
from .providers.taifex.market import Taifex
from .providers.tdcc.market import TDCC
from .transport.http import Http


def validate_options(timeout: float, retries: int, interval: float) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if type(retries) is not int or retries < 0:
        raise ValueError("retries must be a nonnegative integer")
    if not math.isfinite(interval) or interval < 0:
        raise ValueError("interval must be finite and nonnegative")


class Client:
    """使用同步查詢與 context manager 管理市場資料連線.

    English:

    Synchronous market-data client; use as a context manager.

    Args:
        timeout: HTTP timeout in seconds; must be finite and positive.
        retries: Number of additional attempts for retryable queries.
        interval: Minimum interval between requests to each host, in seconds.
        cache_ttl: Cache lifetime in seconds; zero disables caching.
        cache_size: Maximum entries in each cache; each also has a 32 MiB limit.
        proxy: HTTP/HTTPS proxy URL, optionally with credentials.
        trust_env: Honor environment proxy and TLS settings when true.
        transport: Custom HTTP transport; mutually exclusive with proxy.

    Source namespaces are twse, tpex, esb, taifex, mops, tdcc, ndc and cbc.
    Prices use Decimal and missing values use None. Construction makes no requests.
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
        transport: httpx.BaseTransport | None = None,
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
            proxy: HTTP/HTTPS proxy URL, optionally with credentials.
            trust_env: Honor environment proxy and TLS settings when true.
            transport: Custom HTTP transport; mutually exclusive with proxy.
        """
        validate_options(timeout, retries, interval)
        self._http = Http(
            timeout=timeout,
            retries=retries,
            interval=interval,
            cache_ttl=cache_ttl,
            cache_size=cache_size,
            proxy=proxy,
            trust_env=trust_env,
            transport=transport,
        )
        self.twse = StockMarket(self._http, "twse")
        self.tpex = StockMarket(self._http, "tpex")
        self.taifex = Taifex(self._http)
        self.mops = MOPS(self._http)
        self.tdcc = TDCC(self._http)
        self.cbc = CBC(self._http)
        self.ndc = NDC(self._http)
        self.esb = ESB(self._http)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """關閉連線、清除快取；非同步 client 同時關閉串流訂閱.

        English:

        Release the HTTP connection pool and clear this client's caches.
        """
        self._http.close()
