"""Bounded HTTP retries and independent per-host request pacing."""

import asyncio
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TypeVar, cast
from urllib.parse import urlsplit

import httpx
import orjson

from twmarket.errors import TransportError
from twmarket.models.common import SourceInfo

from .cache import MemoryCache, memory_size

T = TypeVar("T")

RETRY_STATUSES = {429, 500, 502, 503, 504}


@dataclass(frozen=True, slots=True)
class Request:
    provider: str
    url: str
    params: dict[str, str] | None = None
    form: dict[str, str] | None = None
    json: dict[str, object] | None = None
    cacheable: bool = True


@dataclass(frozen=True, slots=True)
class Payload:
    content: bytes
    source: SourceInfo


def retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        value = response.headers.get("Retry-After")
        if value:
            try:
                delay = float(value)
            except ValueError:
                try:
                    delay = (
                        parsedate_to_datetime(value) - datetime.now(UTC)
                    ).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    delay = float("nan")
            if math.isfinite(delay):
                if delay > 30:
                    raise TransportError(
                        "Source requested a retry delay longer than 30 seconds"
                    )
                return max(0.0, delay)
    return min(0.25 * 2**attempt, 5.0)


class ParsedCache:
    _cache: MemoryCache[Payload]
    _parsed: MemoryCache[object]

    def parse_cached(
        self, payloads: tuple[Payload, ...], key: str, parse: Callable[[], T]
    ) -> T:
        if not self._parsed.ttl:
            return parse()
        token = orjson.dumps(
            [key, [(p.source.url, p.source.received_at.isoformat()) for p in payloads]]
        )
        cached = self._parsed.get(token)
        if cached is not None:
            return cast(T, cached)
        value = parse()
        self._parsed.put(token, value, memory_size(value))
        return value


def validate_proxy(proxy: object, trust_env: object, transport: object) -> None:
    if type(trust_env) is not bool:
        raise TypeError("trust_env must be a boolean")
    if proxy is not None:
        if not isinstance(proxy, str):
            raise TypeError("proxy must be a URL string")
        url = httpx.URL(proxy)
        if url.scheme not in {"http", "https"} or not url.host:
            raise ValueError("proxy must be an HTTP or HTTPS URL")
        if transport is not None:
            raise ValueError("proxy and transport cannot be combined")


class Http(ParsedCache):
    def __init__(
        self,
        *,
        timeout: float,
        retries: int,
        interval: float,
        cache_ttl: float = 0.0,
        cache_size: int = 128,
        proxy: str | None = None,
        trust_env: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        validate_proxy(proxy, trust_env, transport)
        self.proxy = proxy
        self.trust_env = trust_env
        self._cache = MemoryCache[Payload](ttl=cache_ttl, size=cache_size)
        self._parsed = MemoryCache[object](ttl=cache_ttl, size=cache_size)
        self.client = httpx.Client(
            timeout=timeout,
            proxy=proxy,
            trust_env=trust_env,
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": "twmarket/0.1"},
        )
        self.retries = retries
        self.interval = interval
        self._locks: dict[str, threading.Lock] = {}
        self._next: dict[str, float] = {}

    def fetch(self, request: Request) -> Payload:
        if self.client.is_closed:
            raise TransportError("Client is closed")
        key = (
            orjson.dumps(
                [
                    request.provider,
                    request.url,
                    request.params,
                    request.form,
                    request.json,
                ],
                option=orjson.OPT_SORT_KEYS,
            )
            if request.cacheable and self._cache.ttl
            else b""
        )
        if key and (cached := self._cache.get(key)) is not None:
            return cached
        host = urlsplit(request.url).netloc
        for attempt in range(self.retries + 1):
            with self._locks.setdefault(host, threading.Lock()):
                delay = self._next.get(host, 0.0) - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                self._next[host] = time.monotonic() + self.interval
            response = None
            try:
                response = self.client.request(
                    "POST"
                    if request.form is not None or request.json is not None
                    else "GET",
                    request.url,
                    params=request.params,
                    data=request.form,
                    json=request.json,
                )
                response.raise_for_status()
                payload = Payload(
                    response.content,
                    SourceInfo(request.provider, str(response.url), datetime.now(UTC)),
                )
                if key:
                    self._cache.put(key, payload, len(payload.content))
                return payload
            except httpx.HTTPError as exc:
                retryable = (
                    not isinstance(exc, httpx.HTTPStatusError)
                    or exc.response.status_code in RETRY_STATUSES
                )
                if not retryable or attempt == self.retries:
                    raise TransportError(f"Request failed: {request.url}") from exc
                time.sleep(retry_delay(response, attempt))
        raise AssertionError("Unreachable")

    def close(self) -> None:
        self._cache.clear()
        self._parsed.clear()
        self.client.close()


class AsyncHttp(ParsedCache):
    def __init__(
        self,
        *,
        timeout: float,
        retries: int,
        interval: float,
        cache_ttl: float = 0.0,
        cache_size: int = 128,
        proxy: str | None = None,
        trust_env: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        validate_proxy(proxy, trust_env, transport)
        self.proxy = proxy
        self.trust_env = trust_env
        self._cache = MemoryCache[Payload](ttl=cache_ttl, size=cache_size)
        self._parsed = MemoryCache[object](ttl=cache_ttl, size=cache_size)
        self.client = httpx.AsyncClient(
            timeout=timeout,
            proxy=proxy,
            trust_env=trust_env,
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": "twmarket/0.1"},
        )
        self.retries = retries
        self.interval = interval
        self._locks: dict[str, asyncio.Lock] = {}
        self._next: dict[str, float] = {}
        self._semaphore = asyncio.Semaphore(8)

    async def fetch(self, request: Request) -> Payload:
        if self.client.is_closed:
            raise TransportError("Client is closed")
        key = (
            orjson.dumps(
                [
                    request.provider,
                    request.url,
                    request.params,
                    request.form,
                    request.json,
                ],
                option=orjson.OPT_SORT_KEYS,
            )
            if request.cacheable and self._cache.ttl
            else b""
        )
        if key and (cached := self._cache.get(key)) is not None:
            return cached
        host = urlsplit(request.url).netloc
        for attempt in range(self.retries + 1):
            response = None
            try:
                async with self._semaphore:
                    async with self._locks.setdefault(host, asyncio.Lock()):
                        delay = self._next.get(host, 0.0) - time.monotonic()
                        if delay > 0:
                            await asyncio.sleep(delay)
                        self._next[host] = time.monotonic() + self.interval
                    response = await self.client.request(
                        "POST"
                        if request.form is not None or request.json is not None
                        else "GET",
                        request.url,
                        params=request.params,
                        data=request.form,
                        json=request.json,
                    )
                response.raise_for_status()
                payload = Payload(
                    response.content,
                    SourceInfo(request.provider, str(response.url), datetime.now(UTC)),
                )
                if key:
                    self._cache.put(key, payload, len(payload.content))
                return payload
            except httpx.HTTPError as exc:
                retryable = (
                    not isinstance(exc, httpx.HTTPStatusError)
                    or exc.response.status_code in RETRY_STATUSES
                )
                if not retryable or attempt == self.retries:
                    raise TransportError(f"Request failed: {request.url}") from exc
                await asyncio.sleep(retry_delay(response, attempt))
        raise AssertionError("Unreachable")

    async def close(self) -> None:
        self._cache.clear()
        self._parsed.clear()
        await self.client.aclose()
