"""Bounded batch execution preserving order, duplicate inputs and failures."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar

from twmarket.models.batch import BatchResult
from twmarket.models.instruments import Contract

T = TypeVar("T")
Input = TypeVar("Input")
InstrumentInput = TypeVar("InstrumentInput", str, str | Contract)


def batch(
    fetch: Callable[[InstrumentInput], T], instruments: Iterable[InstrumentInput]
) -> list[BatchResult[T]]:
    result: list[BatchResult[T]] = []
    for instrument in instruments:
        try:
            result.append(BatchResult(instrument, fetch(instrument), None))
        except Exception as exc:
            result.append(BatchResult(instrument, None, exc))
    return result


async def async_batch(
    fetch: Callable[[InstrumentInput], Awaitable[T]],
    instruments: Iterable[InstrumentInput],
) -> list[BatchResult[T]]:
    async def one(instrument: InstrumentInput) -> BatchResult[T]:
        try:
            return BatchResult(instrument, await fetch(instrument), None)
        except Exception as exc:
            return BatchResult(instrument, None, exc)

    return await async_map(one, instruments)


async def async_map(
    fetch: Callable[[Input], Awaitable[T]], items: Iterable[Input]
) -> list[T]:
    """Eight reusable workers; ordered results and cancellation on any failure."""
    inputs = iter(enumerate(items))
    result: dict[int, T] = {}

    async def worker() -> None:
        for index, item in inputs:
            result[index] = await fetch(item)

    tasks = [asyncio.create_task(worker()) for _ in range(8)]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return [result[index] for index in range(len(result))]
