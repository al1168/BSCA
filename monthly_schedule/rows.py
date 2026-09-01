"""Assemble the per-day rows that feed both workbook tables."""

from monthly_schedule.auth_days import (
    get_authorized_weekdays, format_auth_days,
)
from monthly_schedule.month_dates import get_month_dates
from monthly_schedule.per_day import (
    compute_day_eligibility, OneOffConflict, REASON_DAY_ABSENT,
    REASON_DAY_NOT_ENROLLED, REASON_DAY_NO_AUTH,
    REASON_DAY_WRONG_WEEKDAY, REASON_DAY_WINDOW_TOO_NARROW,
)
from monthly_schedule.daily_schedule import build_daily_schedule
from monthly_schedule.rules import parse_hhmm, format_minutes, band_for_member
from monthly_schedule.time_cache import lookup_times, store_times

DAY_ABBR = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
DAY_NAME = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday",
            5: "Friday", 6: "Saturday", 7: "Sunday"}
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

    Each row also carries `status`: "attended" (eligible), "absent"
    (rejected by REASON_DAY_ABSENT) or "ineligible" (any other
    rejection). The activity log workbook keys off it so its day grid
    mirrors the timesheet exactly.

    When `time_cache` is provided (along with `center_id`, `plan`, and
    `travel_minutes`), each eligible day is first looked up in the cache
    so re-runs after a partial schedule reuse the previously-generated
    times. Cache misses (or stale entries that fail the plan/travel/
    window invalidation guard) are filled by build_daily_schedule and
    stored back into `time_cache` for next time. `time_cache` is mutated
    in place; the caller persists it.

    Time-In placement honors the member's morning/afternoon band
    (band_for_member) when the feature is enabled; cached days are
    reused verbatim regardless of band."""
    rows = []
    use_cache = (
        time_cache is not None and center_id is not None
        and plan is not None and travel_minutes is not None
    )
    plan_default_window = (
        parse_hhmm(plan_rules["earliest_time_in"]),
        parse_hhmm(plan_rules["latest_time_out"]),
    )
    band = band_for_member(center_id, plan_rules)
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
                    band=band,
                )
                if use_cache:
                    store_times(
                        time_cache, center_id, day,
                        times, plan, travel_minutes,
                    )
            row.update(times)
            row["status"] = "attended"
        else:
            for key in TIME_KEYS:
                row[key] = ""
            row["status"] = ("absent" if result.reason == REASON_DAY_ABSENT
                             else "ineligible")
        rows.append(row)
    return rows


def _fmt_duration(minutes):
    """126 -> '2h06m' (durations in the debug reason_detail column)."""
    minutes = max(0, minutes)
    return f"{minutes // 60}h{minutes % 60:02d}m"


def _reason_detail(reason, availability, reserve, in_lo, out_hi,
                    plan_rules, avail_row, pickup_reserve=0):
    """Free-text arithmetic behind a window decision ('' when the
    numbers add nothing: open days, non-window rejections)."""
    if reason == REASON_DAY_WINDOW_TOO_NARROW:
        usable = (f"usable {format_minutes(in_lo)}-{format_minutes(out_hi)} "
                  f"({_fmt_duration(out_hi - in_lo)})")
        min_len = plan_rules["session_length_min"][0]
        subtracted = []
        if pickup_reserve:
            subtracted.append(f"{pickup_reserve}m pick-up reserve")
        if reserve:
            subtracted.append(f"{reserve}m drop-off reserve")
        if subtracted:
            return (f"avail {availability} minus {' and '.join(subtracted)} "
                    f"-> {usable} < min {_fmt_duration(min_len)}")
        return f"{usable} < min {_fmt_duration(min_len)}"
    notes = []
    if pickup_reserve:
        notes.append(f"pick-up reserve {pickup_reserve}m after "
                     f"{avail_row['avail_start']} avail start")
    if reserve:
        notes.append(f"drop-off reserve {reserve}m before "
                     f"{avail_row['avail_end']} avail end")
    return "; ".join(notes)


def _simple_reason(reason, day, authorized, absence, availability):
    """One plain-English sentence for the debug CSV `reason` column.

    `authorized` is the weekday set from the day's authorization (empty
    set when there is none), `absence` the Absences row covering the day
    (or None), `availability` the effective HH:MM-HH:MM window ('' when
    none applies)."""
    if reason == REASON_DAY_NOT_ENROLLED:
        return "Not enrolled at the center on this day"
    if reason == REASON_DAY_NO_AUTH:
        return "No authorization covers this day"
    if reason == REASON_DAY_WRONG_WEEKDAY:
        names = ", ".join(DAY_ABBR[d] for d in sorted(authorized))
        detail = (f"authorized: {names}" if names
                  else "no authorized days on file")
        return (f"{DAY_NAME[day.isoweekday()]} is not an authorized day "
                f"({detail})")
    if reason == REASON_DAY_ABSENT:
        leave = str(absence["leave_type"] or "").strip() if absence else ""
        return f"Marked absent ({leave})" if leave else "Marked absent"
    if reason == REASON_DAY_WINDOW_TOO_NARROW:
        if availability:
            return (f"Available time ({availability}) is too short "
                    "to fit a session")
        return "Available time is too short to fit a session"
    return reason


def _simple_conflict_reason(detail):
    """Plain-English sentence for a OneOffConflictDetail."""
    if detail.kind == "duplicate":
        return (f"{len(detail.one_offs)} conflicting one-off availability "
                "entries exist for this day")
    return ("A one-off availability entry conflicts with an absence "
            "on this day")


def build_debug_rows(year, month, ctx, plan_rules,
                     start_day=None, end_day=None, center_id=None):
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
    populated even for REASON_DAY_WINDOW_TOO_NARROW rejections),
    `max_length` (the longest session that fits, HH:MM) and `band`
    ("morning"/"afternoon" on every row when the feature is on and a
    center_id was given; '' otherwise — band is a per-member property).

    `scheduled` is True when compute_day_eligibility accepted the day.
    `reason` is a plain-English sentence: "Scheduled" for accepted days,
    otherwise a one-line explanation of the rejection. A OneOffConflict
    is caught per-day — its simple sentence goes in `reason` and its
    detailed sentence (with the Access row IDs) in `reason_detail` — so
    the CSV always completes even when the schedule build itself fails.
    """
    rows = []
    band = band_for_member(center_id, plan_rules) or ""
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

        conflict_detail = ""
        try:
            result = compute_day_eligibility(day, ctx, plan_rules)
            scheduled = result.eligible
            raw_reason = None if scheduled else (result.reason or "")
            reason = ("Scheduled" if scheduled
                      else _simple_reason(raw_reason, day, authorized,
                                          absence, availability))
            window = result.placement_window
            reserve = result.dropoff_reserve
            pickup_reserve = result.pickup_reserve
        except OneOffConflict as exc:
            scheduled = False
            raw_reason = ""
            reason = _simple_conflict_reason(exc.detail)
            conflict_detail = exc.reason
            window = None
            reserve = 0
            pickup_reserve = 0

        # The placement window actually used: the narrowed window, or
        # the open-day bounds when no availability rule applies.
        if window is None and scheduled:
            window = (
                parse_hhmm(plan_rules["earliest_time_in"]),
                parse_hhmm(plan_rules["latest_time_out"]),
            )
        reason_detail = conflict_detail
        if window is not None:
            in_lo, out_hi = window
            placement = f"{format_minutes(in_lo)}-{format_minutes(out_hi)}"
            max_len = max(0, min(plan_rules["session_length_min"][1],
                                 out_hi - in_lo))
            max_length = format_minutes(max_len)
            reason_detail = _reason_detail(
                raw_reason, availability, reserve, in_lo, out_hi,
                plan_rules, avail_row, pickup_reserve,
            )
        else:
            placement = ""
            max_length = ""

        rows.append({
            "date": day,
            "day": DAY_ABBR[day.isoweekday()],
            "band": band,
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
