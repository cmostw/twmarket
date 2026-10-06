"""SockJS envelopes; importing this module does not load websockets."""

from twmarket.errors import SchemaError, TransportError
from twmarket.parsing.json import decode, mapping, sequence


def messages(frame: str | bytes) -> list[dict[str, object]]:
    text = frame.decode() if isinstance(frame, bytes) else frame
    if text in {"o", "h"}:
        return []
    if text.startswith("c"):
        raise TransportError(f"SockJS closed the session: {text[1:]}")
    if not text.startswith("a"):
        raise SchemaError("Unexpected SockJS envelope")
    result: list[dict[str, object]] = []
    for raw in sequence(decode(text[1:].encode())):
        if not isinstance(raw, str):
            raise SchemaError("SockJS messages must be JSON strings")
        result.append(mapping(decode(raw.encode(), exact_numbers=True)))
    return result
