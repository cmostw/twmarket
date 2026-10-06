"""Published monthly observations and explicit currency-pair direction."""

from dataclasses import dataclass
from datetime import date as Date
from decimal import Decimal

from .common import SourceInfo


@dataclass(frozen=True, slots=True)
class EconomicObservation:
    """保存按月系列數值或景氣燈號；period 為觀測月份首日.

    English:

    One monthly series value or published signal label.

    period is the first day of the observation month; value and text are separate.
    """

    period: Date
    series: str
    value: Decimal | None
    text: str | None
    source: SourceInfo


@dataclass(frozen=True, slots=True)
class ExchangeRate:
    """保存來源日期與 numerator／denominator 匯率方向.

    English:

    Published numerator/denominator exchange rate on a source date.

    rate retains the source pair direction; published_date is separate from date.
    """

    date: Date
    numerator: str
    denominator: str
    rate: Decimal | None
    published_date: Date | None
    source: SourceInfo
