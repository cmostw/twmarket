"""Behavior checks for batching, scheduling and optional parsed caches."""

import asyncio
from decimal import Decimal
from pathlib import Path

import httpx
import orjson
import pytest

from twmarket import AsyncClient, Client, Contract
from twmarket.providers._batch import async_batch

FIXTURES = Path(__file__).parent / "fixtures"


async def test_worker_reuses_slot_before_slow_input_finishes() -> None:
    ninth = asyncio.Event()
    release = asyncio.Event()
    active: set[str] = set()

    async def fetch(code: str) -> str:
        active.add(code)
        try:
            if code == "0":
                await release.wait()
            if code == "8":
                ninth.set()
            return code
        finally:
            active.remove(code)

    task = asyncio.create_task(async_batch(fetch, map(str, range(16))))
    try:
        await asyncio.wait_for(ninth.wait(), timeout=2)
        assert not task.done() and "0" in active
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not active
        release.set()
        rows = await async_batch(fetch, map(str, range(16)))
        assert [r.data for r in rows] == list(map(str, range(16)))
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_snapshot_chunks_duplicates_invalid_inputs_and_chunk_failure() -> None:
    calls: list[list[str]] = []
    template = orjson.loads((FIXTURES / "stock-mis.json").read_bytes())

    def respond(request: httpx.Request) -> httpx.Response:
        codes = [
            part.split("_")[1].split(".")[0]
            for part in request.url.params["ex_ch"].split("|")
        ]
        calls.append(codes)
        assert len(codes) <= 50
        if "1050" in codes:
            return httpx.Response(503)
        rows = [{**template["msgArray"][0], "c": code} for code in codes]
        return httpx.Response(200, json={**template, "msgArray": rows})

    codes = list(map(str, range(1000, 1051))) + ["1000", "invalid space"]
    with Client(
        transport=httpx.MockTransport(respond), interval=0, retries=0, cache_ttl=60
    ) as c:
        rows = c.twse.quote_many(codes)
        assert len(calls) == 2 and rows[0].ok and rows[-2].ok
        assert rows[-3].error is not None and isinstance(rows[-1].error, ValueError)
        assert [r.instrument for r in rows] == codes
        assert rows[-2].data == rows[0].data
        assert rows[0].data is not None
        assert len(rows[0].data.bids) == len(rows[0].data.asks) == 5
        assert rows[0].data.bids[0].price == Decimal("2580")
        c.twse.quote_many(["1000"])
        assert len(calls) == 3  # Snapshots bypass even an enabled cache.
        assert c.twse.quote("1000").last == rows[0].data.last
    calls.clear()
    async with AsyncClient(
        transport=httpx.MockTransport(respond), interval=0, retries=0
    ) as c:
        rows = await c.twse.quote_many(codes)
        assert len(calls) == 2 and rows[0].ok and rows[-3].error is not None


def test_parsed_cache_expiry_source_metadata_and_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from twmarket.errors import TransportError
    from twmarket.transport import cache
    from twmarket.transport.cache import MemoryCache

    clock = [0.0]
    monkeypatch.setattr(cache, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    fetched = [0]

    def respond(request: httpx.Request) -> httpx.Response:
        fetched[0] += 1
        return httpx.Response(
            200, content=(FIXTURES / "catalog-twse.fixture").read_bytes()
        )

    with Client(
        interval=0, cache_ttl=5, transport=httpx.MockTransport(respond)
    ) as client:
        first = client.twse.instruments(category="ETF")
        second = client.twse.instruments(category="ETF")
        assert fetched == [1] and first == second and first is not second
        second.clear()
        assert client.twse.instruments(category="ETF") == first
        assert (
            first[0].symbol.startswith("00")
            and first[0].source == client.twse.instruments(category="ETF")[0].source
        )
        clock[0] = 6
        third = client.twse.instruments(category="ETF")
        assert fetched == [2] and third[0].source is not first[0].source
    with pytest.raises(TransportError, match="closed"):
        client.twse.instruments(category="ETF")
    bounded = MemoryCache[str](ttl=5, size=2, max_bytes=3)
    bounded.put(b"a", "ab", 2)
    bounded.put(b"b", "c", 1)
    assert bounded.get(b"a") == "ab"
    bounded.put(b"c", "d", 1)
    assert bounded.get(b"b") is None
    clock[0] += 6
    assert bounded.get(b"a") is None and bounded.get(b"c") is None


async def test_taifex_snapshot_batch_sessions_and_duplicates() -> None:
    template = orjson.loads((FIXTURES / "taifex-detail.json").read_bytes())
    calls: list[list[str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        codes: list[str] = orjson.loads(request.content)["SymbolID"]
        calls.append(codes)
        rows = [
            {**template["RtData"]["QuoteList"][0], "SymbolID": code}
            for code in codes
            if code != "BAD-F"
        ]
        return httpx.Response(200, json={**template, "RtData": {"QuoteList": rows}})

    codes = ["TXFJ6-F", "MXFJ6-F", "BAD-F", "TXFJ6-F", "TXFJ6-M", "bad id"]
    with Client(transport=httpx.MockTransport(respond), interval=0) as c:
        rows = c.taifex.quote_many(codes, session="regular")
        assert len(calls) == 1 and len(calls[0]) == 3
        assert rows[0].ok and rows[1].ok and not rows[2].ok and rows[3].ok
        assert isinstance(rows[4].error, ValueError) and isinstance(
            rows[5].error, ValueError
        )
        assert rows[0].data is not None and rows[0].data.contract is None
        assert len(rows[0].data.bids) == 5 and rows[0].data.bids[0].price == Decimal(
            "50061"
        )
        assert rows[0].data.quoted_at is not None
        assert c.taifex.quote("TXFJ6-F").last == rows[0].data.last
        first = Contract("TX", "202610", mis_symbol="TXFJ6-F")
        alias = Contract("TXF", "202610", mis_symbol="TXFJ6-F")
        mixed = c.taifex.quote_many([first, "TXFJ6-F", alias])
        assert mixed[0].data is not None and mixed[0].data.contract == first
        assert mixed[1].data is not None and mixed[1].data.contract is None
        assert mixed[2].data is not None and mixed[2].data.contract == alias
    calls.clear()
    async with AsyncClient(transport=httpx.MockTransport(respond), interval=0) as c:
        rows = await c.taifex.quote_many(["TXFJ6-M", "TXFJ6-M"], session="after_hours")
        assert len(calls) == 1 and calls[0] == ["TXFJ6-M"]
        assert rows[0].data is not None and rows[0].data.session == "after_hours"


async def test_async_history_months_overlap_and_remain_ordered() -> None:
    active = [0]
    maximum = [0]
    source = orjson.loads((FIXTURES / "twse.json").read_bytes())

    async def respond(request: httpx.Request) -> httpx.Response:
        active[0] += 1
        maximum[0] = max(maximum[0], active[0])
        try:
            await asyncio.sleep(0.01)
            period = request.url.params["date"]
            year, month = int(period[:4]), int(period[4:6])
            rows = [
                [f"{year - 1911}/{month:02d}/{i + 1:02d}", *r[1:]]
                for i, r in enumerate(source["data"])
            ]
            return httpx.Response(200, json={**source, "data": rows})
        finally:
            active[0] -= 1

    from datetime import date

    async with AsyncClient(
        transport=httpx.MockTransport(respond), interval=0
    ) as client:
        rows = await client.twse.history(
            "2330", start=date(2026, 8, 1), end=date(2026, 9, 30)
        )
    assert maximum[0] == 2 and active[0] == 0
    assert rows and [r.date for r in rows] == sorted(r.date for r in rows)

    # One corrupt month must fail the range and cancel another pending month.
    pending = asyncio.Event()

    async def corrupt_month(request: httpx.Request) -> httpx.Response:
        if request.url.params["date"] == "20260801":
            await pending.wait()
            return httpx.Response(200, content=b"<html>maintenance</html>")
        active[0] += 1
        pending.set()
        try:
            await asyncio.Event().wait()
            raise AssertionError("Unreachable")
        finally:
            active[0] -= 1

    from twmarket.errors import SchemaError

    async with AsyncClient(
        transport=httpx.MockTransport(corrupt_month), interval=0
    ) as client:
        with pytest.raises(SchemaError):
            await client.twse.history(
                "2330", start=date(2026, 8, 1), end=date(2026, 9, 30)
            )
    assert active[0] == 0
