"""Per-day eligibility derived from a MemberContext, and the whole-month
failure check used to skip a member entirely from the run summary."""

from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

from monthly_schedule.auth_days import get_authorized_weekdays
from monthly_schedule.month_dates import get_month_dates
from monthly_schedule.rules import parse_hhmm


REASON_NOT_ENROLLED = "not enrolled during this month"
REASON_NO_AUTH = "no active authorization for this month"
REASON_ABSENT_MONTH = "absent for the entire month"

# Per-day rejection reasons surfaced by compute_day_eligibility().
# Stable strings so the debug CSV and i18n table can key off them.
REASON_DAY_NOT_ENROLLED = "not enrolled on this day"
REASON_DAY_NO_AUTH = "no active authorization on this day"
REASON_DAY_WRONG_WEEKDAY = "weekday not in authorized days"
REASON_DAY_ABSENT = "absent on this day"
REASON_DAY_WINDOW_TOO_NARROW = (
    "availability window too narrow for a valid session"
)


class OneOffConflict(Exception):
    """Raised by compute_day_eligibility when a one-off availability row
    exists for a day but conflicts with an absence or a duplicate one-off
    row. The per-member runner catches this to write the conflict CSV."""

    def __init__(self, center_id, day, reason):
        self.center_id = center_id
        self.day = day
        self.reason = reason
        super().__init__(f"{center_id} {day}: {reason}")


@dataclass(frozen=True)
class DayEligibility:
    """Result of a single-day eligibility check.

    `placement_window` is (in_lo, out_hi) in minutes — the earliest
    allowed Time-In and latest allowed Time-Out for the day, after
    intersecting the plan's day bounds with the member's availability
    (and, when `dropoff_by_avail_end` applies, subtracting the
    drop-off reserve). It is None when no availability rule applies
    (the open day: the generator falls back to the plan's full day
    bounds). Unlike before, it IS populated on a too-narrow rejection
    so the debug CSV can show the numbers.
    `reason` is None when eligible=True, otherwise one of the
    REASON_DAY_* constants explaining the rejection (used by the debug
    CSV).
    `dropoff_reserve` is the minutes subtracted from avail_end to keep
    Drop-Off at or before it (max time-out drift + max drop-off
    trail); 0 when the deadline did not apply.
    """
    eligible: bool
    placement_window: Optional[Tuple[int, int]] = None
    reason: Optional[str] = None
    dropoff_reserve: int = 0


def compute_day_eligibility(day: date, ctx, plan_rules) -> DayEligibility:
    """Run the ordered eligibility checks for one calendar day."""
    if not ctx.is_enrolled(day):
        return DayEligibility(eligible=False, reason=REASON_DAY_NOT_ENROLLED)

    auth = ctx.active_authorization(day)
    if auth is None:
        return DayEligibility(eligible=False, reason=REASON_DAY_NO_AUTH)

    authorized = get_authorized_weekdays(auth["auth_days"])
    if day.isoweekday() not in authorized:
        return DayEligibility(eligible=False, reason=REASON_DAY_WRONG_WEEKDAY)

    one_offs = ctx.one_offs_for(day)
    if one_offs:
        center_id = one_offs[0]["center_id"]
        if len(one_offs) > 1:
            raise OneOffConflict(
                center_id, day,
                f"duplicate one-off rows for {day.isoformat()}",
            )
        if ctx.is_absent(day):
            raise OneOffConflict(
                center_id, day,
                f"one-off on {day.isoformat()} conflicts with absence",
            )
        avail = one_offs[0]
    else:
        if ctx.is_absent(day):
            return DayEligibility(eligible=False, reason=REASON_DAY_ABSENT)
        avail = ctx.availability_for(day)
        if avail is None:
            return DayEligibility(eligible=True)

    earliest_in = parse_hhmm(plan_rules["earliest_time_in"])
    latest_out = parse_hhmm(plan_rules["latest_time_out"])
    avail_lo = parse_hhmm(avail["avail_start"])
    avail_hi = parse_hhmm(avail["avail_end"])
    length_min = plan_rules["session_length_min"][0]

    # Placement window: the member's availability clipped to the hard
    # day bounds (Time-In >= earliest, Time-Out <= latest).
    in_lo = max(earliest_in, avail_lo)
    out_hi = min(latest_out, avail_hi)
    # Home-care deadline: recurring availability ending before the day
    # bound means home care starts at avail_end, so the whole transport
    # tail (drift + drive + buffer) must fit before it. Reserving the
    # maximum of each random range guarantees Drop-Off <= avail_end for
    # any draw. One-off rows are exempt (user decision, spec 2026-07-20).
    reserve = 0
    if (plan_rules.get("dropoff_by_avail_end")
            and not one_offs and avail_hi < latest_out):
        reserve = (plan_rules["time_out_drift_min"][1]
                   + plan_rules["dropoff_trail_min"][1])
        out_hi = avail_hi - reserve
    if out_hi - in_lo < length_min:
        return DayEligibility(
            eligible=False, reason=REASON_DAY_WINDOW_TOO_NARROW,
            placement_window=(in_lo, out_hi), dropoff_reserve=reserve,
        )
    return DayEligibility(
        eligible=True, placement_window=(in_lo, out_hi),
        dropoff_reserve=reserve,
    )


def compute_month_failure(year: int, month: int, ctx,
                           start_day=None, end_day=None):
    """Return a whole-member failure reason string for the requested
    range (defaults to the full month), or None if the member has at
    least one eligible day in that range."""
    days = list(get_month_dates(year, month, start_day, end_day))

    if not any(ctx.is_enrolled(d) for d in days):
        return REASON_NOT_ENROLLED
    if not any(ctx.active_authorization(d) is not None for d in days):
        return REASON_NO_AUTH

    # Check whether the absences blanket every authorized day in the month.
    has_authorized_unblocked = False
    for d in days:
        auth = ctx.active_authorization(d)
        if auth is None:
            continue
        if d.isoweekday() not in get_authorized_weekdays(auth["auth_days"]):
            continue
        if ctx.is_absent(d):
            continue
        has_authorized_unblocked = True
        break

    if not has_authorized_unblocked:
        # Distinguish "absent for entire month" from "no authorized days at
        # all this month" (the latter is rare but possible). Both reduce to
        # the same surfaced reason: nothing to schedule.
        return REASON_ABSENT_MONTH

    return None
