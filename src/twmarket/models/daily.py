"""Historical records keep the source's price and volume semantics."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from .common import SourceInfo
from .instruments import Contract, Session


@dataclass(frozen=True, slots=True)
class EquityDaily:
    """保存證券日行情與來源單位；TWSE 為股／元，TPEx 為張／千元.

    English:

    Daily security prices and turnover with explicit source units.

    TWSE uses shares/TWD; TPEx uses lots/thousand_TWD. Missing values are None.
    change_basis_reset marks a source reset of the price-change comparison basis.
    """

    symbol: str
    date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: int | None
    amount: Decimal | None
    volume_unit: Literal["shares", "lots"]
    amount_unit: Literal["TWD", "thousand_TWD"]
    source: SourceInfo
    change: Decimal | None = None
    transactions: int | None = None
    raw_change: str | None = None
    change_basis_reset: bool = False


@dataclass(frozen=True, slots=True)
class DerivativeDaily:
    """保存契約交易日、時段及價格；最新成交、結算與合計量分開.

    English:

    Daily contract prices and quantities for one trading date and session.

    last and settlement are separate. volume is session volume; combined_volume
    is the source total. Futures/options quantities use contracts.
    """

    contract: Contract
    date: date
    session: Session
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    last: Decimal | None
    settlement: Decimal | None
    volume: int | None
    open_interest: int | None
    source: SourceInfo
    combined_volume: int | None = None
