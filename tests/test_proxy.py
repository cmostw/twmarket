"""Proxy routing, authentication and HTTP/WebSocket policy."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from twmarket import AsyncClient, Client

# pyright: reportPrivateUsage=false
from twmarket.errors import TransportError
from twmarket.transport.http import Payload, Request


async def test_proxy_routes_sync_async_and_stream_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, str | None]] = []

    class Proxy(BaseHTTPRequestHandler):
        protocol_version: str = "HTTP/1.1"

        def do_GET(self) -> None:
            requests.append((self.path, self.headers.get("Proxy-Authorization")))
            body = b'{"websocket":true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proxy = f"http://user:password@127.0.0.1:{server.server_port}"
    target = Request("test", "http://source.invalid/data")
    try:
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        monkeypatch.setenv("NO_PROXY", "*")
        with Client(proxy=proxy, trust_env=False, interval=0) as client:
            assert client._http.fetch(target).content == b'{"websocket":true}'
        async with AsyncClient(proxy=proxy, trust_env=False, interval=0) as client:
            assert (await client._http.fetch(target)).content == b'{"websocket":true}'
            original_fetch = client._http.fetch

            async def fetch_info(request: Request) -> Payload:
                return await original_fetch(target)

            def connect(*args: object, **kwargs: object) -> object:
                assert kwargs["proxy"] == proxy
                raise OSError("proxy unavailable")

            monkeypatch.setattr(client._http, "fetch", fetch_info)
            monkeypatch.setattr("websockets.asyncio.client.connect", connect)
            stream = client.taifex.stream(["TXFJ6-F"], reconnects=0)
            with pytest.raises(TransportError):
                await anext(stream)
        assert len(requests) == 3
        assert all(path == target.url for path, _ in requests)
        assert all(auth == "Basic dXNlcjpwYXNzd29yZA==" for _, auth in requests)
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join()
    for constructor in [Client, AsyncClient]:
        for proxy_url in ["localhost:8080", "socks5://localhost:8080", "http://"]:
            with pytest.raises(ValueError):
                constructor(proxy=proxy_url)
        with pytest.raises(ValueError, match="cannot be combined"):
            constructor(
                proxy=proxy,
                transport=httpx.MockTransport(lambda r: httpx.Response(200)),
            )
