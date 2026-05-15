"""Produce every calendar date in a given year/month."""

import calendar
from datetime import date


def get_month_dates(year, month):
    """Return a list of date objects from the 1st through the last
    day of the given year/month, inclusive."""
    last_day = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, last_day + 1)]
