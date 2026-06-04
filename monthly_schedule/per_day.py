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
    """
    eligible: bool
    arrival_window: Optional[Tuple[int, int]] = None


def compute_day_eligibility(day: date, ctx, plan_rules) -> DayEligibility:
    """Run the ordered eligibility checks for one calendar day."""
    if not ctx.is_enrolled(day):
        return DayEligibility(eligible=False)

    auth = ctx.active_authorization(day)
    if auth is None:
        return DayEligibility(eligible=False)

    authorized = get_authorized_weekdays(auth["auth_days"])
    if day.isoweekday() not in authorized:
        return DayEligibility(eligible=False)

    if ctx.is_absent(day):
        return DayEligibility(eligible=False)

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
        return DayEligibility(eligible=False)
    return DayEligibility(eligible=True, arrival_window=(lo, hi))


def compute_month_failure(year: int, month: int, ctx):
    """Return a whole-member failure reason string for this month, or None
    if the member has at least one eligible day."""
    days = list(get_month_dates(year, month))

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
