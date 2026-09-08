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
REASON_NO_ELIGIBLE_DAYS = (
    "no day is both enrolled and authorized this month"
)

# Per-day rejection reasons surfaced by compute_day_eligibility().
# Stable strings so the debug CSV and i18n table can key off them.
REASON_DAY_NOT_ENROLLED = "not enrolled on this day"
REASON_DAY_NO_AUTH = "no active authorization on this day"
REASON_DAY_WRONG_WEEKDAY = "weekday not in authorized days"
REASON_DAY_ABSENT = "absent on this day"
REASON_DAY_CENTER_CLOSED = "center closed on this day"
REASON_DAY_WINDOW_TOO_NARROW = (
    "availability window too narrow for a valid session"
)


@dataclass(frozen=True)
class OneOffConflictDetail:
    """The parts of a one-off conflict, kept separate from the English
    sentence so the GUI can render the same facts in another language.

    `kind` is "absence" (a one-off row on a day the member is also marked
    absent) or "duplicate" (two or more one-off rows for the same day).
    `one_offs` holds one entry per offending OneOffAvailability row —
    a single row for "absence", every colliding row for "duplicate".
    `absence` is the conflicting Absences row, or None for "duplicate".
    """
    kind: str
    day: date
    one_offs: tuple
    absence: Optional[dict] = None

    def as_dict(self) -> dict:
        """Same content using only primitives, for handing across the
        worker's Qt signal into the GUI thread."""
        return {
            "kind": self.kind,
            "day": self.day.isoformat(),
            "one_offs": [dict(r) for r in self.one_offs],
            "absence": None if self.absence is None else {
                "id": self.absence["id"],
                "leave_type": self.absence["leave_type"],
                "start_date": self.absence["start_date"].isoformat(),
                "end_date": self.absence["end_date"].isoformat(),
            },
        }


def _one_off_fields(row) -> dict:
    """Trim a OneOffAvailability row to just what a message needs."""
    return {
        "id": row["id"],
        "avail_start": row["avail_start"],
        "avail_end": row["avail_end"],
    }


def _absence_fields(row) -> dict:
    """Trim an Absences row to just what a message needs."""
    return {
        "id": row["id"],
        "leave_type": row["leave_type"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
    }


def _join_series(parts) -> str:
    """'a', 'a and b', 'a, b and c' — no serial comma, matching the rest
    of the user-facing copy."""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def format_one_off_conflict(detail: OneOffConflictDetail) -> str:
    """Render `detail` as the English sentence used by the run summary
    and both CSV reports. Names each offending record and its Access row
    ID so staff can open the exact rows that disagree."""
    if detail.kind == "duplicate":
        rows = _join_series([
            f"{r['avail_start']}-{r['avail_end']} (row {r['id']})"
            for r in detail.one_offs
        ])
        return (
            f"{len(detail.one_offs)} one-off rows for "
            f"{detail.day.isoformat()}: {rows}"
        )
    one_off = detail.one_offs[0]
    absence = detail.absence
    leave_type = str(absence["leave_type"] or "").strip()
    # A blank Leave Type would otherwise read "a  absence".
    kind_phrase = f"a {leave_type} absence" if leave_type else "an absence"
    return (
        f"one-off availability {one_off['avail_start']}-"
        f"{one_off['avail_end']} on {detail.day.isoformat()} "
        f"(OneOffAvailability row {one_off['id']}) conflicts with "
        f"{kind_phrase} covering {absence['start_date'].isoformat()} to "
        f"{absence['end_date'].isoformat()} (Absences row {absence['id']})"
    )


class OneOffConflict(Exception):
    """Raised by compute_day_eligibility when a one-off availability row
    exists for a day but conflicts with an absence or a duplicate one-off
    row. The per-member runner catches this to write the conflict CSV.

    `reason` is the English sentence; `detail` is the same information
    structured, for callers that render it in another language."""

    def __init__(self, center_id, day, detail: OneOffConflictDetail):
        self.center_id = center_id
        self.day = day
        self.detail = detail
        self.reason = format_one_off_conflict(detail)
        super().__init__(f"{center_id} {day}: {self.reason}")


@dataclass(frozen=True)
class DayEligibility:
    """Result of a single-day eligibility check.

    `placement_window` is (in_lo, out_hi) in minutes — the earliest
    allowed Time-In and latest allowed Time-Out for the day, after
    intersecting the plan's day bounds with the member's availability
    (and, when `dropoff_by_avail_end` applies, subtracting the
    drop-off reserve). It is None when no availability rule applies
    (the open day: the generator falls back to the plan's full day
    bounds). It is also populated when `eligible=False` with
    `REASON_DAY_WINDOW_TOO_NARROW`, so the debug CSV can show the
    numbers behind the rejection (note: `out_hi` may be less than
    `in_lo` in that case — consumers must check `eligible` first).
    `reason` is None when eligible=True, otherwise one of the
    REASON_DAY_* constants explaining the rejection (used by the debug
    CSV).
    `dropoff_reserve` is the minutes subtracted from avail_end to keep
    Drop-Off at or before it (max time-out drift + max drop-off
    trail); 0 when the deadline did not apply.
    `pickup_reserve` is the minutes added to avail_start to keep
    Pick-Up at or after it (max time-in drift + max pick-up lead);
    0 when the constraint did not apply.
    """
    eligible: bool
    placement_window: Optional[Tuple[int, int]] = None
    reason: Optional[str] = None
    dropoff_reserve: int = 0
    pickup_reserve: int = 0


def compute_day_eligibility(day: date, ctx, plan_rules, calendar=None) -> DayEligibility:
    """Run the ordered eligibility checks for one calendar day.

    `calendar` (a CenterCalendar) rejects company holidays and closed
    weekdays right after the authorization check; None skips that
    check. The day bounds are read from `plan_rules` as given — callers
    that want per-weekday hours pass `calendar.rules_for(day, rules)`."""
    if not ctx.is_enrolled(day):
        return DayEligibility(eligible=False, reason=REASON_DAY_NOT_ENROLLED)

    auth = ctx.active_authorization(day)
    if auth is None:
        return DayEligibility(eligible=False, reason=REASON_DAY_NO_AUTH)

    if calendar is not None and calendar.is_closed(day):
        return DayEligibility(eligible=False, reason=REASON_DAY_CENTER_CLOSED)

    authorized = get_authorized_weekdays(auth["auth_days"])
    if day.isoweekday() not in authorized:
        return DayEligibility(eligible=False, reason=REASON_DAY_WRONG_WEEKDAY)

    one_offs = ctx.one_offs_for(day)
    if one_offs:
        center_id = one_offs[0]["center_id"]
        if len(one_offs) > 1:
            raise OneOffConflict(
                center_id, day,
                OneOffConflictDetail(
                    kind="duplicate", day=day,
                    one_offs=tuple(_one_off_fields(r) for r in one_offs),
                ),
            )
        absence = ctx.absence_for(day)
        if absence is not None:
            raise OneOffConflict(
                center_id, day,
                OneOffConflictDetail(
                    kind="absence", day=day,
                    one_offs=(_one_off_fields(one_offs[0]),),
                    absence=_absence_fields(absence),
                ),
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
    # Mirror constraint at the head: recurring availability starting
    # after the day bound means the member is busy until avail_start,
    # so the whole transport lead (drift + drive + buffer) must fit
    # after it. Reserving the maximum of each random range guarantees
    # Pick-Up >= avail_start for any draw. One-off rows are exempt.
    head_reserve = 0
    if (plan_rules.get("pickup_by_avail_start")
            and not one_offs and avail_lo > earliest_in):
        head_reserve = (plan_rules["time_in_drift_min"][1]
                        + plan_rules["pickup_lead_min"][1])
        in_lo = avail_lo + head_reserve
    if out_hi - in_lo < length_min:
        return DayEligibility(
            eligible=False, reason=REASON_DAY_WINDOW_TOO_NARROW,
            placement_window=(in_lo, out_hi), dropoff_reserve=reserve,
            pickup_reserve=head_reserve,
        )
    return DayEligibility(
        eligible=True, placement_window=(in_lo, out_hi),
        dropoff_reserve=reserve, pickup_reserve=head_reserve,
    )


def compute_month_failure(year: int, month: int, ctx,
                           start_day=None, end_day=None, calendar=None):
    """Return a whole-member failure reason string for the requested
    range (defaults to the full month), or None if the member has at
    least one eligible day in that range. Days the center is closed
    (per `calendar`) count as unschedulable, like wrong weekdays."""
    days = list(get_month_dates(year, month, start_day, end_day))

    if not any(ctx.is_enrolled(d) for d in days):
        return REASON_NOT_ENROLLED
    if not any(ctx.active_authorization(d) is not None for d in days):
        return REASON_NO_AUTH

    # A day is schedulable only when the member is enrolled AND an
    # authorization covers it AND its weekday is authorized. Track that
    # separately from the absence blanket so a member whose enrolled
    # days never coincide with authorized days (an all-blank sheet) is
    # skipped with its own reason instead of slipping through.
    has_schedulable = False
    has_unblocked = False
    for d in days:
        if not ctx.is_enrolled(d):
            continue
        auth = ctx.active_authorization(d)
        if auth is None:
            continue
        if calendar is not None and calendar.is_closed(d):
            continue
        if d.isoweekday() not in get_authorized_weekdays(auth["auth_days"]):
            continue
        has_schedulable = True
        if ctx.is_absent(d):
            continue
        has_unblocked = True
        break

    if not has_schedulable:
        return REASON_NO_ELIGIBLE_DAYS
    if not has_unblocked:
        return REASON_ABSENT_MONTH

    return None
