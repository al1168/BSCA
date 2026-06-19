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

    `arrival_window` is None when the plan's default applies; a tuple of
    (lo_minutes, hi_minutes) when an Availability rule has narrowed it.
    `reason` is None when eligible=True, otherwise one of the
    REASON_DAY_* constants explaining the rejection (used by the debug
    CSV).
    """
    eligible: bool
    arrival_window: Optional[Tuple[int, int]] = None
    reason: Optional[str] = None


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

    plan_lo = parse_hhmm(plan_rules["arrival_window"][0])
    plan_hi = parse_hhmm(plan_rules["arrival_window"][1])
    avail_lo = parse_hhmm(avail["avail_start"])
    avail_hi = parse_hhmm(avail["avail_end"])
    session_min_lower = plan_rules["session_span_min"][0]

    lo = max(plan_lo, avail_lo)
    hi = min(plan_hi, avail_hi - session_min_lower)
    if lo > hi:
        return DayEligibility(
            eligible=False, reason=REASON_DAY_WINDOW_TOO_NARROW
        )
    return DayEligibility(eligible=True, arrival_window=(lo, hi))


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
