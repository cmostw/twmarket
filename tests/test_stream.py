"""Exercise real local WebSocket framing, reconnect and client-owned cleanup."""

import asyncio
from pathlib import Path

import httpx
import orjson
import pytest

from twmarket import AsyncClient
from twmarket.errors import TransportError

pytest.importorskip("websockets")
from websockets.asyncio.client import connect as real_connect  # noqa: E402
from websockets.asyncio.server import ServerConnection, serve  # noqa: E402

FRAME = (Path(__file__).parent / "fixtures/stream-frame.txt").read_text()


@pytest.mark.parametrize("close_client", [False, True])
async def test_local_stream_reconnect_and_cleanup(
    monkeypatch: pytest.MonkeyPatch, close_client: bool
) -> None:
    connections = 0
    disconnected = asyncio.Event()

    async def source(socket: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        await socket.send("o")
        request = orjson.loads(await socket.recv())
        assert orjson.loads(request[0])["symbols"] == ["TXFJ6-F"]
        await socket.send("h")
        await socket.send(FRAME)
        if connections == 1:
            await socket.close(code=1012)
        else:
            await socket.send(
                "a"
                + orjson.dumps(
                    [orjson.dumps({"type": "changeSource"}).decode()]
                ).decode()
            )
            subscribed = orjson.loads(await socket.recv())
            refreshed = orjson.loads(await socket.recv())
            assert orjson.loads(subscribed[0])["symbols"] == ["TXFJ6-F"]
            assert orjson.loads(refreshed[0])["type"] == "refresh"
            await socket.send(FRAME)
            await socket.wait_closed()
            disconnected.set()

    async with serve(source, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        def connector(*args: object, **kwargs: object) -> real_connect:
            assert kwargs["proxy"] is (True if close_client else None)
            return real_connect(f"ws://127.0.0.1:{port}", proxy=None)

        monkeypatch.setattr("websockets.asyncio.client.connect", connector)
        transport = httpx.MockTransport(
            lambda r: httpx.Response(200, json={"websocket": True})
        )
        async with AsyncClient(
            transport=transport, interval=0, trust_env=close_client
        ) as client:
            quotes = client.taifex.stream(["TXFJ6-F"])
            first = await asyncio.wait_for(anext(quotes), 2)
            stale = await asyncio.wait_for(anext(quotes), 2)
            refreshed = await asyncio.wait_for(anext(quotes), 3)
            assert first.last == stale.last == refreshed.last
            assert not first.stale and stale.stale and not refreshed.stale
            assert connections == 2
            reset = await asyncio.wait_for(anext(quotes), 2)
            resynced = await asyncio.wait_for(anext(quotes), 2)
            assert reset.stale and not resynced.stale and reset.last == resynced.last
            if close_client:
                await client.close()
            else:
                await quotes.aclose()
            await asyncio.wait_for(disconnected.wait(), 2)
            await quotes.aclose()


async def test_local_stream_cancellation_and_reconnect_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = asyncio.Event()
    subscribed = asyncio.Event()

    async def source(socket: ServerConnection) -> None:
        await socket.send("o")
        await socket.recv()
        subscribed.set()
        await socket.wait_closed()
        closed.set()

    async with serve(source, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        def connector(*args: object, **kwargs: object) -> real_connect:
            return real_connect(f"ws://127.0.0.1:{port}", proxy=None)

        monkeypatch.setattr("websockets.asyncio.client.connect", connector)
        async with AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200)), interval=0
        ) as client:
            quotes = client.taifex.stream(["TXFJ6-F"])
            task = asyncio.create_task(anext(quotes))
            await asyncio.wait_for(subscribed.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(closed.wait(), 2)
            await quotes.aclose()

    def unavailable(*args: object, **kwargs: object) -> object:
        raise OSError("offline")

    monkeypatch.setattr("websockets.asyncio.client.connect", unavailable)
    async with AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200)), interval=0
    ) as client:
        quotes = client.taifex.stream(["TXFJ6-F"], reconnects=0)
        with pytest.raises(TransportError):
            await anext(quotes)
