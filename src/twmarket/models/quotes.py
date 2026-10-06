"""Quote snapshots preserve bid/ask levels and source timestamps."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from .common import SourceInfo
from .instruments import Contract, Session


@dataclass(frozen=True, slots=True)
class BookLevel:
    """保存一個買檔或賣檔的檔位、價格及數量.

    English:

    One numbered bid or ask level with a price and optional quantity.
    """

    level: int
    price: Decimal
    size: int | None


@dataclass(frozen=True, slots=True)
class Quote:
    """保存成交與買賣檔快照；報價時間為台北時區，stale 表示待重新同步.

    English:

    A quote snapshot with separate last-trade and bid/ask fields.

    quoted_at uses Asia/Taipei when available. stale marks a snapshot awaiting
    resynchronization. source.received_at records retrieval time.
    """

    symbol: str
    last: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    volume: int | None
    volume_unit: Literal["lots", "contracts"]
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    quoted_at: datetime | None
    source: SourceInfo
    session: Session | None = None
    source_date: date | None = None
    status: str | None = None
    contract: Contract | None = None
    stale: bool = False
