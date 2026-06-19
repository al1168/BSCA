"""Assemble the per-day rows that feed both workbook tables."""

from monthly_schedule.auth_days import get_authorized_weekdays
from monthly_schedule.month_dates import get_month_dates
from monthly_schedule.per_day import compute_day_eligibility, OneOffConflict
from monthly_schedule.daily_schedule import build_daily_schedule
from monthly_schedule.rules import parse_hhmm
from monthly_schedule.time_cache import lookup_times, store_times

DAY_ABBR = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
TIME_KEYS = ("pickup", "arrival", "time_in", "time_out", "departure", "dropoff")


def build_rows(year, month, ctx, plan_rules, rng,
               start_day=None, end_day=None,
               time_cache=None, center_id=None,
               plan=None, travel_minutes=None):
    """Return a list of row dicts (one per calendar day in the requested
    range — defaults to the full month).

    `ctx` is a MemberContext from monthly_schedule.eligibility_context.
    `plan_rules` is the dict returned by get_rules_for_plan().

    Ineligible days have '' for every time key. Eligible days are filled
    via build_daily_schedule, honoring any narrowed arrival window the
    member's Availability rule imposes.

    When `time_cache` is provided (along with `center_id`, `plan`, and
    `travel_minutes`), each eligible day is first looked up in the cache
    so re-runs after a partial schedule reuse the previously-generated
    times. Cache misses (or stale entries that fail the plan/travel/
    arrival-window invalidation guard) are filled by build_daily_schedule
    and stored back into `time_cache` for next time. `time_cache` is
    mutated in place; the caller persists it."""
    rows = []
    use_cache = (
        time_cache is not None and center_id is not None
        and plan is not None and travel_minutes is not None
    )
    plan_default_window = (
        parse_hhmm(plan_rules["arrival_window"][0]),
        parse_hhmm(plan_rules["arrival_window"][1]),
    )
    for day in get_month_dates(year, month, start_day, end_day):
        row = {"date": day, "day": DAY_ABBR[day.isoweekday()]}
        result = compute_day_eligibility(day, ctx, plan_rules)
        if result.eligible:
            effective_window = (
                result.arrival_window
                if result.arrival_window is not None
                else plan_default_window
            )
            times = None
            if use_cache:
                times = lookup_times(
                    time_cache, center_id, day,
                    plan, travel_minutes, effective_window,
                )
            if times is None:
                times = build_daily_schedule(
                    plan_rules, rng,
                    arrival_window=result.arrival_window,
                )
                if use_cache:
                    store_times(
                        time_cache, center_id, day,
                        times, plan, travel_minutes,
                    )
            row.update(times)
        else:
            for key in TIME_KEYS:
                row[key] = ""
        rows.append(row)
    return rows


def build_debug_rows(year, month, ctx, plan_rules,
                     start_day=None, end_day=None):
    """Diagnostic rows for the debug CSV (one per authorized day).

    A day is "authorized" iff there's an active authorization on it AND
    that day's weekday is in the authorization's auth_days. Non-
    authorized days are skipped (the user only wants reasons for days
    they expected to be scheduled).

    Each row is {date, day, scheduled, reason}. `scheduled` is True
    when compute_day_eligibility accepted the day; otherwise False with
    a non-empty `reason` from REASON_DAY_*. A OneOffConflict is caught
    per-day and reported as the reason, so the CSV always completes
    even when the schedule build itself fails.
    """
    rows = []
    for day in get_month_dates(year, month, start_day, end_day):
        auth = ctx.active_authorization(day)
        if auth is None:
            continue
        if day.isoweekday() not in get_authorized_weekdays(auth["auth_days"]):
            continue
        try:
            result = compute_day_eligibility(day, ctx, plan_rules)
            scheduled = result.eligible
            reason = "" if scheduled else (result.reason or "")
        except OneOffConflict as exc:
            scheduled = False
            reason = exc.reason
        rows.append({
            "date": day,
            "day": DAY_ABBR[day.isoweekday()],
            "scheduled": scheduled,
            "reason": reason,
        })
    return rows
