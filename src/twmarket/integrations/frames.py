"""Optional, explicit conversion with stable schemas and exact decimals."""

from __future__ import annotations

import types
from collections.abc import Iterable
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import (
    TYPE_CHECKING,
    Literal,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from twmarket.models.batch import BatchResult
from twmarket.models.daily import EquityDaily
from twmarket.models.disclosures import FinancialStatement, FinancialValue
from twmarket.models.instruments import Contract
from twmarket.models.quotes import Quote

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl

PriceType = Literal["decimal", "float"]
SKIP = {"bids", "asks", "broker_quotes", "ticks"}


def scalar_type(annotation: object) -> object:
    origin = get_origin(annotation)
    if origin in {types.UnionType, Union}:
        return scalar_type(next(a for a in get_args(annotation) if a is not type(None)))
    if origin is Literal:
        first: object = get_args(annotation)[0]
        return type(first)
    return annotation


@lru_cache(maxsize=128)
def _schema(model: type[object], prefix: str = "") -> dict[str, object]:
    if not is_dataclass(model):
        raise TypeError("model must be a dataclass type")
    result: dict[str, object] = {}
    for name, annotation in get_type_hints(model).items():
        if name in SKIP:
            continue
        name = prefix + name
        kind = scalar_type(annotation)
        if isinstance(kind, type) and is_dataclass(kind):
            result.update(_schema(kind, name + "_"))
        else:
            result[name] = kind
    return result


def schema(model: type[object], prefix: str = "") -> dict[str, object]:
    # Cached schemas are shared; conversion columns are local.
    return dict(_schema(model, prefix))


def flatten(record: object, prefix: str = "") -> dict[str, object]:
    if not is_dataclass(record) or isinstance(record, type):
        raise TypeError("DataFrame records must be dataclass instances")
    result: dict[str, object] = {}
    for field in fields(record):
        if field.name in SKIP:
            continue
        value: object = getattr(record, field.name)
        name = prefix + field.name
        if is_dataclass(value) and not isinstance(value, type):
            result.update(flatten(value, name + "_"))
        else:
            result[name] = value
    return result


def records(
    data: object,
    model: type[object] | None,
    price_type: PriceType,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if price_type not in {"decimal", "float"}:
        raise ValueError("price_type must be 'decimal' or 'float'")
    if isinstance(data, FinancialStatement):
        model = FinancialValue
        data = data.rows
    elif is_dataclass(data) and not isinstance(data, type):
        data = [data]
    if not isinstance(data, Iterable):
        raise TypeError("Expected a dataclass record or an iterable of records")
    rows = list(cast(Iterable[object], data))
    if rows and isinstance(rows[0], BatchResult):
        return batch_records(rows, model)
    model = model or (type(rows[0]) if rows else EquityDaily)
    if any(type(row) is not model for row in rows):
        raise TypeError("All DataFrame records must use the same model")
    columns = schema(model)
    result: list[dict[str, object]] = []
    for row in rows:
        flat = flatten(row)
        result.append({name: flat.get(name) for name in columns})
    return columns, result


def batch_records(
    rows: list[object], model: type[object] | None
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if any(not isinstance(row, BatchResult) for row in rows):
        raise TypeError("Cannot mix batch results and data records")
    batches = cast(list[BatchResult[object]], rows)
    successes = [row.data for row in batches if row.data is not None]
    if model is None:
        if not successes:
            raise TypeError("Pass model=... when every batch entry failed")
        model = type(successes[0])
    if any(type(row) is not model for row in successes):
        raise TypeError("All successful batch entries must use the same model")
    columns = schema(model)
    columns.update(
        {
            "requested_symbol": str,
            **schema(Contract, "requested_"),
            "error_type": str,
            "error_message": str,
        }
    )
    result: list[dict[str, object]] = []
    for row in batches:
        flat = flatten(row.data) if row.data is not None else {}
        if isinstance(row.instrument, Contract):
            flat.update(flatten(row.instrument, "requested_"))
        else:
            flat["requested_symbol"] = row.instrument
        flat["error_type"] = type(row.error).__name__ if row.error else None
        flat["error_message"] = str(row.error) if row.error else None
        result.append({name: flat.get(name) for name in columns})
    return columns, result


def decimal_scale(values: list[object]) -> int:
    decimals = [v for v in values if isinstance(v, Decimal)]
    scale = max([0] + [-int(v.as_tuple().exponent) for v in decimals])
    if any(max(0, v.adjusted() + 1) + scale > 38 for v in decimals) or scale > 38:
        raise ValueError(
            "Values exceed Polars Decimal precision 38; choose float explicitly"
        )
    return scale


def to_pandas(
    data: object,
    *,
    model: type[object] | None = None,
    price_type: PriceType = "decimal",
) -> pd.DataFrame:
    """將同型紀錄、財報或批次結果轉為 pandas DataFrame；model 指定空表 schema.

    English:

    Convert records, a financial statement or batch results to a pandas DataFrame.

    Args:
        data: One record or an iterable of records of the same model.
        model: Schema for empty/all-failed inputs; empty inputs default to EquityDaily.
        price_type: decimal preserves Decimal objects; float converts Decimal values.

    Financial statements expand into account/period/measure rows. Batch frames
    include requested_* and error columns. Order books and tick bands are omitted.
    Requires twmarket[pandas]; invalid or mixed models raise TypeError.
    """
    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportError("Install twmarket[pandas] to use to_pandas") from exc
    columns, rows = records(data, model, price_type)
    series: dict[str, pd.Series] = {}
    for name, kind in columns.items():
        values = [r[name] for r in rows]
        if kind is Decimal and price_type == "float":
            values = [float(v) if isinstance(v, Decimal) else v for v in values]
            series[name] = pd.Series(values, dtype="Float64")
        elif kind is int:
            series[name] = pd.Series(values, dtype="Int64")
        elif kind is bool:
            series[name] = pd.Series(values, dtype="boolean")
        elif kind is datetime:
            timezone = (
                "Asia/Taipei"
                if name in {"quoted_at", "halted_at", "resumed_at"}
                else "UTC"
            )
            series[name] = pd.Series(
                pd.to_datetime(pd.Series(values), utc=True)
            ).dt.tz_convert(timezone)
        else:
            # Decimal and date columns use object dtype.
            series[name] = pd.Series(values, dtype=object)
    return pd.DataFrame(series)


def to_polars(
    data: object,
    *,
    model: type[object] | None = None,
    price_type: PriceType = "decimal",
) -> pl.DataFrame:
    """將同型紀錄、財報或批次結果轉為 Polars DataFrame；model 指定空表 schema.

    English:

    Convert records, a financial statement or batch results to a Polars DataFrame.

    Args:
        data: One record or an iterable of records of the same model.
        model: Schema for empty/all-failed inputs; empty inputs default to EquityDaily.
        price_type: decimal preserves precision; float converts Decimal values.

    Financial statements expand into account/period/measure rows. Batch frames
    include requested_* and error columns. Order books and tick bands are omitted.
    Requires twmarket[polars]; decimals exceeding precision 38 raise ValueError.
    """
    try:
        import polars as pl
    except ImportError as exc:
        raise ImportError("Install twmarket[polars] to use to_polars") from exc
    columns, rows = records(data, model, price_type)
    series: list[pl.Series] = []
    for name, kind in columns.items():
        values = [r[name] for r in rows]
        if kind is Decimal:
            if price_type == "float":
                dtype = pl.Float64
                values = [float(v) if isinstance(v, Decimal) else v for v in values]
            else:
                dtype = pl.Decimal(precision=38, scale=decimal_scale(values))
        elif kind is int:
            dtype = pl.Int64
        elif kind is bool:
            dtype = pl.Boolean
        elif kind is date:
            dtype = pl.Date
        elif kind is datetime:
            dtype = pl.Datetime(
                time_zone="Asia/Taipei"
                if name in {"quoted_at", "halted_at", "resumed_at"}
                else "UTC"
            )
        elif kind is str:
            dtype = pl.String
        else:
            raise TypeError(f"No tabular conversion for field {name}")
        series.append(pl.Series(name, values, dtype=dtype, strict=True))
    return pl.DataFrame(series)


def to_pandas_book(quote: Quote) -> pd.DataFrame:
    """將買賣檔轉成 side、level、price、size 表，保留 Decimal 及空表型別.

    English:

    Return bid/ask rows with side, level, price and size columns.

    Prices retain Decimal; an empty book retains its schema. Requires twmarket[pandas].
    """
    from dataclasses import dataclass

    @dataclass(frozen=True, slots=True)
    class Level:
        side: str
        level: int
        price: Decimal
        size: int | None

    return to_pandas(
        [
            Level(side, level.level, level.price, level.size)
            for side, levels in [("bid", quote.bids), ("ask", quote.asks)]
            for level in levels
        ],
        model=Level,
    )


def to_polars_book(quote: Quote) -> pl.DataFrame:
    """將買賣檔轉成 side、level、price、size 表，保留 Decimal 及空表型別.

    English:

    Return bid/ask rows with side, level, price and size columns.

    Prices retain Decimal; an empty book retains its schema. Requires twmarket[polars].
    """
    from dataclasses import dataclass

    @dataclass(frozen=True, slots=True)
    class Level:
        side: str
        level: int
        price: Decimal
        size: int | None

    return to_polars(
        [
            Level(side, level.level, level.price, level.size)
            for side, levels in [("bid", quote.bids), ("ask", quote.asks)]
            for level in levels
        ],
        model=Level,
    )
