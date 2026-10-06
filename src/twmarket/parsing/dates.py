"""Date ranges, ROC dates, and explicit Taipei quote timestamps."""

from collections.abc import Iterator
from datetime import date, datetime
from zoneinfo import ZoneInfo

from twmarket.errors import SchemaError

TAIPEI = ZoneInfo("Asia/Taipei")


def parse_date(value: object) -> date:
    text = str(value).strip().replace("-", "/")
    try:
        if "/" in text:
            year, month, day = map(int, text.split("/"))
            return date(year + 1911 if 1 <= year <= 999 else year, month, day)
        if len(text) == 7 and text.isdigit():
            return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:]))
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise SchemaError(f"Invalid date: {value!r}") from exc


def months(start: date, end: date) -> Iterator[date]:
    if type(start) is not date or type(end) is not date:
        raise TypeError("start and end must be datetime.date instances")
    if start > end:
        raise ValueError("start must not be after end")
    cursor = start.replace(day=1)
    while cursor <= end:
        yield cursor
        cursor = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)


def quote_time(day: object, clock: object) -> datetime | None:
    if not day or not clock or str(clock) in {"-", "--"}:
        return None
    parsed_day = parse_date(day)
    text = str(clock).replace(":", "")
    try:
        parsed_time = datetime.strptime(text, "%H%M%S").time()
    except ValueError as exc:
        raise SchemaError(f"Invalid quote time: {clock!r}") from exc
    return datetime.combine(parsed_day, parsed_time, TAIPEI)
