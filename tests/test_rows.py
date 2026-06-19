import random
from datetime import date

from monthly_schedule.eligibility_context import MemberContext
from monthly_schedule.rows import build_rows, build_debug_rows
from monthly_schedule.per_day import (
    REASON_DAY_ABSENT,
    REASON_DAY_WINDOW_TOO_NARROW,
)


PLAN_RULES = {
    "arrival_window": ("08:00", "11:00"),
    "session_span_min": (210, 245),
    "pickup_lead_min": (8, 12),
    "dropoff_trail_min": (8, 12),
    "time_in_drift_min": (2, 2),
    "time_out_drift_min": (2, 2),
    "round_to_minutes": 1,
    "travel_buffer_min": (1, 5),
}


def _ctx_full_month(authorized="1,3,5"):
    return MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": authorized}],
        absences=[],
        availabilities=[],
        one_offs=[],
    )


def test_build_rows_one_row_per_day():
    rows = build_rows(2026, 5, _ctx_full_month(), PLAN_RULES, random.Random(0))
    assert len(rows) == 31


def test_build_rows_row_shape():
    rows = build_rows(2026, 5, _ctx_full_month(), PLAN_RULES, random.Random(0))
    keys = set(rows[0].keys())
    assert keys == {"date", "day", "pickup", "arrival",
                    "time_in", "time_out", "departure", "dropoff"}


def test_unauthorized_days_have_blank_times():
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"),
                      PLAN_RULES, random.Random(0))
    # 2026-05-02 is Saturday (isoweekday 6) → not in "1,3,5"
    sat = next(r for r in rows if r["date"] == date(2026, 5, 2))
    assert sat["pickup"] == "" and sat["arrival"] == ""


def test_authorized_days_have_times():
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"),
                      PLAN_RULES, random.Random(0))
    # 2026-05-04 is Monday (isoweekday 1) → in "1,3,5"
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["pickup"] != "" and mon["arrival"] != ""


def test_absence_blocks_an_authorized_day():
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[{"id": 1, "center_id": 1, "leave_type": "Vacation",
                   "start_date": date(2026, 5, 4),
                   "end_date": date(2026, 5, 4)}],
        availabilities=[],
        one_offs=[],
    )
    rows = build_rows(2026, 5, ctx, PLAN_RULES, random.Random(0))
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["pickup"] == ""  # blocked by absence


def test_availability_window_honored():
    avail = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": None,
             "day_of_week": 1,
             "avail_start": "10:00", "avail_end": "15:00"}
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[],
        availabilities=[avail],
        one_offs=[],
    )
    rows = build_rows(2026, 5, ctx, PLAN_RULES, random.Random(0))
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    # Plan default arrival is 08:00–11:00; member is available 10:00 onwards,
    # so the effective arrival window narrows to 10:00–11:00 (600–660 min).
    h, m = mon["arrival"].split(":")
    arrival_min = int(h) * 60 + int(m)
    assert 600 <= arrival_min <= 660


def test_debug_rows_only_authorized_weekdays():
    # auth_days "1,3,5" → Mon/Wed/Fri only. May 2026 has 13 such days.
    rows = build_debug_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES)
    assert len(rows) == 13
    days = {r["day"] for r in rows}
    assert days == {"Mon", "Wed", "Fri"}
    # All days scheduled, no rejection reason.
    assert all(r["scheduled"] is True for r in rows)
    assert all(r["reason"] == "" for r in rows)


def test_debug_rows_records_absence_reason():
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[{"id": 1, "center_id": 1, "leave_type": "Vacation",
                   "start_date": date(2026, 5, 4),
                   "end_date": date(2026, 5, 4)}],
        availabilities=[],
        one_offs=[],
    )
    rows = build_debug_rows(2026, 5, ctx, PLAN_RULES)
    monday = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert monday["scheduled"] is False
    assert monday["reason"] == REASON_DAY_ABSENT


def test_debug_rows_records_window_too_narrow():
    # Plan arrival 08:00-11:00, session_span lower 210. A 12:00-13:30
    # availability gives lo=720, hi=min(660, 810-210)=600 → ineligible.
    avail = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": None,
             "day_of_week": 1,
             "avail_start": "12:00", "avail_end": "13:30"}
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[],
        availabilities=[avail],
        one_offs=[],
    )
    rows = build_debug_rows(2026, 5, ctx, PLAN_RULES)
    monday = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert monday["scheduled"] is False
    assert monday["reason"] == REASON_DAY_WINDOW_TOO_NARROW


def test_debug_rows_catches_one_off_conflict():
    # Duplicate one-offs would normally raise; debug rows catches per-day
    # so the CSV always completes.
    one_offs = [
        {"id": 1, "center_id": 1, "date": date(2026, 5, 4),
         "avail_start": "09:00", "avail_end": "12:00"},
        {"id": 2, "center_id": 1, "date": date(2026, 5, 4),
         "avail_start": "10:00", "avail_end": "13:00"},
    ]
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[],
        availabilities=[],
        one_offs=one_offs,
    )
    rows = build_debug_rows(2026, 5, ctx, PLAN_RULES)
    monday = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert monday["scheduled"] is False
    assert "duplicate one-off rows" in monday["reason"]
