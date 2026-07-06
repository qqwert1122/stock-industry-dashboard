from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import date


def to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text == ".":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fmt_number(value: float, digits: int = 2) -> str:
    if abs(value) >= 100:
        return f"{value:,.1f}"
    if abs(value) >= 10:
        return f"{value:,.2f}"
    return f"{value:,.{digits}f}"


def fmt_signed(value: float, digits: int = 2) -> str:
    return f"{value:+,.{digits}f}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1f}%"


def pct_change(latest: float, previous: float | None) -> float | None:
    if previous in (None, 0):
        return None
    return (latest / previous - 1) * 100


def add_months(month: date, delta: int) -> date:
    index = month.year * 12 + month.month - 1 + delta
    year, month_index = divmod(index, 12)
    return date(year, month_index + 1, 1)


def month_key(month: date) -> str:
    return f"{month.year}{month.month:02d}"


def display_month(month: date) -> str:
    return f"{month.year}.{month.month:02d}"


def iter_month_windows(start: date, end: date, max_months: int = 12) -> Iterator[tuple[date, date]]:
    cursor = start
    while cursor <= end:
        window_end = min(add_months(cursor, max_months - 1), end)
        yield cursor, window_end
        cursor = add_months(window_end, 1)
