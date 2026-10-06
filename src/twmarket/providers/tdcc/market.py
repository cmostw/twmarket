"""Official weekly TDCC distribution CSV, with source-defined bracket levels."""

import csv
import io

from twmarket.errors import SchemaError
from twmarket.models.holdings import ShareholdingBracket
from twmarket.parsing.dates import parse_date
from twmarket.parsing.json import symbol
from twmarket.parsing.numbers import integer, number
from twmarket.transport.http import AsyncHttp, Http, Payload, Request

URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
HEADER = ["資料日期", "證券代號", "持股分級", "人數", "股數", "占集保庫存數比例%"]


def parse(payload: Payload, code: str) -> list[ShareholdingBracket]:
    reader = csv.reader(io.StringIO(payload.content.decode("utf-8-sig")))
    if next(reader, None) != HEADER:
        raise SchemaError("TDCC CSV headers changed")
    rows: list[ShareholdingBracket] = []
    for row in reader:
        if len(row) != 6:
            raise SchemaError("TDCC CSV row width changed")
        if row[1].strip() == code:
            level = integer(row[2])
            if level is None or level not in range(1, 18):
                raise SchemaError("Unknown TDCC bracket")
            rows.append(
                ShareholdingBracket(
                    code,
                    parse_date(row[0]),
                    level,
                    integer(row[3]),
                    integer(row[4]),
                    number(row[5]),
                    payload.source,
                )
            )
    return rows


class TDCC:
    """依證券代號查詢最新公布的持股級距.

    English:

    Latest published TDCC shareholding brackets by security code.
    """

    def __init__(self, http: Http) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http

    def distribution(self, code: str) -> list[ShareholdingBracket]:
        """取得最新持股級距，包含調整與總計；查無證券時回傳空清單.

        English:

        Return the latest published holding brackets for a security code string.

        Percentages retain percent units; adjustment and total levels are included.
        No matching security returns an empty list.
        """
        code = symbol(code)
        return parse(self._http.fetch(Request("tdcc", URL)), code)


class AsyncTDCC:
    """以 await 查詢最新公布的持股級距.

    English:

    Awaitable queries for the latest TDCC shareholding brackets.
    """

    def __init__(self, http: AsyncHttp) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http

    async def distribution(self, code: str) -> list[ShareholdingBracket]:
        """取得最新持股級距，包含調整與總計；查無證券時回傳空清單.

        English:

        Return the latest published holding brackets for a security code string.

        Percentages retain percent units; adjustment and total levels are included.
        No matching security returns an empty list.
        """
        code = symbol(code)
        return parse(await self._http.fetch(Request("tdcc", URL)), code)
