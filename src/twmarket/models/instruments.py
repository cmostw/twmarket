"""Derivative contract identifiers."""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Literal

InstrumentKind = Literal["future", "option"]
Session = Literal["regular", "after_hours"]


@dataclass(frozen=True, slots=True)
class Contract:
    """標識期貨或選擇權的商品、到期月份／週別、價差、履約價與買賣權.

    English:

    Exact futures or options identity.

    expiry retains month, weekly series or spread periods. Options include strike
    and right; mis_symbol and expires_on are populated from official metadata.
    """

    product: str
    expiry: str
    kind: InstrumentKind = "future"
    strike: Decimal | None = None
    right: Literal["call", "put"] | None = None
    mis_symbol: str | None = None
    expires_on: date | None = None

    @property
    def expiry_month(self) -> str:
        """回傳第一個交割月份；expiry 保留週別與價差期間.

        English:

        Return the first delivery month; expiry retains week/spread information.
        """
        return self.expiry[:6]

    @property
    def legs(self) -> tuple["Contract", ...]:
        """回傳來源價差兩腿期間；單一契約回傳空 tuple.

        English:

        Return source spread legs, or an empty tuple for an outright contract.
        """
        if "/" not in self.expiry:
            return ()
        return tuple(
            replace(self, expiry=period, mis_symbol=None, expires_on=None)
            for period in self.expiry.split("/")
        )
