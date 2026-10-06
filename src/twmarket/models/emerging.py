"""Negotiated-market records are distinct from OHLC and a central order book."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .common import SourceInfo


@dataclass(frozen=True, slots=True)
class EmergingDaily:
    """保存興櫃高低價、加權均價與成交資料；量／額為股／元.

    English:

    Emerging-stock daily high, low, weighted average and turnover.

    Volume is shares and amount is TWD. block_* fields hold block-trade totals.
    """

    symbol: str
    date: date
    high: Decimal | None
    low: Decimal | None
    weighted_average: Decimal | None
    volume: int | None
    amount: Decimal | None
    transactions: int | None
    source: SourceInfo
    block_volume: int | None = None
    block_amount: Decimal | None = None
    block_high: Decimal | None = None
    block_low: Decimal | None = None
    block_weighted_average: Decimal | None = None
    block_transactions: int | None = None


@dataclass(frozen=True, slots=True)
class BrokerQuote:
    """保存個別推薦券商的買賣價量及來源時間.

    English:

    One recommending broker bid/ask quote and its source timestamp.
    """

    broker: str
    bid: Decimal | None
    bid_size: int | None
    ask: Decimal | None
    ask_size: int | None
    quoted_at: datetime | None


@dataclass(frozen=True, slots=True)
class EmergingQuote:
    """保存興櫃成交統計與券商個別報價；量／額為股／元.

    English:

    Emerging-stock trade statistics and individual broker quotes.

    Volume is shares and amount is TWD; quoted_at uses Asia/Taipei when available.
    """

    symbol: str
    last: Decimal | None
    high: Decimal | None
    low: Decimal | None
    weighted_average: Decimal | None
    volume: int | None
    amount: Decimal | None
    quoted_at: datetime | None
    broker_quotes: tuple[BrokerQuote, ...]
    source: SourceInfo
    status: str | None = None
