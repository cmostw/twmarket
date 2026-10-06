"""Structured financial observations, monthly revenue and dividend decisions."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from .common import SourceInfo


@dataclass(frozen=True, slots=True)
class FinancialValue:
    """保存一個科目、期間與金額或百分數；來源未標示單位時為 None.

    English:

    One financial account, reporting period and measure.

    measure separates amounts from percentages; percentages retain percent units.
    A missing value or unspecified source unit is None.
    """

    symbol: str
    kind: str
    report_year: int
    report_quarter: int
    report_type: str | None
    account: str
    depth: int
    is_empty: bool
    period_start: date | None
    period_end: date
    period_label: str
    measure: Literal["amount", "percentage"]
    value: Decimal | None
    unit: str | None
    source: SourceInfo


@dataclass(frozen=True, slots=True)
class FinancialStatement:
    """保存報表年度、季度及各科目自身的報導期間.

    English:

    A reported financial table with account/period/measure rows.

    Year and quarter identify the report; individual rows retain their own periods.
    """

    symbol: str
    kind: str
    year: int
    quarter: int
    report_type: str | None
    rows: tuple[FinancialValue, ...]
    source: SourceInfo


@dataclass(frozen=True, slots=True)
class Revenue:
    """保存當月與累計營收及增減；金額與百分數維持來源單位.

    English:

    Reported monthly and cumulative revenue with year-over-year changes.

    Amounts retain source units; percentage changes retain percent units.
    """

    symbol: str
    year: int
    month: int
    current: Decimal | None
    previous_year: Decimal | None
    change: Decimal | None
    change_percent: Decimal | None
    cumulative: Decimal | None
    previous_year_cumulative: Decimal | None
    cumulative_change: Decimal | None
    cumulative_change_percent: Decimal | None
    unit: str
    source: SourceInfo


@dataclass(frozen=True, slots=True)
class Dividend:
    """保存普通／特別股決議；盈餘期間、決議日期及各類股利分開.

    English:

    One common/preferred-share dividend decision and profit period.

    Cash amounts, per-share dividends and stock quantities retain distinct units.
    Board and meeting dates are separate from the profit period.
    """

    symbol: str
    share_class: Literal["common", "preferred"]
    share_name: str | None
    status: str
    year: int
    quarter: int | None
    period_start: date | None
    period_end: date | None
    installment: int | None
    board_date: date | None
    meeting_date: date | None
    opening_retained_earnings: Decimal | None
    net_income: Decimal | None
    distributable_earnings: Decimal | None
    closing_retained_earnings: Decimal | None
    cash_from_earnings: Decimal | None
    cash_from_legal_reserve: Decimal | None
    cash_from_capital_reserve: Decimal | None
    cash_total: Decimal | None
    stock_from_earnings: Decimal | None
    stock_from_legal_reserve: Decimal | None
    stock_from_capital_reserve: Decimal | None
    stock_total_shares: int | None
    par_value: Decimal | None
    par_currency: str | None
    source: SourceInfo
    amount_unit: str = "元"
    per_share_unit: str = "元/股"
