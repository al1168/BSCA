"""Produce every calendar date in a given year/month."""

import calendar
from datetime import date


def get_month_dates(year, month, start_day=None, end_day=None):
    """Return a list of date objects in the given year/month.

    By default returns every day of the month (1..last day, inclusive),
    with leap years handled by `calendar.monthrange`. When `start_day`
    and/or `end_day` are provided, the result is trimmed to that
    inclusive range — the values must satisfy
    `1 <= start_day <= end_day <= last_day_of_month` or ValueError is
    raised. A None on either side defaults to the natural boundary."""
    last_day = calendar.monthrange(year, month)[1]
    lo = 1 if start_day is None else start_day
    hi = last_day if end_day is None else end_day
    if lo < 1 or hi < 1:
        raise ValueError(
            f"start_day/end_day must be >= 1 (got {lo}..{hi})"
        )
    if hi > last_day:
        raise ValueError(
            f"end_day {hi} exceeds last day of "
            f"{year:04d}-{month:02d} ({last_day})"
        )
    if lo > hi:
        raise ValueError(
            f"start_day {lo} is after end_day {hi}"
        )
    return [date(year, month, d) for d in range(lo, hi + 1)]
