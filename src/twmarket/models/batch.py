"""Each batch entry retains its input and either data or its exception."""

from dataclasses import dataclass
from typing import Generic, TypeVar

from .instruments import Contract

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BatchResult(Generic[T]):
    """保存原始批次輸入、資料或例外；批次保留順序與重複輸入.

    English:

    An original batch input with either its data or its exception.

    Batch query results retain input order and duplicate entries.
    """

    instrument: str | Contract
    data: T | None
    error: Exception | None

    @property
    def ok(self) -> bool:
        """回傳批次是否沒有例外.

        English:

        Whether this batch entry completed without an exception.
        """
        return self.error is None
