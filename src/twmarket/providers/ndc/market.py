"""NDC monthly economic observations."""

import csv
import io
import zipfile
from datetime import date

from twmarket.errors import SchemaError
from twmarket.models.macro import EconomicObservation
from twmarket.parsing.dates import months
from twmarket.parsing.numbers import MISSING, number
from twmarket.transport.http import AsyncHttp, Http, Payload, Request

from .urls import NDC_BUSINESS_CYCLE_ZIP_URL, NDC_PMI_CSV_URL

TABLES = {
    "signal": "景氣指標與燈號.csv",
    "signal_components": "景氣對策信號構成項目.csv",
    "leading": "領先指標構成項目.csv",
    "coincident": "同時指標構成項目.csv",
    "lagging": "落後指標構成項目.csv",
}


def request(start: date, end: date, table: str | None = None) -> Request:
    list(months(start, end))
    if table is not None and table not in TABLES:
        raise ValueError(f"table must be one of {', '.join(TABLES)}")
    return Request(
        "ndc", NDC_PMI_CSV_URL if table is None else NDC_BUSINESS_CYCLE_ZIP_URL
    )


def parse(
    payload: Payload, start: date, end: date, table: str | None = None
) -> list[EconomicObservation]:
    body = payload.content
    if table is not None:
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                entry = next(
                    (
                        n
                        for n in archive.namelist()
                        if n.rsplit("/", 1)[-1] == TABLES[table]
                    ),
                    None,
                )
                if entry is None:
                    raise SchemaError("NDC ZIP no longer contains the requested table")
                body = archive.read(entry)
        except zipfile.BadZipFile as exc:
            raise SchemaError("NDC response is not a ZIP archive") from exc
    reader = csv.reader(io.StringIO(body.decode("utf-8-sig")))
    columns = next(reader, None)
    if not columns or columns[0] != "Date":
        raise SchemaError("NDC CSV headers changed")
    if table is None and columns != ["Date", "PMI", "NMI"]:
        raise SchemaError("NDC PMI/NMI headers changed")
    result: list[EconomicObservation] = []
    for row in reader:
        if not row:
            continue
        if len(row) != len(columns):
            raise SchemaError("NDC CSV row width changed")
        try:
            day = date(int(row[0][:4]), int(row[0][4:]), 1)
        except ValueError as exc:
            raise SchemaError("Invalid NDC observation month") from exc
        if start.replace(day=1) <= day <= end:
            for series, cell in zip(columns[1:], row[1:], strict=True):
                text = cell.strip()
                if text.upper() in MISSING:
                    value, label = None, None
                elif text in {
                    "紅",
                    "黃紅",
                    "綠",
                    "黃藍",
                    "藍",
                    "紅燈",
                    "黃紅燈",
                    "綠燈",
                    "黃藍燈",
                    "藍燈",
                }:
                    value, label = None, text
                else:
                    value, label = number(text), None
                result.append(
                    EconomicObservation(day, series, value, label, payload.source)
                )
    return result


class NDC:
    """查詢按月公布的 PMI、NMI 與景氣觀測值.

    English:

    Monthly NDC observations, including PMI, NMI and cycle indicators.
    """

    def __init__(self, http: Http) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http

    def pmi(self, *, start: date, end: date) -> list[EconomicObservation]:
        """取得期間內的 PMI 與 NMI；包含 start 所在月份，以 series 篩選系列.

        English:

        Return monthly PMI and NMI observations within the supplied month range.

        The start month is included even when start is mid-month. Rows use the first
        day of each month; filter series to select PMI or NMI.
        """
        return parse(self._http.fetch(request(start, end)), start, end)

    def indicators(
        self, *, start: date, end: date, table: str = "signal"
    ) -> list[EconomicObservation]:
        """依 table 查月觀測值；包含 start 所在月份，燈號與數值分開.

        English:

        Return monthly business-cycle observations for table within the month range.

        table is signal, signal_components, leading, coincident or lagging.
        The start month is included; numeric values and signal labels are separate.
        """
        return parse(self._http.fetch(request(start, end, table)), start, end, table)


class AsyncNDC:
    """以 await 查詢按月公布的 PMI、NMI 與景氣觀測值.

    English:

    Awaitable monthly PMI, NMI and business-cycle observations.
    """

    def __init__(self, http: AsyncHttp) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http

    async def pmi(self, *, start: date, end: date) -> list[EconomicObservation]:
        """取得期間內的 PMI 與 NMI；包含 start 所在月份，以 series 篩選系列.

        English:

        Return monthly PMI and NMI observations within the supplied month range.

        The start month is included even when start is mid-month. Rows use the first
        day of each month; filter series to select PMI or NMI.
        """
        return parse(await self._http.fetch(request(start, end)), start, end)

    async def indicators(
        self, *, start: date, end: date, table: str = "signal"
    ) -> list[EconomicObservation]:
        """依 table 查月觀測值；包含 start 所在月份，燈號與數值分開.

        English:

        Return monthly business-cycle observations for table within the month range.

        table is signal, signal_components, leading, coincident or lagging.
        The start month is included; numeric values and signal labels are separate.
        """
        return parse(
            await self._http.fetch(request(start, end, table)), start, end, table
        )
