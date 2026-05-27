"""Assemble the per-day rows that feed both workbook tables."""

from monthly_schedule.month_dates import get_month_dates
from monthly_schedule.per_day import compute_day_eligibility
from monthly_schedule.daily_schedule import build_daily_schedule

DAY_ABBR = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
TIME_KEYS = ("pickup", "arrival", "time_in", "time_out", "departure", "dropoff")


def build_rows(year, month, ctx, plan_rules, rng):
    """Return a list of row dicts (one per calendar day).

    `ctx` is a MemberContext from monthly_schedule.eligibility_context.
    `plan_rules` is the dict returned by get_rules_for_plan().

    Ineligible days have '' for every time key. Eligible days are filled
    via build_daily_schedule, honoring any narrowed arrival window the
    member's Availability rule imposes."""
    rows = []
    for day in get_month_dates(year, month):
        row = {"date": day, "day": DAY_ABBR[day.isoweekday()]}
        result = compute_day_eligibility(day, ctx, plan_rules)
        if result.eligible:
            row.update(build_daily_schedule(
                plan_rules, rng, arrival_window=result.arrival_window
            ))
        else:
            for key in TIME_KEYS:
                row[key] = ""
        rows.append(row)
    return rows
