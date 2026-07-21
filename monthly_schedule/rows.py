"""Assemble the per-day rows that feed both workbook tables."""

from monthly_schedule.auth_days import (
    get_authorized_weekdays, format_auth_days,
)
from monthly_schedule.month_dates import get_month_dates
from monthly_schedule.per_day import (
    compute_day_eligibility, OneOffConflict, REASON_DAY_WINDOW_TOO_NARROW,
)
from monthly_schedule.daily_schedule import build_daily_schedule
from monthly_schedule.rules import parse_hhmm, format_minutes
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
    via build_daily_schedule, honoring the placement window (day bounds
    intersected with availability) the member's Availability rule imposes.

    When `time_cache` is provided (along with `center_id`, `plan`, and
    `travel_minutes`), each eligible day is first looked up in the cache
    so re-runs after a partial schedule reuse the previously-generated
    times. Cache misses (or stale entries that fail the plan/travel/
    window invalidation guard) are filled by build_daily_schedule and
    stored back into `time_cache` for next time. `time_cache` is mutated
    in place; the caller persists it."""
    rows = []
    use_cache = (
        time_cache is not None and center_id is not None
        and plan is not None and travel_minutes is not None
    )
    plan_default_window = (
        parse_hhmm(plan_rules["earliest_time_in"]),
        parse_hhmm(plan_rules["latest_time_out"]),
    )
    for day in get_month_dates(year, month, start_day, end_day):
        row = {"date": day, "day": DAY_ABBR[day.isoweekday()]}
        result = compute_day_eligibility(day, ctx, plan_rules)
        if result.eligible:
            effective_window = (
                result.placement_window
                if result.placement_window is not None
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
                    window=result.placement_window,
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


def _fmt_duration(minutes):
    """126 -> '2h06m' (durations in the debug reason_detail column)."""
    minutes = max(0, minutes)
    return f"{minutes // 60}h{minutes % 60:02d}m"


def build_debug_rows(year, month, ctx, plan_rules,
                     start_day=None, end_day=None):
    """Diagnostic rows for the debug CSV (one per authorized day).

    A day is "authorized" iff there's an active authorization on it AND
    that day's weekday is in the authorization's auth_days. Non-
    authorized days are skipped (the user only wants reasons for days
    they expected to be scheduled).

    Each row is {date, day, scheduled, reason} plus diagnostic fields
    explaining the decision: `reason_detail` (free-text arithmetic
    behind the reason, e.g. the drop-off reserve subtraction; '' when
    there's nothing to add), `availability` (the effective HH:MM-HH:MM
    window for the day) and `availability_source` (recurring/one-off/''),
    `absent` ('yes (LeaveType)'/'no'), `auth_days` (e.g. '1,3,5'),
    `placement_window` (day bounds intersected with availability,
    populated even for REASON_DAY_WINDOW_TOO_NARROW rejections) and
    `max_length` (the longest session that fits, HH:MM).

    `scheduled` is True when compute_day_eligibility accepted the day;
    otherwise False with a non-empty `reason` from REASON_DAY_*. A
    OneOffConflict is caught per-day and reported as the reason, so the
    CSV always completes even when the schedule build itself fails.
    """
    rows = []
    for day in get_month_dates(year, month, start_day, end_day):
        auth = ctx.active_authorization(day)
        if auth is None:
            continue
        authorized = get_authorized_weekdays(auth["auth_days"])
        if day.isoweekday() not in authorized:
            continue

        # The availability that applies: a one-off overrides the
        # recurring rule for that date.
        one_offs = ctx.one_offs_for(day)
        if one_offs:
            avail_row = one_offs[0] if len(one_offs) == 1 else None
            avail_source = "one-off"
        else:
            avail_row = ctx.availability_for(day)
            avail_source = "recurring" if avail_row else ""
        availability = (
            f"{avail_row['avail_start']}-{avail_row['avail_end']}"
            if avail_row else ""
        )
        absence = ctx.absence_for(day)
        absent = f"yes ({absence['leave_type']})" if absence else "no"

        try:
            result = compute_day_eligibility(day, ctx, plan_rules)
            scheduled = result.eligible
            reason = "" if scheduled else (result.reason or "")
            window = result.placement_window
            reserve = result.dropoff_reserve
        except OneOffConflict as exc:
            scheduled = False
            reason = exc.reason
            window = None
            reserve = 0

        # The placement window actually used: the narrowed window, or
        # the open-day bounds when no availability rule applies.
        if window is None and scheduled:
            window = (
                parse_hhmm(plan_rules["earliest_time_in"]),
                parse_hhmm(plan_rules["latest_time_out"]),
            )
        reason_detail = ""
        if window is not None:
            in_lo, out_hi = window
            placement = f"{format_minutes(in_lo)}-{format_minutes(out_hi)}"
            max_len = max(0, min(plan_rules["session_length_min"][1],
                                 out_hi - in_lo))
            max_length = format_minutes(max_len)
            usable = (f"usable {placement} "
                      f"({_fmt_duration(out_hi - in_lo)})")
            if reason == REASON_DAY_WINDOW_TOO_NARROW:
                min_len = plan_rules["session_length_min"][0]
                prefix = (
                    f"avail {availability} minus {reserve}m "
                    f"drop-off reserve -> " if reserve else ""
                )
                reason_detail = (
                    f"{prefix}{usable} < min {_fmt_duration(min_len)}"
                )
            elif reserve:
                reason_detail = (
                    f"drop-off reserve {reserve}m before "
                    f"{avail_row['avail_end']} avail end"
                )
        else:
            placement = ""
            max_length = ""

        rows.append({
            "date": day,
            "day": DAY_ABBR[day.isoweekday()],
            "scheduled": scheduled,
            "reason": reason,
            "reason_detail": reason_detail,
            "availability": availability,
            "availability_source": avail_source,
            "absent": absent,
            "auth_days": format_auth_days(authorized),
            "placement_window": placement,
            "max_length": max_length,
        })
    return rows
