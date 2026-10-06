"""Official security metadata, index observations and market events."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from .common import SourceInfo

Market = Literal["twse", "tpex", "esb"]
EventKind = Literal["rights", "dividend", "rights_and_dividend"]
RestrictionKind = Literal["attention", "disposition", "suspended"]


@dataclass(frozen=True, slots=True)
class Instrument:
    """保存證券代號、ISIN、分類及來源日期；代號保留前導零.

    English:

    A security catalog entry with its original code, ISIN and category.

    Codes retain leading zeros; as_of is the source update date when available.
    """

    symbol: str
    name: str
    market: Market
    category: str
    isin: str | None
    listed_on: date | None
    industry: str | None
    cfi: str | None
    source: SourceInfo
    as_of: date | None = None


@dataclass(frozen=True, slots=True)
class IndexDaily:
    """保存每日指數 OHLC 與來源單位.

    English:

    Daily index OHLC values in the source unit, normally points.
    """

    index: str
    date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    source: SourceInfo
    change: Decimal | None = None
    unit: str = "points"


@dataclass(frozen=True, slots=True)
class IndexClose:
    """保存價格／報酬指數收盤、發布單位及來源日期.

    English:

    Published closing level for a price or total-return index.

    Publisher, date and percentage change retain the source definitions.
    """

    index: str
    date: date
    kind: Literal["price", "total_return"]
    publisher: str
    close: Decimal | None
    change: Decimal | None
    change_percent: Decimal | None
    source: SourceInfo
    has_special_note: bool = False
    unit: str = "points"


@dataclass(frozen=True, slots=True)
class ExRight:
    """保存歷史除權息事件及參考價格；每千股配股數獨立保存.

    English:

    A historical ex-rights/dividend event with reference prices.

    Share allocations per thousand shares are distinct from schedule ratios.
    """

    symbol: str
    date: date
    name: str
    kind: EventKind
    previous_close: Decimal | None
    reference_price: Decimal | None
    adjustment: Decimal | None
    limit_up: Decimal | None
    limit_down: Decimal | None
    opening_reference: Decimal | None
    dividend_reference: Decimal | None
    source: SourceInfo
    rights_value: Decimal | None = None
    dividend_value: Decimal | None = None
    cash_dividend: Decimal | None = None
    bonus_shares_per_thousand: Decimal | None = None
    subscription_shares: int | None = None
    subscription_price: Decimal | None = None
    public_shares: int | None = None
    employee_shares: int | None = None
    shareholder_shares: int | None = None
    subscription_shares_per_thousand: Decimal | None = None
    price_unit: str = "TWD"


@dataclass(frozen=True, slots=True)
class ExRightSchedule:
    """保存最新除權息預告；配股率與每千股配股數分開.

    English:

    An upcoming ex-rights/dividend event from the current source schedule.

    Share ratios and allocations per thousand shares retain separate fields.
    """

    symbol: str
    date: date
    name: str
    kind: EventKind
    cash_dividend: Decimal | None
    bonus_share_ratio: Decimal | None
    subscription_share_ratio: Decimal | None
    subscription_price: Decimal | None
    public_shares: int | None
    employee_shares: int | None
    shareholder_shares: int | None
    shareholder_subscription_shares_per_thousand: Decimal | None
    source: SourceInfo
    price_unit: str = "TWD"


@dataclass(frozen=True, slots=True)
class TradingRestriction:
    """保存注意、處置或暫停交易的公告日期、有效期間與時間.

    English:

    Published attention, disposition or suspension fields.

    Announcement, effective dates and Taipei halt/resumption times are separate.
    """

    symbol: str
    name: str
    market: Market
    kind: RestrictionKind
    announced_on: date | None
    starts_on: date | None
    ends_on: date | None
    source: SourceInfo
    halted_at: datetime | None = None
    resumed_at: datetime | None = None
    close: Decimal | None = None
    price_earnings_ratio: Decimal | None = None


@dataclass(frozen=True, slots=True)
class TradingStatus:
    """保存最新交易方式及暫停狀態；來源無日期時 date 為 None.

    English:

    Current altered-trading, matching and suspension status.

    A source without a publication date has date=None.
    """

    symbol: str
    name: str
    market: Literal["twse", "tpex"]
    date: date | None
    altered: bool
    segmented: bool | None
    managed: bool | None
    suspended: bool | None
    matching_interval_minutes: int | None
    source: SourceInfo
