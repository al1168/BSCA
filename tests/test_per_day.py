from datetime import date

from monthly_schedule.eligibility_context import MemberContext
from monthly_schedule.per_day import (
    DayEligibility,
    compute_day_eligibility,
    compute_month_failure,
)


PLAN_RULES = {
    "arrival_window": ("08:00", "11:00"),
    "session_span_min": (210, 245),
}


def _ctx(enrolled=True, authorized="1,3,5", absent=False, availability=None):
    enrollments = (
        [{"id": 1, "center_id": 1,
          "start_date": date(2026, 1, 1), "end_date": None}]
        if enrolled else []
    )
    authorizations = (
        [{"id": 1, "center_id": 1,
          "auth_start": date(2026, 1, 1), "auth_end": date(2026, 12, 31),
          "effective_start": date(2026, 1, 1),
          "effective_end": date(2026, 12, 31),
          "auth_days": authorized}]
        if authorized else []
    )
    absences = (
        [{"id": 1, "center_id": 1, "leave_type": "Vacation",
          "start_date": date(2026, 5, 1),
          "end_date": date(2026, 5, 31)}]
        if absent else []
    )
    availabilities = [availability] if availability else []
    return MemberContext(enrollments, authorizations, absences, availabilities, [])


def test_eligible_day_no_availability_rule():
    # 2026-05-04 is a Monday (isoweekday 1) → in auth_days "1,3,5"
    result = compute_day_eligibility(date(2026, 5, 4), _ctx(), PLAN_RULES)
    assert result.eligible is True
    assert result.arrival_window is None


def test_ineligible_not_enrolled():
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(enrolled=False), PLAN_RULES
    )
    assert result.eligible is False


def test_ineligible_no_authorization():
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(authorized=None), PLAN_RULES
    )
    assert result.eligible is False


def test_ineligible_wrong_weekday():
    # 2026-05-05 is a Tuesday (isoweekday 2) → NOT in "1,3,5"
    result = compute_day_eligibility(date(2026, 5, 5), _ctx(), PLAN_RULES)
    assert result.eligible is False


def test_ineligible_absent():
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(absent=True), PLAN_RULES
    )
    assert result.eligible is False


def test_availability_rule_narrows_window():
    # Plan default arrival is 08:00–11:00, session_span_min lower is 210.
    # Member is available 10:00–15:00 on Mondays.
    # Effective arrival window:
    #   lo = max(480 [08:00], 600 [10:00]) = 600
    #   hi = min(660 [11:00], 900 [15:00] - 210) = min(660, 690) = 660
    avail = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": None,
             "day_of_week": 1,
             "avail_start": "10:00", "avail_end": "15:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=avail), PLAN_RULES
    )
    assert result.eligible is True
    assert result.arrival_window == (600, 660)


def test_availability_window_too_narrow_makes_day_ineligible():
    # Member available only 12:00–13:30 on Monday: lo=720, hi=min(660, 810-210)=600;
    # lo > hi → ineligible.
    avail = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": None,
             "day_of_week": 1,
             "avail_start": "12:00", "avail_end": "13:30"}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=avail), PLAN_RULES
    )
    assert result.eligible is False


def test_month_failure_none_when_all_present():
    failure = compute_month_failure(2026, 5, _ctx())
    assert failure is None


def test_month_failure_not_enrolled():
    failure = compute_month_failure(2026, 5, _ctx(enrolled=False))
    from monthly_schedule.per_day import REASON_NOT_ENROLLED
    assert failure == REASON_NOT_ENROLLED


def test_month_failure_no_authorization():
    failure = compute_month_failure(2026, 5, _ctx(authorized=None))
    from monthly_schedule.per_day import REASON_NO_AUTH
    assert failure == REASON_NO_AUTH


def test_month_failure_absent_entire_month():
    # Authorized for Mon/Wed/Fri; absences cover all of May.
    failure = compute_month_failure(2026, 5, _ctx(absent=True))
    from monthly_schedule.per_day import REASON_ABSENT_MONTH
    assert failure == REASON_ABSENT_MONTH


def test_month_failure_partial_absence_is_not_whole_month():
    # Absent for only one day → not a whole-month failure.
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[{"id": 1, "center_id": 1, "leave_type": "Sick",
                   "start_date": date(2026, 5, 4),
                   "end_date": date(2026, 5, 4)}],
        availabilities=[],
        one_offs=[],
    )
    assert compute_month_failure(2026, 5, ctx) is None


def test_one_off_conflict_exception_carries_fields():
    from datetime import date
    from monthly_schedule.per_day import OneOffConflict
    exc = OneOffConflict(123, date(2026, 6, 5), "duplicate one-off rows for 2026-06-05")
    assert exc.center_id == 123
    assert exc.day == date(2026, 6, 5)
    assert exc.reason == "duplicate one-off rows for 2026-06-05"
    assert "123" in str(exc)
    assert "2026-06-05" in str(exc)
    assert "duplicate" in str(exc)
