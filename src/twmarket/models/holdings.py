"""TDCC shareholding brackets."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .common import SourceInfo


@dataclass(frozen=True, slots=True)
class ShareholdingBracket:
    """保存官方持股級距、人數、股數及百分數；16、17 為調整與總計.

    English:

    A published holding level with people, shares and percentage.

    percentage retains percent units. Levels 16 and 17 are adjustment and total.
    """

    symbol: str
    date: date
    level: int
    people: int | None
    shares: int | None
    percentage: Decimal | None
    source: SourceInfo
