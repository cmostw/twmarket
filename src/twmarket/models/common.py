"""Source provenance shared by records from the same response."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """記錄來源、端點及 UTC 取得時間；取得時間與交易日分開.

    English:

    Response provenance.

    received_at is the timezone-aware UTC retrieval time, not a trading date.
    """

    provider: str
    url: str
    received_at: datetime
