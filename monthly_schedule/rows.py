"""Assemble the per-day rows that feed both workbook tables."""

from monthly_schedule.month_dates import get_month_dates
from monthly_schedule.eligibility import is_day_eligible
from monthly_schedule.daily_schedule import build_daily_schedule

DAY_ABBR = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
TIME_KEYS = ("pickup", "arrival", "time_in", "time_out", "departure", "dropoff")


def build_rows(year, month, authorized_weekdays, rules, rng, exclusions=None):
    """Return a list of row dicts (one per calendar day). Each row has
    'date', 'day', and the six TIME_KEYS. Ineligible days have ''
    for every time key."""
    rows = []
    for day in get_month_dates(year, month):
        row = {"date": day, "day": DAY_ABBR[day.isoweekday()]}
        if is_day_eligible(day, authorized_weekdays, exclusions):
            row.update(build_daily_schedule(rules, rng))
        else:
            for key in TIME_KEYS:
                row[key] = ""
        rows.append(row)
    return rows
