from datetime import date

from monthly_schedule.eligibility_context import MemberContext


def test_is_enrolled_true_open_ended():
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[], absences=[], availabilities=[], one_offs=[],
    )
    assert ctx.is_enrolled(date(2026, 5, 15)) is True


def test_is_enrolled_true_inside_range():
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1),
                      "end_date": date(2026, 12, 31)}],
        authorizations=[], absences=[], availabilities=[], one_offs=[],
    )
    assert ctx.is_enrolled(date(2026, 5, 15)) is True


def test_is_enrolled_false_before_start():
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 6, 1), "end_date": None}],
        authorizations=[], absences=[], availabilities=[], one_offs=[],
    )
    assert ctx.is_enrolled(date(2026, 5, 15)) is False


def test_is_enrolled_false_after_end():
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1),
                      "end_date": date(2026, 4, 30)}],
        authorizations=[], absences=[], availabilities=[], one_offs=[],
    )
    assert ctx.is_enrolled(date(2026, 5, 15)) is False


def test_is_enrolled_returning_member_multiple_rows():
    ctx = MemberContext(
        enrollments=[
            {"id": 1, "center_id": 1,
             "start_date": date(2025, 1, 1), "end_date": date(2025, 6, 30)},
            {"id": 2, "center_id": 1,
             "start_date": date(2026, 1, 1), "end_date": None},
        ],
        authorizations=[], absences=[], availabilities=[], one_offs=[],
    )
    assert ctx.is_enrolled(date(2025, 3, 1)) is True
    assert ctx.is_enrolled(date(2025, 10, 1)) is False  # gap
    assert ctx.is_enrolled(date(2026, 5, 15)) is True


def test_active_authorization_picks_overlapping_row():
    auth_a = {"id": 1, "center_id": 1,
              "auth_start": date(2025, 1, 1), "auth_end": date(2025, 12, 31),
              "effective_start": date(2025, 1, 1),
              "effective_end": date(2025, 12, 31),
              "auth_days": "1,3,5"}
    auth_b = {"id": 2, "center_id": 1,
              "auth_start": date(2026, 1, 1), "auth_end": date(2026, 12, 31),
              "effective_start": date(2026, 1, 1),
              "effective_end": date(2026, 12, 31),
              "auth_days": "2,4"}
    ctx = MemberContext(
        enrollments=[], authorizations=[auth_a, auth_b],
        absences=[], availabilities=[], one_offs=[],
    )
    assert ctx.active_authorization(date(2025, 6, 1)) == auth_a
    assert ctx.active_authorization(date(2026, 6, 1)) == auth_b


def test_active_authorization_most_recent_wins_on_overlap():
    a = {"id": 1, "center_id": 1,
         "auth_start": date(2026, 1, 1), "auth_end": date(2026, 12, 31),
         "effective_start": date(2026, 1, 1),
         "effective_end": date(2026, 12, 31),
         "auth_days": "1,3,5"}
    b = {"id": 2, "center_id": 1,
         "auth_start": date(2026, 7, 1), "auth_end": date(2026, 12, 31),
         "effective_start": date(2026, 7, 1),
         "effective_end": date(2026, 12, 31),
         "auth_days": "2,4"}
    ctx = MemberContext(
        enrollments=[], authorizations=[a, b],
        absences=[], availabilities=[], one_offs=[],
    )
    # July 15 is covered by both; b has the later effective_start → wins
    assert ctx.active_authorization(date(2026, 7, 15)) == b


def test_active_authorization_none_when_no_match():
    ctx = MemberContext(
        enrollments=[], authorizations=[],
        absences=[], availabilities=[], one_offs=[],
    )
    assert ctx.active_authorization(date(2026, 5, 1)) is None


def test_is_absent_inclusive_range():
    ctx = MemberContext(
        enrollments=[], authorizations=[],
        absences=[{"id": 1, "center_id": 1, "leave_type": "Vacation",
                   "start_date": date(2026, 5, 10),
                   "end_date": date(2026, 5, 16)}],
        availabilities=[], one_offs=[],
    )
    assert ctx.is_absent(date(2026, 5, 9)) is False
    assert ctx.is_absent(date(2026, 5, 10)) is True
    assert ctx.is_absent(date(2026, 5, 16)) is True
    assert ctx.is_absent(date(2026, 5, 17)) is False


def test_availability_for_matches_weekday_and_period():
    rule = {"id": 1, "center_id": 1,
            "effective_start_date": date(2026, 1, 1),
            "effective_end_date": None,
            "day_of_week": 2,
            "avail_start": "10:00", "avail_end": "15:00"}
    ctx = MemberContext(
        enrollments=[], authorizations=[], absences=[],
        availabilities=[rule], one_offs=[],
    )
    # 2026-05-05 is a Tuesday (isoweekday 2) → match
    assert ctx.availability_for(date(2026, 5, 5)) == rule
    # 2026-05-06 is a Wednesday → no match (rule is for Tuesday only)
    assert ctx.availability_for(date(2026, 5, 6)) is None


def test_availability_for_most_recent_wins():
    older = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": date(2026, 12, 31),
             "day_of_week": 2,
             "avail_start": "10:00", "avail_end": "15:00"}
    newer = {"id": 2, "center_id": 1,
             "effective_start_date": date(2026, 6, 1),
             "effective_end_date": None,
             "day_of_week": 2,
             "avail_start": "11:00", "avail_end": "14:00"}
    ctx = MemberContext(
        enrollments=[], authorizations=[], absences=[],
        availabilities=[older, newer], one_offs=[],
    )
    # 2026-06-02 is a Tuesday; both match; newer wins
    assert ctx.availability_for(date(2026, 6, 2)) == newer
    # 2026-05-05 is a Tuesday; only older matches
    assert ctx.availability_for(date(2026, 5, 5)) == older


def test_one_offs_for_returns_matching_rows():
    from datetime import date
    from monthly_schedule.eligibility_context import MemberContext

    rows = [
        {"id": 1, "center_id": 1, "date": date(2026, 6, 5),
         "avail_start": "12:00", "avail_end": "16:00"},
        {"id": 2, "center_id": 1, "date": date(2026, 6, 6),
         "avail_start": "09:00", "avail_end": "11:00"},
    ]
    ctx = MemberContext(
        enrollments=[], authorizations=[], absences=[],
        availabilities=[], one_offs=rows,
    )
    assert ctx.one_offs_for(date(2026, 6, 5)) == [rows[0]]
    assert ctx.one_offs_for(date(2026, 6, 6)) == [rows[1]]
    assert ctx.one_offs_for(date(2026, 6, 7)) == []


def test_one_offs_for_returns_all_duplicates():
    from datetime import date
    from monthly_schedule.eligibility_context import MemberContext

    rows = [
        {"id": 1, "center_id": 1, "date": date(2026, 6, 5),
         "avail_start": "12:00", "avail_end": "16:00"},
        {"id": 2, "center_id": 1, "date": date(2026, 6, 5),
         "avail_start": "13:00", "avail_end": "15:00"},
    ]
    ctx = MemberContext(
        enrollments=[], authorizations=[], absences=[],
        availabilities=[], one_offs=rows,
    )
    out = ctx.one_offs_for(date(2026, 6, 5))
    assert len(out) == 2
    assert {r["id"] for r in out} == {1, 2}


def test_one_offs_defaults_to_empty_list_when_none_passed():
    from monthly_schedule.eligibility_context import MemberContext
    ctx = MemberContext(
        enrollments=[], authorizations=[], absences=[],
        availabilities=[], one_offs=[],
    )
    from datetime import date
    assert ctx.one_offs_for(date(2026, 6, 5)) == []
