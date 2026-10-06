"""Validate JSON shapes at the provider boundary."""

import json
from decimal import Decimal
from typing import cast

import orjson

from twmarket.errors import SchemaError


def decode(body: bytes, *, exact_numbers: bool = False) -> object:
    try:
        if exact_numbers:
            return cast(object, json.loads(body, parse_float=Decimal))
        return cast(object, orjson.loads(body))
    except (ValueError, UnicodeError) as exc:
        raise SchemaError("Source response is not valid JSON") from exc


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SchemaError("Expected a JSON object")
    result = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in result):
        raise SchemaError("Expected string object keys")
    return cast(dict[str, object], result)


def sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        raise SchemaError("Expected a JSON array")
    return cast(list[object], value)


def required(row: dict[str, object], key: str) -> object:
    if key not in row:
        raise SchemaError(f"Missing source field: {key}")
    return row[key]


def symbol(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Instrument codes must be strings")
    value = value.strip()
    if not value or not value.isascii() or not value.isalnum():
        raise ValueError("Invalid instrument code")
    return value
