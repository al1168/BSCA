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


def _window_ctx(enroll_start, enroll_end, auth_start=date(2026, 1, 1),
                auth_end=date(2026, 12, 31), auth_days="1,2,3,4,5",
                absences=None):
    """MemberContext with explicit enrollment/authorization windows, for
    the month-gate tests that need dates other than _ctx's defaults."""
    return MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": enroll_start, "end_date": enroll_end}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": auth_start, "auth_end": auth_end,
                         "effective_start": auth_start,
                         "effective_end": auth_end,
                         "auth_days": auth_days}],
        absences=list(absences or []),
        availabilities=[],
        one_offs=[],
    )


def test_month_failure_enrollment_starts_after_month():
    # First enrollment starts Nov 1; generating September → no sheet.
    ctx = _window_ctx(date(2026, 11, 1), None)
    from monthly_schedule.per_day import REASON_NOT_ENROLLED
    assert compute_month_failure(2026, 9, ctx) == REASON_NOT_ENROLLED


def test_month_failure_enrollment_ended_before_month():
    ctx = _window_ctx(date(2025, 1, 1), date(2026, 8, 15))
    from monthly_schedule.per_day import REASON_NOT_ENROLLED
    assert compute_month_failure(2026, 9, ctx) == REASON_NOT_ENROLLED


def test_month_failure_none_for_partial_enrollment():
    # Enrolled 9/1–9/15 only → the sheet must still be generated.
    ctx = _window_ctx(date(2026, 9, 1), date(2026, 9, 15))
    assert compute_month_failure(2026, 9, ctx) is None


def test_month_failure_enrolled_days_outside_auth_weekdays():
    # Enrolled only Sat 9/5–Sun 9/6; authorized weekdays are Mon–Fri.
    # No day is both enrolled and authorized → the sheet would be
    # entirely blank, so the member must be skipped.
    ctx = _window_ctx(date(2026, 9, 5), date(2026, 9, 6))
    from monthly_schedule.per_day import REASON_NO_ELIGIBLE_DAYS
    assert compute_month_failure(2026, 9, ctx) == REASON_NO_ELIGIBLE_DAYS


def test_month_failure_enrollment_and_auth_windows_disjoint():
    # Enrolled 9/1–9/10 but the authorization only starts 9/15.
    ctx = _window_ctx(date(2026, 9, 1), date(2026, 9, 10),
                      auth_start=date(2026, 9, 15))
    from monthly_schedule.per_day import REASON_NO_ELIGIBLE_DAYS
    assert compute_month_failure(2026, 9, ctx) == REASON_NO_ELIGIBLE_DAYS


def test_month_failure_absent_on_all_enrolled_authorized_days():
    # Enrolled 9/1–9/15 with an absence blanketing exactly that range:
    # every schedulable day is blocked even though later September days
    # are authorized (but not enrolled) → absent-for-the-month skip.
    absence = [{"id": 1, "center_id": 1, "leave_type": "Vacation",
                "start_date": date(2026, 9, 1),
                "end_date": date(2026, 9, 15)}]
    ctx = _window_ctx(date(2026, 9, 1), date(2026, 9, 15),
                      absences=absence)
    from monthly_schedule.per_day import REASON_ABSENT_MONTH
    assert compute_month_failure(2026, 9, ctx) == REASON_ABSENT_MONTH


def test_one_off_conflict_exception_carries_fields():
    from datetime import date
    from monthly_schedule.per_day import OneOffConflict, OneOffConflictDetail
    exc = OneOffConflict(
        123, date(2026, 6, 5),
        OneOffConflictDetail(
            kind="duplicate", day=date(2026, 6, 5),
            one_offs=(
                {"id": 1, "avail_start": "09:00", "avail_end": "12:00"},
                {"id": 2, "avail_start": "10:00", "avail_end": "13:00"},
            ),
        ),
    )
    assert exc.center_id == 123
    assert exc.day == date(2026, 6, 5)
    assert exc.reason == (
        "2 one-off rows for 2026-06-05: 09:00-12:00 (row 1) "
        "and 10:00-13:00 (row 2)"
    )
    assert "123" in str(exc)
    assert "2026-06-05" in str(exc)
    assert "one-off rows" in str(exc)


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
    assert info.value.reason == (
        "2 one-off rows for 2026-05-04: 09:00-12:00 (row 1) "
        "and 10:00-13:00 (row 2)"
    )


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
    # Names both sides of the contradiction, with the Access row IDs, so
    # staff can open the two rows without hunting for them.
    assert info.value.reason == (
        "one-off availability 09:00-12:00 on 2026-05-04 "
        "(OneOffAvailability row 99) conflicts with a Vacation absence "
        "covering 2026-05-01 to 2026-05-31 (Absences row 1)"
    )


def test_one_off_absence_conflict_without_leave_type():
    """A blank Leave Type must not produce a double space or a dangling
    article — the sentence drops the type instead."""
    from monthly_schedule.per_day import OneOffConflict
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "09:00", "avail_end": "12:00"}
    ctx = _ctx(absent=True, one_offs=[one_off])
    ctx._absences[0]["leave_type"] = ""
    import pytest
    with pytest.raises(OneOffConflict) as info:
        compute_day_eligibility(date(2026, 5, 4), ctx, PLAN_RULES)
    assert info.value.reason == (
        "one-off availability 09:00-12:00 on 2026-05-04 "
        "(OneOffAvailability row 99) conflicts with an absence "
        "covering 2026-05-01 to 2026-05-31 (Absences row 1)"
    )


def test_one_off_absence_conflict_carries_structured_detail():
    """The GUI needs the parts, not the English sentence, so it can build
    the same message in Chinese."""
    from monthly_schedule.per_day import OneOffConflict
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "09:00", "avail_end": "12:00"}
    import pytest
    with pytest.raises(OneOffConflict) as info:
        compute_day_eligibility(
            date(2026, 5, 4),
            _ctx(absent=True, one_offs=[one_off]),
            PLAN_RULES,
        )
    detail = info.value.detail
    assert detail.kind == "absence"
    assert detail.day == date(2026, 5, 4)
    assert detail.one_offs == (
        {"id": 99, "avail_start": "09:00", "avail_end": "12:00"},
    )
    assert detail.absence == {
        "id": 1, "leave_type": "Vacation",
        "start_date": date(2026, 5, 1), "end_date": date(2026, 5, 31),
    }


def test_one_off_conflict_detail_serialises_to_primitives():
    """as_dict() crosses the Qt signal boundary into the GUI thread, so
    every value has to survive as a plain JSON-ish type."""
    from monthly_schedule.per_day import OneOffConflict
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "09:00", "avail_end": "12:00"}
    import pytest
    with pytest.raises(OneOffConflict) as info:
        compute_day_eligibility(
            date(2026, 5, 4),
            _ctx(absent=True, one_offs=[one_off]),
            PLAN_RULES,
        )
    assert info.value.detail.as_dict() == {
        "kind": "absence",
        "day": "2026-05-04",
        "one_offs": [
            {"id": 99, "avail_start": "09:00", "avail_end": "12:00"},
        ],
        "absence": {
            "id": 1, "leave_type": "Vacation",
            "start_date": "2026-05-01", "end_date": "2026-05-31",
        },
    }


def test_duplicate_one_off_detail_lists_every_row():
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
    detail = info.value.detail
    assert detail.kind == "duplicate"
    assert detail.absence is None
    assert [r["id"] for r in detail.one_offs] == [1, 2]


def test_three_duplicate_one_offs_join_with_a_single_and():
    from monthly_schedule.per_day import OneOffConflict
    one_offs = [
        {"id": 1, "center_id": 1, "date": date(2026, 5, 4),
         "avail_start": "09:00", "avail_end": "12:00"},
        {"id": 2, "center_id": 1, "date": date(2026, 5, 4),
         "avail_start": "10:00", "avail_end": "13:00"},
        {"id": 3, "center_id": 1, "date": date(2026, 5, 4),
         "avail_start": "11:00", "avail_end": "14:00"},
    ]
    import pytest
    with pytest.raises(OneOffConflict) as info:
        compute_day_eligibility(
            date(2026, 5, 4), _ctx(one_offs=one_offs), PLAN_RULES
        )
    assert info.value.reason == (
        "3 one-off rows for 2026-05-04: 09:00-12:00 (row 1), "
        "10:00-13:00 (row 2) and 11:00-14:00 (row 3)"
    )


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
    assert info.value.detail.kind == "duplicate"


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


HEAD_RULES = {
    "earliest_time_in": "08:00",
    "latest_time_out": "16:00",
    "session_length_min": (210, 240),
    "time_in_drift_min": (2, 2),
    "pickup_lead_min": (23, 27),     # travel 22 + buffer 1-5
    "time_out_drift_min": (2, 2),
    "dropoff_trail_min": (30, 34),   # travel-adjusted in real runs
    "pickup_by_avail_start": True,
    "dropoff_by_avail_end": True,
}

FRIDAY_AVAIL_12_TO_16 = {
    "id": 1, "center_id": 1,
    "effective_start_date": date(2026, 1, 1),
    "effective_end_date": None,
    "day_of_week": 5,
    "avail_start": "12:00", "avail_end": "16:00",
}

FRIDAY = date(2026, 7, 3)


def test_head_reserve_raises_in_lo():
    # avail_start 12:00 (720) > earliest_in 08:00 → reserve = 2 + 27 =
    # 29 → in_lo = 749 (12:29). avail_end == latest_out → no tail.
    # Width 211 >= 210 → still eligible (the member-25182 case).
    result = compute_day_eligibility(
        FRIDAY, _ctx(availability=FRIDAY_AVAIL_12_TO_16), HEAD_RULES
    )
    assert result.eligible is True
    assert result.placement_window == (749, 960)
    assert result.pickup_reserve == 29
    assert result.dropoff_reserve == 0


def test_head_reserve_off_keeps_legacy_window():
    rules = {**HEAD_RULES, "pickup_by_avail_start": False}
    result = compute_day_eligibility(
        FRIDAY, _ctx(availability=FRIDAY_AVAIL_12_TO_16), rules
    )
    assert result.placement_window == (720, 960)
    assert result.pickup_reserve == 0


def test_head_reserve_skipped_when_avail_start_at_day_bound():
    # avail_start == earliest_time_in → member is free before pickup;
    # in_lo unchanged. Tail reserve still applies (avail_end 15:00).
    avail = {**FRIDAY_AVAIL_12_TO_16,
             "avail_start": "08:00", "avail_end": "15:00"}
    result = compute_day_eligibility(
        FRIDAY, _ctx(availability=avail), HEAD_RULES
    )
    assert result.placement_window == (480, 864)
    assert result.pickup_reserve == 0
    assert result.dropoff_reserve == 36


def test_head_reserve_not_applied_to_one_off():
    # One-off 12:00-16:00: per the spec, one-offs keep legacy behavior.
    one_off = {"id": 99, "center_id": 1, "date": FRIDAY,
               "avail_start": "12:00", "avail_end": "16:00"}
    result = compute_day_eligibility(
        FRIDAY, _ctx(one_offs=[one_off]), HEAD_RULES
    )
    assert result.placement_window == (720, 960)
    assert result.pickup_reserve == 0
    assert result.dropoff_reserve == 0


def test_head_reserve_too_narrow_day_blank_with_numbers():
    # avail 13:00-16:00: in_lo = 780 + 29 = 809 → width 151 < 210 →
    # ineligible, but the window/reserve are still reported for debug.
    from monthly_schedule.per_day import REASON_DAY_WINDOW_TOO_NARROW
    avail = {**FRIDAY_AVAIL_12_TO_16, "avail_start": "13:00"}
    result = compute_day_eligibility(
        FRIDAY, _ctx(availability=avail), HEAD_RULES
    )
    assert result.eligible is False
    assert result.reason == REASON_DAY_WINDOW_TOO_NARROW
    assert result.placement_window == (809, 960)
    assert result.pickup_reserve == 29


def test_both_reserves_combine():
    # avail 09:00-15:00: in_lo = 540 + 29 = 569, out_hi = 900 - 36 =
    # 864. Width 295 → eligible.
    avail = {**FRIDAY_AVAIL_12_TO_16,
             "avail_start": "09:00", "avail_end": "15:00"}
    result = compute_day_eligibility(
        FRIDAY, _ctx(availability=avail), HEAD_RULES
    )
    assert result.eligible is True
    assert result.placement_window == (569, 864)
    assert result.pickup_reserve == 29
    assert result.dropoff_reserve == 36


def test_both_reserves_too_narrow():
    # avail 10:30-14:30: (630+29, 870-36) = (659, 834) → width 175 <
    # 210 → blank, both reserves reported.
    from monthly_schedule.per_day import REASON_DAY_WINDOW_TOO_NARROW
    avail = {**FRIDAY_AVAIL_12_TO_16,
             "avail_start": "10:30", "avail_end": "14:30"}
    result = compute_day_eligibility(
        FRIDAY, _ctx(availability=avail), HEAD_RULES
    )
    assert result.eligible is False
    assert result.reason == REASON_DAY_WINDOW_TOO_NARROW
    assert result.placement_window == (659, 834)
    assert result.pickup_reserve == 29
    assert result.dropoff_reserve == 36


def test_tail_only_sunday_shape_unaffected_by_head_flag():
    # Sunday shape 08:00-12:30: head exempt (start at bound), tail
    # applies → (480, 750-36=714). Width 234 → eligible.
    avail = {**FRIDAY_AVAIL_12_TO_16,
             "avail_start": "08:00", "avail_end": "12:30"}
    result = compute_day_eligibility(
        FRIDAY, _ctx(availability=avail), HEAD_RULES
    )
    assert result.eligible is True
    assert result.placement_window == (480, 714)
    assert result.pickup_reserve == 0
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
