"""Shared chunked official snapshot requests; failures retain each original input."""

from collections.abc import Callable

from twmarket.models.batch import BatchResult
from twmarket.models.quotes import Quote
from twmarket.parsing.json import decode, mapping, required, sequence
from twmarket.transport.http import AsyncHttp, Http, Payload, Request

from ._batch import async_map


def chunks(prepared: list[BatchResult[str]], size: int) -> list[list[str]]:
    codes = list(dict.fromkeys(row.data for row in prepared if row.data is not None))
    return [codes[i : i + size] for i in range(0, len(codes), size)]


def parse_chunk(
    payload: Payload,
    codes: list[str],
    parse: Callable[[Payload, str, dict[str, object]], Quote],
) -> dict[str, Quote | Exception]:
    root = mapping(decode(payload.content))
    derivative = payload.source.provider == "taifex"
    if derivative:
        data = (
            mapping(required(root, "RtData")) if str(root.get("RtCode")) == "0" else {}
        )
        raw_rows = sequence(data.get("QuoteList", []))
    else:
        raw_rows = sequence(root.get("msgArray", []))
    indexed: dict[str, list[object]] = {}
    for raw in raw_rows:
        row = mapping(raw)
        key = str(row.get("SymbolID") if derivative else row.get("c"))
        indexed.setdefault(key, []).append(row)
    result: dict[str, Quote | Exception] = {}
    for code in codes:
        try:
            selected = dict(root)
            if derivative and str(root.get("RtCode")) == "0":
                selected["RtData"] = {
                    **mapping(required(root, "RtData")),
                    "QuoteList": indexed.get(code, []),
                }
            elif not derivative:
                selected["msgArray"] = indexed.get(code, [])
            result[code] = parse(payload, code, selected)
        except Exception as exc:
            result[code] = exc
    return result


def restore(
    prepared: list[BatchResult[str]], values: dict[str, Quote | Exception]
) -> list[BatchResult[Quote]]:
    result: list[BatchResult[Quote]] = []
    for row in prepared:
        value = values[row.data] if row.data is not None else row.error
        result.append(
            BatchResult(
                row.instrument,
                value if isinstance(value, Quote) else None,
                value if isinstance(value, Exception) else None,
            )
        )
    return result


def snapshots(
    http: Http,
    prepared: list[BatchResult[str]],
    request: Callable[[list[str]], Request],
    parse: Callable[[Payload, str, dict[str, object]], Quote],
    *,
    size: int,
) -> list[BatchResult[Quote]]:
    values: dict[str, Quote | Exception] = {}
    for codes in chunks(prepared, size):
        try:
            values.update(parse_chunk(http.fetch(request(codes)), codes, parse))
        except Exception as exc:
            values.update(dict.fromkeys(codes, exc))
    return restore(prepared, values)


async def async_snapshots(
    http: AsyncHttp,
    prepared: list[BatchResult[str]],
    request: Callable[[list[str]], Request],
    parse: Callable[[Payload, str, dict[str, object]], Quote],
    *,
    size: int,
) -> list[BatchResult[Quote]]:
    async def fetch(codes: list[str]) -> dict[str, Quote | Exception]:
        try:
            return parse_chunk(await http.fetch(request(codes)), codes, parse)
        except Exception as exc:
            return dict.fromkeys(codes, exc)

    values: dict[str, Quote | Exception] = {}
    for group in await async_map(fetch, chunks(prepared, size)):
        values.update(group)
    return restore(prepared, values)
