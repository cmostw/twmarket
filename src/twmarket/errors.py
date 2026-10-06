"""Errors that callers can distinguish without inspecting message text."""


class TwmarketError(Exception):
    """Base error for market-data operations."""


class TransportError(TwmarketError):
    """An HTTP request failed after bounded retries."""


class SourceError(TwmarketError):
    """The source reported a failed query."""


class SchemaError(TwmarketError):
    """The source returned unexpected or invalid data."""


class NoDataError(TwmarketError):
    """A single requested instrument has no available data."""


class UnsupportedFeatureError(TwmarketError):
    """The requested data cannot be supplied by this adapter."""
