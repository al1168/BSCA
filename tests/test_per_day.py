from datetime import date

from monthly_schedule.eligibility_context import MemberContext
from monthly_schedule.per_day import (
    DayEligibility,
    compute_day_eligibility,
    compute_month_failure,
)


PLAN_RULES = {
    "earliest_time_in": "08:00",
    "latest_time_out": "16:00",
    "session_length_min": (210, 240),
}


def _ctx(enrolled=True, authorized="1,3,5", absent=False,
        availability=None, one_offs=None):
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
    return MemberContext(
        enrollments, authorizations, absences, availabilities,
        list(one_offs or []),
    )


def test_eligible_day_no_availability_rule():
    # 2026-05-04 is a Monday (isoweekday 1) → in auth_days "1,3,5"
    result = compute_day_eligibility(date(2026, 5, 4), _ctx(), PLAN_RULES)
    assert result.eligible is True
    assert result.placement_window is None


def test_ineligible_not_enrolled():
    from monthly_schedule.per_day import REASON_DAY_NOT_ENROLLED
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(enrolled=False), PLAN_RULES
    )
    assert result.eligible is False
    assert result.reason == REASON_DAY_NOT_ENROLLED


def test_ineligible_no_authorization():
    from monthly_schedule.per_day import REASON_DAY_NO_AUTH
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(authorized=None), PLAN_RULES
    )
    assert result.eligible is False
    assert result.reason == REASON_DAY_NO_AUTH


def test_ineligible_wrong_weekday():
    from monthly_schedule.per_day import REASON_DAY_WRONG_WEEKDAY
    # 2026-05-05 is a Tuesday (isoweekday 2) → NOT in "1,3,5"
    result = compute_day_eligibility(date(2026, 5, 5), _ctx(), PLAN_RULES)
    assert result.eligible is False
    assert result.reason == REASON_DAY_WRONG_WEEKDAY


def test_ineligible_absent():
    from monthly_schedule.per_day import REASON_DAY_ABSENT
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(absent=True), PLAN_RULES
    )
    assert result.eligible is False
    assert result.reason == REASON_DAY_ABSENT


def test_eligible_has_no_reason():
    result = compute_day_eligibility(date(2026, 5, 4), _ctx(), PLAN_RULES)
    assert result.eligible is True
    assert result.reason is None


def test_availability_rule_narrows_window():
    # Day bounds 08:00–16:00; member available 10:00–15:00 on Mondays.
    # Placement window = [max(08:00, 10:00), min(16:00, 15:00)]
    #                  = (600, 900); 5h wide, fits the 3h30m minimum.
    avail = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": None,
             "day_of_week": 1,
             "avail_start": "10:00", "avail_end": "15:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=avail), PLAN_RULES
    )
    assert result.eligible is True
    assert result.placement_window == (600, 900)


def test_availability_window_too_narrow_makes_day_ineligible():
    # Member available only 12:00–13:30 on Monday: window (720, 810) is
    # 90 min, narrower than the 210 min minimum → ineligible.
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


def test_one_off_wins_over_recurring_availability():
    # Recurring availability (Mon 10:00-15:00) would give window (600, 900).
    # A one-off for the same Monday says 12:00-16:00. The one-off must win
    # and the recurring rule must be IGNORED:
    #   window = [max(08:00, 12:00), min(16:00, 16:00)] = (720, 960), 4h.
    avail = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": None,
             "day_of_week": 1,
             "avail_start": "10:00", "avail_end": "15:00"}
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "12:00", "avail_end": "16:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4),
        _ctx(availability=avail, one_offs=[one_off]),
        PLAN_RULES,
    )
    assert result.eligible is True
    assert result.placement_window == (720, 960)


def test_one_off_inside_day_bounds_sets_window():
    # One-off says 09:00-14:00; recurring (Mon 12:00-13:00) is ignored.
    #   window = [max(08:00, 09:00), min(16:00, 14:00)] = (540, 840), 5h.
    narrow_recurring = {"id": 1, "center_id": 1,
                        "effective_start_date": date(2026, 1, 1),
                        "effective_end_date": None,
                        "day_of_week": 1,
                        "avail_start": "12:00", "avail_end": "13:00"}
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "09:00", "avail_end": "14:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4),
        _ctx(availability=narrow_recurring, one_offs=[one_off]),
        PLAN_RULES,
    )
    assert result.eligible is True
    assert result.placement_window == (540, 840)


def test_duplicate_one_off_rows_raise_conflict():
    from monthly_schedule.per_day import OneOffConflict
    one_offs = [
        {"id": 1, "center_id": 1, "date": date(2026, 5, 4),
         "avail_start": "09:00", "avail_end": "12:00"},
        {"id": 2, "center_id": 1, "date": date(2026, 5, 4),
         "avail_start": "10:00", "avail_end": "13:00"},
    ]
    import pytest
    with pytest.raises(OneOffConflict) as info:
        compute_day_eligibility(
            date(2026, 5, 4), _ctx(one_offs=one_offs), PLAN_RULES
        )
    assert info.value.center_id == 1
    assert info.value.day == date(2026, 5, 4)
    assert info.value.reason == "duplicate one-off rows for 2026-05-04"


def test_one_off_with_absence_raises_conflict():
    from monthly_schedule.per_day import OneOffConflict
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "09:00", "avail_end": "12:00"}
    import pytest
    with pytest.raises(OneOffConflict) as info:
        # `absent=True` covers the entire month of May 2026.
        compute_day_eligibility(
            date(2026, 5, 4),
            _ctx(absent=True, one_offs=[one_off]),
            PLAN_RULES,
        )
    assert info.value.reason == "one-off on 2026-05-04 conflicts with absence"


def test_duplicate_one_off_beats_absence_conflict():
    # Two one-offs AND an absence: first-match wins; duplicate is checked first.
    from monthly_schedule.per_day import OneOffConflict
    one_offs = [
        {"id": 1, "center_id": 1, "date": date(2026, 5, 4),
         "avail_start": "09:00", "avail_end": "12:00"},
        {"id": 2, "center_id": 1, "date": date(2026, 5, 4),
         "avail_start": "10:00", "avail_end": "13:00"},
    ]
    import pytest
    with pytest.raises(OneOffConflict) as info:
        compute_day_eligibility(
            date(2026, 5, 4),
            _ctx(absent=True, one_offs=one_offs),
            PLAN_RULES,
        )
    assert info.value.reason == "duplicate one-off rows for 2026-05-04"


def test_one_off_on_unenrolled_day_silently_skipped():
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "12:00", "avail_end": "14:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4),
        _ctx(enrolled=False, one_offs=[one_off]),
        PLAN_RULES,
    )
    assert result.eligible is False  # silent — no raise


def test_one_off_with_no_active_auth_silently_skipped():
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "12:00", "avail_end": "14:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4),
        _ctx(authorized=None, one_offs=[one_off]),
        PLAN_RULES,
    )
    assert result.eligible is False


def test_one_off_on_unauthorized_weekday_silently_skipped():
    # 2026-05-05 is Tuesday (weekday 2); _ctx default auth_days "1,3,5"
    # excludes it. A one-off must not override the weekday gate.
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 5),
               "avail_start": "12:00", "avail_end": "14:00"}
    result = compute_day_eligibility(
        date(2026, 5, 5),
        _ctx(one_offs=[one_off]),
        PLAN_RULES,
    )
    assert result.eligible is False


def test_one_off_window_too_narrow_after_bounds_skipped():
    # Day bounds 08:00-16:00. One-off 14:00-17:00 clips to (840, 960) =
    # 2h, narrower than the 210 min minimum → ineligible, no raise.
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "14:00", "avail_end": "17:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4),
        _ctx(one_offs=[one_off]),
        PLAN_RULES,
    )
    assert result.eligible is False


DEADLINE_RULES = {
    "earliest_time_in": "08:00",
    "latest_time_out": "16:00",
    "session_length_min": (210, 240),
    "time_out_drift_min": (2, 2),
    "dropoff_trail_min": (30, 34),   # travel-adjusted in real runs
    "dropoff_by_avail_end": True,
}

MONDAY_AVAIL_8_TO_15 = {
    "id": 1, "center_id": 1,
    "effective_start_date": date(2026, 1, 1),
    "effective_end_date": None,
    "day_of_week": 1,
    "avail_start": "08:00", "avail_end": "15:00",
}


def test_deadline_shrinks_out_hi_by_reserve():
    # avail_end 15:00 (900) < latest_out 16:00 → reserve = 2 + 34 = 36
    # → out_hi = 900 - 36 = 864 (14:24). Window (480, 864) is 384 min.
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=MONDAY_AVAIL_8_TO_15),
        DEADLINE_RULES,
    )
    assert result.eligible is True
    assert result.placement_window == (480, 864)
    assert result.dropoff_reserve == 36


def test_deadline_off_keeps_legacy_window():
    rules = {**DEADLINE_RULES, "dropoff_by_avail_end": False}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=MONDAY_AVAIL_8_TO_15), rules
    )
    assert result.placement_window == (480, 900)
    assert result.dropoff_reserve == 0


def test_deadline_skipped_when_avail_end_at_day_bound():
    # avail_end == latest_time_out → member has no home care deadline;
    # window unchanged.
    avail = {**MONDAY_AVAIL_8_TO_15, "avail_end": "16:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=avail), DEADLINE_RULES
    )
    assert result.placement_window == (480, 960)
    assert result.dropoff_reserve == 0


def test_deadline_does_not_apply_to_one_off():
    # One-off 08:00-15:00: per the spec, one-offs keep legacy behavior.
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "08:00", "avail_end": "15:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(one_offs=[one_off]), DEADLINE_RULES
    )
    assert result.placement_window == (480, 900)
    assert result.dropoff_reserve == 0


def test_deadline_too_narrow_day_blank_with_numbers():
    # avail 08:00-11:30 (690): out_hi = 690 - 36 = 654 → width 174 < 210
    # → ineligible, but the window/reserve are still reported for debug.
    from monthly_schedule.per_day import REASON_DAY_WINDOW_TOO_NARROW
    avail = {**MONDAY_AVAIL_8_TO_15, "avail_end": "11:30"}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=avail), DEADLINE_RULES
    )
    assert result.eligible is False
    assert result.reason == REASON_DAY_WINDOW_TOO_NARROW
    assert result.placement_window == (480, 654)
    assert result.dropoff_reserve == 36


def test_legacy_too_narrow_also_reports_window():
    # Flag absent (module PLAN_RULES): the too-narrow rejection now
    # carries the window it computed instead of None.
    avail = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": None,
             "day_of_week": 1,
             "avail_start": "12:00", "avail_end": "13:30"}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=avail), PLAN_RULES
    )
    assert result.eligible is False
    assert result.placement_window == (720, 810)
