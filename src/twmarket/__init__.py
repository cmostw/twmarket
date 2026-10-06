"""Python interfaces for official Taiwan market data."""

from .async_client import AsyncClient
from .client import Client
from .models.daily import DerivativeDaily, EquityDaily
from .models.disclosures import Dividend, FinancialStatement, FinancialValue, Revenue
from .models.instruments import Contract
from .models.quotes import BookLevel, Quote

__all__ = [
    "AsyncClient",
    "Client",
    "Contract",
    "DerivativeDaily",
    "EquityDaily",
    "Dividend",
    "FinancialStatement",
    "FinancialValue",
    "Revenue",
    "BookLevel",
    "Quote",
]

from .models.batch import BatchResult
from .models.derivatives import (
    ContractSpecification,
    DerivativeProduct,
    MarginRequirement,
    TickSize,
)
from .models.market import (
    ExRight,
    ExRightSchedule,
    IndexClose,
    IndexDaily,
    Instrument,
    TradingRestriction,
    TradingStatus,
)

__all__ += [
    "BatchResult",
    "ContractSpecification",
    "DerivativeProduct",
    "MarginRequirement",
    "TickSize",
    "Instrument",
    "IndexDaily",
    "IndexClose",
    "ExRight",
    "ExRightSchedule",
    "TradingRestriction",
    "TradingStatus",
]
