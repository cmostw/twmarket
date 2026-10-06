"""Exchange product specifications and margin amounts/rates."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from .common import SourceInfo
from .instruments import InstrumentKind

MarginCategory = Literal["index", "stock", "etf", "fx", "commodity", "interest_rate"]


@dataclass(frozen=True, slots=True)
class MarginRequirement:
    """保存保證金金額或百分數；unit 與選擇權風險組件分開.

    English:

    Published initial, maintenance and clearing margin values.

    unit distinguishes source amounts from percentages. Option risk components
    are separate records; date is the source publication date.
    """

    product: str
    name: str
    category: MarginCategory
    date: date
    clearing: Decimal | None
    maintenance: Decimal | None
    initial: Decimal | None
    unit: str
    source: SourceInfo
    underlying: str | None = None
    group: int | None = None
    component: str | None = None


@dataclass(frozen=True, slots=True)
class DerivativeProduct:
    """保存商品目錄、規格 URL 及乘數來源.

    English:

    Product catalog entry with specification and multiplier provenance.
    """

    product: str
    name: str
    kind: InstrumentKind
    specification_url: str
    source: SourceInfo
    underlying: str | None = None
    multiplier: Decimal | None = None
    multiplier_unit: str | None = None
    mis_commodity: str | None = None
    multiplier_source: SourceInfo | None = None


@dataclass(frozen=True, slots=True)
class TickSize:
    """保存 tick 價格級距；lower 含下界、upper 不含上界，None 表示無界.

    English:

    Price tick for a band with inclusive lower and exclusive upper bounds.

    A None bound is unbounded.
    """

    lower: Decimal | None
    upper: Decimal | None
    tick: Decimal


@dataclass(frozen=True, slots=True)
class ContractSpecification:
    """保存乘數、幣別、交割方式及 tick 級距；來源缺值為 None.

    English:

    Product multiplier, currency, settlement method and tick bands.

    Missing source metadata is None; multiplier_source identifies the share table.
    """

    product: str
    name: str
    kind: InstrumentKind
    underlying: str
    multiplier: Decimal | None
    multiplier_unit: str | None
    currency: str | None
    settlement: Literal["cash", "physical"] | None
    source: SourceInfo
    ticks: tuple[TickSize, ...] = ()
    multiplier_source: SourceInfo | None = None
