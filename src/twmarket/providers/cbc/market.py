"""Official CBC exchange rates preserve the published pair direction."""

import re
from datetime import date

from twmarket.errors import SchemaError
from twmarket.models.macro import ExchangeRate
from twmarket.parsing.dates import months, parse_date
from twmarket.parsing.json import decode, mapping, required, sequence
from twmarket.parsing.numbers import number
from twmarket.transport.http import AsyncHttp, Http, Payload, Request

REQUEST = Request(
    "cbc", "https://cpx.cbc.gov.tw/API/DataAPI/Get", {"FileName": "BP01D01"}
)


def validate(currency: str | None, start: date, end: date) -> None:
    list(months(start, end))
    if currency is not None and not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("currency must be a three-letter code, e.g. NTD, USD, JPY")


def parse(
    payload: Payload, currency: str | None, start: date, end: date
) -> list[ExchangeRate]:
    root = mapping(decode(payload.content, exact_numbers=True))
    data = mapping(required(root, "data"))
    columns = sequence(required(mapping(required(data, "structure")), "Table1"))
    pairs: list[tuple[str, str]] = []
    for value in columns:
        match = re.search(
            r"([A-Z]{3})/([A-Z]{3})", str(required(mapping(value), "data"))
        )
        if match is None:
            raise SchemaError("CBC currency-pair header changed")
        pairs.append((match[1], match[2]))
    meta = mapping(root.get("meta", {}))
    published = parse_date(meta["last_updated"]) if meta.get("last_updated") else None
    result: list[ExchangeRate] = []
    for value in sequence(required(data, "dataSets")):
        row = sequence(value)
        if len(row) != len(pairs) + 1:
            raise SchemaError("CBC row width changed")
        day = parse_date(row[0])
        if start <= day <= end:
            for pair, cell in zip(pairs, row[1:], strict=True):
                if currency is None or currency in pair:
                    result.append(
                        ExchangeRate(
                            day,
                            pair[0],
                            pair[1],
                            number(cell),
                            published,
                            payload.source,
                        )
                    )
    return result


class CBC:
    """查詢央行匯率並保留來源幣別配對方向.

    English:

    CBC exchange rates with the published currency-pair direction.
    """

    def __init__(self, http: Http) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http

    def exchange_rates(
        self, *, start: date, end: date, currency: str | None = None
    ) -> list[ExchangeRate]:
        """查詢含起訖兩日的匯率；currency 可篩選任一側幣別，維持來源方向.

        English:

        Return exchange-rate rows within inclusive start/end dates.

        currency optionally matches either side of a published pair, using a
        three-letter source code such as NTD, USD or JPY. Pair direction is preserved.
        """
        validate(currency, start, end)
        return parse(self._http.fetch(REQUEST), currency, start, end)


class AsyncCBC:
    """以 await 查詢央行匯率並保留來源幣別配對方向.

    English:

    Awaitable CBC exchange rates with the published currency-pair direction.
    """

    def __init__(self, http: AsyncHttp) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http

    async def exchange_rates(
        self, *, start: date, end: date, currency: str | None = None
    ) -> list[ExchangeRate]:
        """查詢含起訖兩日的匯率；currency 可篩選任一側幣別，維持來源方向.

        English:

        Return exchange-rate rows within inclusive start/end dates.

        currency optionally matches either side of a published pair, using a
        three-letter source code such as NTD, USD or JPY. Pair direction is preserved.
        """
        validate(currency, start, end)
        return parse(await self._http.fetch(REQUEST), currency, start, end)
