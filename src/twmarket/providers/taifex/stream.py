"""Rebuild snapshots from subscribed SockJS updates, with bounded reconnects."""

import asyncio
import secrets
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import orjson

from twmarket.errors import SchemaError, TransportError, UnsupportedFeatureError
from twmarket.models.common import SourceInfo
from twmarket.models.instruments import Contract, Session
from twmarket.models.quotes import Quote
from twmarket.parsing.json import mapping, required
from twmarket.transport.http import AsyncHttp, Payload, Request
from twmarket.transport.sockjs import messages

from .data import parse_quote
from .qnames import QNAMES

if TYPE_CHECKING:
    from .market import AsyncTaifex

BASE = "https://mis.taifex.com.tw/futures/rt"
STATUSES = ["", "PT", "NCP", "TH", "TC", "PO", "PC", "CO", "QR"]


class QuoteState:
    """Absent keys retain values; an explicit null clears a field."""

    def __init__(self, codes: dict[str, Contract | None]) -> None:
        self.codes = codes
        self.rows: dict[str, dict[str, object]] = {}
        self.last: dict[str, Quote] = {}

    def reset(self) -> None:
        self.rows.clear()
        self.last.clear()

    def apply(self, message: dict[str, object]) -> Quote | None:
        if message.get("type") in {"changeDate", "changeSource"}:
            self.reset()
            return None
        if message.get("type") != "quote":
            return None
        data = mapping(required(message, "quote"))
        code = str(required(data, "symbol"))
        if code not in self.codes:
            return None
        values = mapping(required(data, "values"))
        full = str(message.get("mode")) == "1"
        if code not in self.rows and not full:
            return None  # Partial updates require a full snapshot.
        row: dict[str, object] = {"SymbolID": code} if full else dict(self.rows[code])
        for key, value in values.items():
            name = QNAMES.get(key)
            if name is not None:
                if key == "145" and value is not None:
                    try:
                        index = int(str(value))
                        if not 0 <= index < len(STATUSES):
                            raise ValueError("Invalid status index")
                        value = STATUSES[index]
                    except (ValueError, IndexError) as exc:
                        raise SchemaError("Unknown MIS status code") from exc
                row[name] = value
        self.rows[code] = row
        required_keys = {
            "CLastPrice",
            "COpenPrice",
            "CHighPrice",
            "CLowPrice",
            "CTotalVolume",
        }
        if not required_keys <= row.keys():
            raise SchemaError("Full MIS snapshot lacks required fields")
        # Unquoted book levels may be absent in a full snapshot.
        for side in ["Bid", "Ask"]:
            for i in range(1, 6):
                row.setdefault(f"C{side}Price{i}", None)
                row.setdefault(f"C{side}Size{i}", None)
        payload = Payload(
            orjson.dumps({"RtCode": "0", "RtData": {"QuoteList": [row]}}, default=str),
            SourceInfo("taifex", BASE, datetime.now(UTC)),
        )
        quote = replace(
            parse_quote(payload, code),
            contract=self.codes[code],
            session="after_hours" if code.endswith(("-M", "-N")) else "regular",
        )
        self.last[code] = quote
        return quote


async def stream(
    market: "AsyncTaifex",
    http: AsyncHttp,
    contracts: list[Contract | str],
    *,
    reconnects: int = 3,
    session: Session = "regular",
) -> AsyncGenerator[Quote, None]:
    try:
        from websockets.asyncio.client import connect
        from websockets.exceptions import WebSocketException
        from websockets.typing import Origin
    except ImportError as exc:
        raise UnsupportedFeatureError(
            "Install twmarket[stream] to subscribe to MIS"
        ) from exc
    if type(reconnects) is not int or reconnects < 0:
        raise ValueError("reconnects must be a nonnegative integer")
    if not contracts:
        raise ValueError("At least one contract is required")
    codes: dict[str, Contract | None] = {}
    for item in contracts:
        resolved = (
            await market.resolve(item, session=session)
            if isinstance(item, Contract)
            else item
        )
        code = resolved.mis_symbol if isinstance(resolved, Contract) else resolved
        from .data import quote_request

        quote_request(resolved)  # Validate the resolved symbol.
        if code:
            codes[code] = resolved if isinstance(resolved, Contract) else None
    state = QuoteState(codes)
    failures = 0
    while not market.closed:
        state.reset()
        try:
            await http.fetch(Request("taifex", BASE + "/info", cacheable=False))
            cookie = "; ".join(f"{k}={v}" for k, v in http.client.cookies.items())
            url = f"wss://mis.taifex.com.tw/futures/rt/000/{secrets.token_hex(12)}/websocket"
            async with connect(
                url,
                proxy=http.proxy if http.proxy is not None else http.trust_env or None,
                origin=Origin("https://mis.taifex.com.tw"),
                additional_headers={"Cookie": cookie},
                open_timeout=15,
                close_timeout=5,
                max_queue=16,
                max_size=4 * 1024 * 1024,
            ) as socket:
                market.register_stream(socket.close)
                try:
                    opened = await asyncio.wait_for(socket.recv(), 30)
                    if opened != "o":
                        raise SchemaError("SockJS session did not send an open frame")
                    subscription = orjson.dumps(
                        {"type": "subscribe", "symbols": list(codes)}
                    ).decode()
                    await socket.send(orjson.dumps([subscription]).decode())
                    while not market.closed:
                        frame = await asyncio.wait_for(socket.recv(), 40)
                        for message in messages(frame):
                            if message.get("type") in {"changeDate", "changeSource"}:
                                for old in tuple(state.last.values()):
                                    yield replace(old, stale=True)
                                state.reset()
                                # Refresh the subscription after a source/date reset.
                                await socket.send(orjson.dumps([subscription]).decode())
                                await socket.send(
                                    orjson.dumps(
                                        [orjson.dumps({"type": "refresh"}).decode()]
                                    ).decode()
                                )
                                continue
                            quote = state.apply(message)
                            if quote is not None:
                                yield quote
                finally:
                    market.unregister_stream(socket.close)
        except (WebSocketException, OSError, TimeoutError, TransportError) as exc:
            if market.closed:
                return
            for old in tuple(state.last.values()):
                yield replace(old, stale=True)
            state.reset()
            if failures >= reconnects:
                raise TransportError(
                    "MIS stream exhausted its reconnect attempts"
                ) from exc
            failures += 1
            await asyncio.sleep(min(0.5 * 2 ** (failures - 1), 8))
