"""Exact parsing; float input is rejected rather than silently rounded."""

from decimal import Decimal, InvalidOperation

from twmarket.errors import SchemaError

MISSING = {"", "-", "--", "---", "NULL", "N/A", "NA"}


def number(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise SchemaError(f"Expected an exact number, got {value!r}")
    text = str(value).strip().replace(",", "")
    if text.upper() in MISSING:
        return None
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise SchemaError(f"Invalid number: {value!r}") from exc
    if not result.is_finite():
        raise SchemaError(f"Non-finite number: {value!r}")
    return result


def integer(value: object) -> int | None:
    result = number(value)
    if result is None:
        return None
    if result != result.to_integral_value():
        raise SchemaError(f"Expected an integer, got {value!r}")
    return int(result)
