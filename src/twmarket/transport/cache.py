"""Optional TTL/LRU cache bounded by entry count and response bytes."""

import math
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import fields, is_dataclass
from typing import Generic, TypeVar, cast

T = TypeVar("T")


class MemoryCache(Generic[T]):
    def __init__(
        self, *, ttl: float, size: int = 128, max_bytes: int = 32 * 1024 * 1024
    ) -> None:
        if not math.isfinite(ttl) or ttl < 0:
            raise ValueError("cache TTL must be finite and nonnegative")
        if (
            type(size) is not int
            or size < 1
            or type(max_bytes) is not int
            or max_bytes < 1
        ):
            raise ValueError("cache size and byte limit must be positive integers")
        self.ttl, self.size, self.max_bytes = ttl, size, max_bytes
        self._entries: OrderedDict[bytes, tuple[float, T, int]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key: bytes) -> T | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry[0] <= time.monotonic():
                self._bytes -= self._entries.pop(key)[2]
                return None
            self._entries.move_to_end(key)
            return entry[1]

    def put(self, key: bytes, value: T, size: int) -> None:
        if not self.ttl or size > self.max_bytes:
            return
        with self._lock:
            if key in self._entries:
                self._bytes -= self._entries.pop(key)[2]
            self._entries[key] = time.monotonic() + self.ttl, value, size
            self._bytes += size
            while len(self._entries) > self.size or self._bytes > self.max_bytes:
                self._bytes -= self._entries.popitem(last=False)[1][2]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0


def memory_size(value: object) -> int:
    """Estimate retained bytes, counting shared objects once."""
    seen: set[int] = set()

    def visit(item: object) -> int:
        if id(item) in seen:
            return 0
        seen.add(id(item))
        size = sys.getsizeof(item)
        if is_dataclass(item) and not isinstance(item, type):
            size += sum(visit(getattr(item, field.name)) for field in fields(item))
        elif isinstance(item, (tuple, list)):
            size += sum(
                visit(part) for part in cast(tuple[object, ...] | list[object], item)
            )
        return size

    return visit(value)
