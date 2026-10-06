"""Company disclosures with matching sync and async APIs."""

from twmarket.models.disclosures import Dividend, FinancialStatement, Revenue
from twmarket.parsing.json import symbol
from twmarket.transport.http import AsyncHttp, Http

from .data import (
    dividends_request,
    parse_dividends,
    parse_revenue,
    parse_statement,
    revenue_request,
    statement_request,
)


class MOPS:
    """依公司代號與西元年度查詢財報、營收及股利.

    English:

    Company financial statements, monthly revenue and dividend decisions.

    Company codes are strings; query years use the Gregorian calendar.
    """

    def __init__(self, http: Http) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http

    def _statement(
        self, code: str, kind: str, year: int | None, quarter: int | None
    ) -> FinancialStatement:
        return parse_statement(
            self._http.fetch(statement_request(code, kind, year, quarter)),
            symbol(code),
            kind,
            year,
            quarter,
        )

    def income_statement(
        self, code: str, *, year: int | None = None, quarter: int | None = None
    ) -> FinancialStatement:
        """取得損益表；year 為西元、quarter 為 1–4，兩者同時指定或省略查最新.

        English:

        Return the company's reported income statement as account/period rows.

        code is a string; year is Gregorian and quarter is 1-4. Supply both or
        neither; omitting both requests the latest report. No report raises NoDataError.
        """
        return self._statement(code, "income", year, quarter)

    def balance_sheet(
        self, code: str, *, year: int | None = None, quarter: int | None = None
    ) -> FinancialStatement:
        """取得資產負債表；year 為西元、quarter 為 1–4，兩者同時指定或省略查最新.

        English:

        Return the company's reported balance sheet as account/period rows.

        code is a string; year is Gregorian and quarter is 1-4. Supply both or
        neither; omitting both requests the latest report. No report raises NoDataError.
        """
        return self._statement(code, "balance", year, quarter)

    def cash_flow_statement(
        self, code: str, *, year: int | None = None, quarter: int | None = None
    ) -> FinancialStatement:
        """取得現金流量表；year 為西元、quarter 為 1–4，兩者同時指定或省略查最新.

        English:

        Return the company's reported cash-flow statement as account/period rows.

        code is a string; year is Gregorian and quarter is 1-4. Supply both or
        neither; omitting both requests the latest report. No report raises NoDataError.
        """
        return self._statement(code, "cashflow", year, quarter)

    def revenue(
        self, code: str, *, year: int | None = None, month: int | None = None
    ) -> Revenue:
        """取得營收；year 為西元、month 為 1–12，兩者同時指定或省略查最新.

        English:

        Return the company's reported monthly revenue and cumulative values.

        code is a string; year is Gregorian and month is 1-12. Supply both or
        neither; omitting both requests the latest month. Amounts retain source units.
        """
        return parse_revenue(
            self._http.fetch(revenue_request(code, year, month)),
            symbol(code),
            year,
            month,
        )

    def dividends(self, code: str, *, start_year: int, end_year: int) -> list[Dividend]:
        """依含起訖年度的西元決議年查股利；盈餘期間可能早於決議年.

        English:

        Return dividend decisions within inclusive Gregorian decision years.

        start_year/end_year select decision years; profit periods may be earlier.
        Common and preferred-share decisions remain separate records.
        """
        return parse_dividends(
            self._http.fetch(dividends_request(code, start_year, end_year)),
            symbol(code),
        )


class AsyncMOPS:
    """以 await 依公司代號與西元年度查詢財報、營收及股利.

    English:

    Awaitable financial statements, revenue and dividend decisions.

    Company codes are strings; query years use the Gregorian calendar.
    """

    def __init__(self, http: AsyncHttp) -> None:
        """Initialize the source namespace with its owning HTTP transport."""
        self._http = http

    async def _statement(
        self, code: str, kind: str, year: int | None, quarter: int | None
    ) -> FinancialStatement:
        return parse_statement(
            await self._http.fetch(statement_request(code, kind, year, quarter)),
            symbol(code),
            kind,
            year,
            quarter,
        )

    async def income_statement(
        self, code: str, *, year: int | None = None, quarter: int | None = None
    ) -> FinancialStatement:
        """取得損益表；year 為西元、quarter 為 1–4，兩者同時指定或省略查最新.

        English:

        Return the company's reported income statement as account/period rows.

        code is a string; year is Gregorian and quarter is 1-4. Supply both or
        neither; omitting both requests the latest report. No report raises NoDataError.
        """
        return await self._statement(code, "income", year, quarter)

    async def balance_sheet(
        self, code: str, *, year: int | None = None, quarter: int | None = None
    ) -> FinancialStatement:
        """取得資產負債表；year 為西元、quarter 為 1–4，兩者同時指定或省略查最新.

        English:

        Return the company's reported balance sheet as account/period rows.

        code is a string; year is Gregorian and quarter is 1-4. Supply both or
        neither; omitting both requests the latest report. No report raises NoDataError.
        """
        return await self._statement(code, "balance", year, quarter)

    async def cash_flow_statement(
        self, code: str, *, year: int | None = None, quarter: int | None = None
    ) -> FinancialStatement:
        """取得現金流量表；year 為西元、quarter 為 1–4，兩者同時指定或省略查最新.

        English:

        Return the company's reported cash-flow statement as account/period rows.

        code is a string; year is Gregorian and quarter is 1-4. Supply both or
        neither; omitting both requests the latest report. No report raises NoDataError.
        """
        return await self._statement(code, "cashflow", year, quarter)

    async def revenue(
        self, code: str, *, year: int | None = None, month: int | None = None
    ) -> Revenue:
        """取得營收；year 為西元、month 為 1–12，兩者同時指定或省略查最新.

        English:

        Return the company's reported monthly revenue and cumulative values.

        code is a string; year is Gregorian and month is 1-12. Supply both or
        neither; omitting both requests the latest month. Amounts retain source units.
        """
        return parse_revenue(
            await self._http.fetch(revenue_request(code, year, month)),
            symbol(code),
            year,
            month,
        )

    async def dividends(
        self, code: str, *, start_year: int, end_year: int
    ) -> list[Dividend]:
        """依含起訖年度的西元決議年查股利；盈餘期間可能早於決議年.

        English:

        Return dividend decisions within inclusive Gregorian decision years.

        start_year/end_year select decision years; profit periods may be earlier.
        Common and preferred-share decisions remain separate records.
        """
        return parse_dividends(
            await self._http.fetch(dividends_request(code, start_year, end_year)),
            symbol(code),
        )
