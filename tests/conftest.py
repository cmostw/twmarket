"""Default suite may use local WebSockets, but must never contact official hosts."""

import socket

import pytest


@pytest.fixture(autouse=True)
def offline_network(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    if "integration" in request.keywords:
        return
    original = socket.socket.connect

    def local_only(sock: socket.socket, address: tuple[str, int] | str) -> None:
        if isinstance(address, tuple) and address[0] not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            raise AssertionError(
                f"Offline test attempted external connection: {address}"
            )
        original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)
