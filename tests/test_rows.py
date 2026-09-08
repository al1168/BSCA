import random
from datetime import date

from monthly_schedule.eligibility_context import MemberContext
from monthly_schedule.center_calendar import CenterCalendar
from monthly_schedule.rows import build_rows, build_debug_rows, TIME_KEYS
from monthly_schedule.rules import parse_hhmm, format_minutes


PLAN_RULES = {
    "earliest_time_in": "08:00",
    "latest_time_out": "16:00",
    "session_length_min": (210, 240),
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


def _to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def test_build_rows_caps_session_to_availability():
    # Member available only 08:00-11:40 (3h40m) on Mon/Wed/Fri. Every
    # scheduled day's attendance block (Time-In..Time-Out) must end by
    # 11:40 and run 3h30m-3h40m — fitting the free time, not the plan max.
    avail = [
        {"id": d, "center_id": 1,
         "effective_start_date": date(2026, 1, 1),
         "effective_end_date": None,
         "day_of_week": d, "avail_start": "08:00", "avail_end": "11:40"}
        for d in (1, 3, 5)
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
        absences=[], availabilities=avail, one_offs=[],
    )
    rows = build_rows(2026, 5, ctx, PLAN_RULES, random.Random(0))
    scheduled = [r for r in rows if r["arrival"]]
    assert scheduled  # sanity: some days were scheduled
    for r in scheduled:
        ti = _to_min(r["time_in"])
        to = _to_min(r["time_out"])
        assert ti >= _to_min("08:00")
        assert to <= _to_min("11:40")
        assert 210 <= to - ti <= 220


def test_build_rows_one_row_per_day():
    rows = build_rows(2026, 5, _ctx_full_month(), PLAN_RULES, random.Random(0))
    assert len(rows) == 31


def test_build_rows_row_shape():
    rows = build_rows(2026, 5, _ctx_full_month(), PLAN_RULES, random.Random(0))
    keys = set(rows[0].keys())
    assert keys == {"date", "day", "pickup", "arrival",
                    "time_in", "time_out", "departure", "dropoff", "status"}


def test_build_rows_status_attended():
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"),
                      PLAN_RULES, random.Random(0))
    # 2026-05-04 is Monday → scheduled.
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["status"] == "attended"


def test_build_rows_status_ineligible():
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"),
                      PLAN_RULES, random.Random(0))
    # 2026-05-02 is Saturday → not authorized.
    sat = next(r for r in rows if r["date"] == date(2026, 5, 2))
    assert sat["status"] == "ineligible"


def test_build_rows_status_absent():
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
    assert mon["status"] == "absent"


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
    # Member available 10:00–15:00, so the attendance block must sit
    # inside that window: Time-In >= 10:00 and Time-Out <= 15:00.
    assert _to_min(mon["time_in"]) >= _to_min("10:00")
    assert _to_min(mon["time_out"]) <= _to_min("15:00")


def test_debug_rows_cover_every_day_of_month():
    # Every calendar day of May 2026 gets a row, weekends included.
    rows = build_debug_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES)
    assert len(rows) == 31
    # Authorized weekdays (Mon/Wed/Fri) are scheduled.
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["scheduled"] is True
    assert mon["reason"] == "Scheduled"
    # 2026-05-02 is a Saturday → plain sentence naming the day and the
    # authorized days.
    sat = next(r for r in rows if r["date"] == date(2026, 5, 2))
    assert sat["scheduled"] is False
    assert sat["reason"] == (
        "Saturday is not an authorized day (authorized: Mon, Wed, Fri)"
    )
    assert sat["auth_days"] == "1,3,5"


def test_debug_rows_no_auth_day_sentence():
    # Authorization ends 2026-05-15 → later days have no authorization.
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 5, 15),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 5, 15),
                         "auth_days": "1,3,5"}],
        absences=[], availabilities=[], one_offs=[],
    )
    rows = build_debug_rows(2026, 5, ctx, PLAN_RULES)
    assert len(rows) == 31
    # 2026-05-18 is a Monday after the authorization ended.
    mon = next(r for r in rows if r["date"] == date(2026, 5, 18))
    assert mon["scheduled"] is False
    assert mon["reason"] == "No authorization covers this day"
    assert mon["auth_days"] == ""


def test_debug_rows_not_enrolled_day_sentence():
    # Enrollment starts mid-month → earlier days are not enrolled.
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 5, 15), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[], availabilities=[], one_offs=[],
    )
    rows = build_debug_rows(2026, 5, ctx, PLAN_RULES)
    # 2026-05-04 is a Monday before enrollment started.
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["scheduled"] is False
    assert mon["reason"] == "Not enrolled at the center on this day"


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
    assert monday["reason"] == "Marked absent (Vacation)"
    assert monday["absent"] == "yes (Vacation)"


def test_debug_rows_carry_diagnostic_fields():
    # Recurring availability 08:00-11:40 on Mon/Wed/Fri, no absence.
    avail = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": None,
             "day_of_week": 1,
             "avail_start": "08:00", "avail_end": "11:40"}
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
    assert monday["availability"] == "08:00-11:40"
    assert monday["availability_source"] == "recurring"
    assert monday["absent"] == "no"
    assert monday["auth_days"] == "1,3,5"
    assert monday["placement_window"] == "08:00-11:40"
    assert monday["max_length"] == "03:40"   # min(4h00, 3h40 of free time)


def test_debug_rows_show_one_off_availability_source():
    one_off = {"id": 9, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "09:00", "avail_end": "14:00"}
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
        one_offs=[one_off],
    )
    rows = build_debug_rows(2026, 5, ctx, PLAN_RULES)
    monday = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert monday["availability"] == "09:00-14:00"
    assert monday["availability_source"] == "one-off"
    assert monday["placement_window"] == "09:00-14:00"


def test_debug_rows_records_window_too_narrow():
    # A 12:00-13:30 availability clips to window (720, 810) = 90 min,
    # narrower than the 210 min minimum → ineligible.
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
    assert monday["reason"] == (
        "Available time (12:00-13:30) is too short to fit a session"
    )


def test_build_rows_uses_time_cache_when_hit(monkeypatch):
    """A cache hit short-circuits build_daily_schedule and reuses the
    cached times verbatim — this is the idempotency property that lets
    a partial-month rerun produce the same printed times."""
    from monthly_schedule import rows as rows_mod

    # Pre-seed: every Monday in May 2026 has the same fixed times.
    fixed = {
        "pickup": "08:32", "arrival": "08:45", "time_in": "08:47",
        "time_out": "12:47", "departure": "12:49", "dropoff": "13:02",
    }
    time_cache = {"members": {"1": {}}}
    from monthly_schedule.time_cache import store_times
    for day in (4, 11, 18, 25):
        store_times(
            time_cache, 1, date(2026, 5, day), fixed, "HOF", 7,
        )

    # If build_daily_schedule is invoked on a cached Monday, that's a
    # bug — fail loudly.
    def boom(*a, **k):
        raise AssertionError(
            "build_daily_schedule should not run on cached days"
        )
    monkeypatch.setattr(rows_mod, "build_daily_schedule", boom)

    out = rows_mod.build_rows(
        2026, 5, _ctx_full_month("1"), PLAN_RULES, random.Random(0),
        time_cache=time_cache, center_id=1, plan="HOF", travel_minutes=7,
    )
    mondays = [r for r in out if r["day"] == "Mon"]
    assert len(mondays) == 4
    for row in mondays:
        for k, v in fixed.items():
            assert row[k] == v


def test_build_rows_stores_into_time_cache_on_miss():
    """A cache miss generates fresh times AND writes them into the
    cache so a subsequent run reuses them."""
    from monthly_schedule.time_cache import lookup_times
    time_cache = {}
    rows = build_rows(
        2026, 5, _ctx_full_month("1"), PLAN_RULES, random.Random(0),
        time_cache=time_cache, center_id=1, plan="HOF", travel_minutes=7,
    )
    monday = next(r for r in rows if r["date"] == date(2026, 5, 4))
    hit = lookup_times(
        time_cache, 1, date(2026, 5, 4), "HOF", 7,
        (480, 960),
    )
    assert hit is not None
    assert hit["arrival"] == monday["arrival"]
    assert hit["pickup"] == monday["pickup"]


def test_cached_times_survive_band_toggle():
    """Turning the band feature on must NOT invalidate or reshuffle
    already-cached (printed) days, even when the cached times sit
    outside the member's new band."""
    from monthly_schedule.time_cache import store_times, lookup_times

    # Pre-feature cached entry with an early-afternoon Time-In (12:02) —
    # outside the morning band the feature will assign this member.
    fixed = {
        "pickup": "11:47", "arrival": "12:00", "time_in": "12:02",
        "time_out": "15:32", "departure": "15:34", "dropoff": "15:44",
    }
    time_cache = {}
    for day in (4, 11, 18, 25):
        store_times(time_cache, 1, date(2026, 5, day), fixed, "HOF", 7)

    rules = {**BAND_PLAN_RULES}  # percent 100 -> member is "morning"
    out = build_rows(
        2026, 5, _ctx_full_month("1"), rules, random.Random(0),
        time_cache=time_cache, center_id=1, plan="HOF", travel_minutes=7,
    )
    mondays = [r for r in out if r["day"] == "Mon"]
    assert len(mondays) == 4
    for row in mondays:
        assert row["time_in"] == "12:02"     # cached value, not re-rolled
    # Entries still present in the cache afterwards.
    for day in (4, 11, 18, 25):
        assert lookup_times(time_cache, 1, date(2026, 5, day),
                            "HOF", 7, (480, 960)) is not None


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
    assert monday["reason"] == (
        "2 conflicting one-off availability entries exist for this day"
    )
    assert monday["reason_detail"] == (
        "2 one-off rows for 2026-05-04: 09:00-12:00 (row 1) "
        "and 10:00-13:00 (row 2)"
    )


def test_debug_rows_one_off_absence_conflict_sentence():
    one_off = {"id": 4, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "09:00", "avail_end": "12:00"}
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[{"id": 14, "center_id": 1, "leave_type": "Hospital",
                   "start_date": date(2026, 5, 4),
                   "end_date": date(2026, 5, 8)}],
        availabilities=[],
        one_offs=[one_off],
    )
    rows = build_debug_rows(2026, 5, ctx, PLAN_RULES)
    monday = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert monday["scheduled"] is False
    assert monday["reason"] == (
        "A one-off availability entry conflicts with an absence on this day"
    )
    # The detailed sentence (with the Access row IDs) is preserved.
    assert "OneOffAvailability row 4" in monday["reason_detail"]
    assert "Absences row 14" in monday["reason_detail"]


# Shared by the deadline property test below and the debug-detail tests (Task 4).
DEADLINE_E2E_RULES = {
    "earliest_time_in": "08:00",
    "latest_time_out": "16:00",
    "session_length_min": (210, 240),
    "pickup_lead_min": (26, 30),      # travel 25 + buffer 1-5
    "dropoff_trail_min": (26, 30),
    "time_in_drift_min": (2, 2),
    "time_out_drift_min": (2, 2),
    "round_to_minutes": 1,
    "dropoff_by_avail_end": True,
}


def _deadline_ctx():
    return MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1"}],
        absences=[],
        availabilities=[{"id": 1, "center_id": 1,
                         "effective_start_date": date(2026, 1, 1),
                         "effective_end_date": None,
                         "day_of_week": 1,
                         "avail_start": "08:00", "avail_end": "15:00"}],
        one_offs=[],
    )


def test_dropoff_never_past_avail_end_across_seeds():
    # The guarantee the whole feature rests on: for ANY random draw,
    # Drop-Off <= avail_end on recurring-availability days.
    # parse_hhmm (production parser) on purpose: this is an end-to-end fence.
    deadline = parse_hhmm("15:00")
    ctx = _deadline_ctx()
    for seed in range(50):
        rows = build_rows(2026, 5, ctx, DEADLINE_E2E_RULES,
                          random.Random(seed))
        scheduled = [r for r in rows if r["dropoff"]]
        assert scheduled, "expected Mondays to be scheduled"
        for r in scheduled:
            dropoff_min = parse_hhmm(r["dropoff"])
            assert dropoff_min <= deadline, (
                f"seed {seed} {r['date']}: dropoff {r['dropoff']} "
                f"past {format_minutes(deadline)}"
            )
            # Full session still granted when the window allows it.
            length = parse_hhmm(r["time_out"]) - parse_hhmm(r["time_in"])
            assert 210 <= length <= 240, (
                f"seed {seed} {r['date']}: session {length}m outside 210-240"
            )


HEAD_E2E_RULES = {
    **DEADLINE_E2E_RULES,
    "pickup_lead_min": (23, 27),      # travel 22 + buffer 1-5
    "pickup_by_avail_start": True,
}


def _avail_ctx(avail_start, avail_end):
    return MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1"}],
        absences=[],
        availabilities=[{"id": 1, "center_id": 1,
                         "effective_start_date": date(2026, 1, 1),
                         "effective_end_date": None,
                         "day_of_week": 1,
                         "avail_start": avail_start,
                         "avail_end": avail_end}],
        one_offs=[],
    )


def test_pickup_never_before_avail_start_across_seeds():
    # The guarantee the head reserve rests on: for ANY random draw,
    # Pick-Up >= avail_start on recurring-availability days.
    start = parse_hhmm("12:00")
    ctx = _avail_ctx("12:00", "16:00")
    for seed in range(50):
        rows = build_rows(2026, 5, ctx, HEAD_E2E_RULES,
                          random.Random(seed))
        scheduled = [r for r in rows if r["pickup"]]
        assert scheduled, "expected Mondays to be scheduled"
        for r in scheduled:
            pickup_min = parse_hhmm(r["pickup"])
            assert pickup_min >= start, (
                f"seed {seed} {r['date']}: pickup {r['pickup']} "
                f"before {format_minutes(start)}"
            )
            length = parse_hhmm(r["time_out"]) - parse_hhmm(r["time_in"])
            assert 210 <= length <= 240, (
                f"seed {seed} {r['date']}: session {length}m outside 210-240"
            )


def test_pickup_and_dropoff_both_bounded_across_seeds():
    # Both reserves at once: pickup >= 09:00 AND dropoff <= 15:00.
    start = parse_hhmm("09:00")
    end = parse_hhmm("15:00")
    ctx = _avail_ctx("09:00", "15:00")
    for seed in range(50):
        rows = build_rows(2026, 5, ctx, HEAD_E2E_RULES,
                          random.Random(seed))
        scheduled = [r for r in rows if r["pickup"]]
        assert scheduled, "expected Mondays to be scheduled"
        for r in scheduled:
            assert parse_hhmm(r["pickup"]) >= start, (
                f"seed {seed} {r['date']}: pickup {r['pickup']} before 09:00"
            )
            assert parse_hhmm(r["dropoff"]) <= end, (
                f"seed {seed} {r['date']}: dropoff {r['dropoff']} past 15:00"
            )


def test_pickup_flag_off_allows_early_pickup():
    # With the flag off, some draw lands Pick-Up before avail_start —
    # proving the flag (not luck) provides the guarantee above.
    rules = {**HEAD_E2E_RULES, "pickup_by_avail_start": False}
    start = parse_hhmm("12:00")
    ctx = _avail_ctx("12:00", "16:00")
    early = False
    for seed in range(50):
        rows = build_rows(2026, 5, ctx, rules, random.Random(seed))
        if any(r["pickup"] and parse_hhmm(r["pickup"]) < start
               for r in rows):
            early = True
            break
    assert early, "expected at least one pickup before 12:00 with flag off"


def _first_monday(rows):
    # 2026-05-04 is the first Monday of May 2026 — the first authorized
    # day in the auth_days "1" contexts these tests use.
    return next(r for r in rows if r["date"] == date(2026, 5, 4))


def test_debug_too_narrow_day_has_window_and_detail():
    # avail 08:00-11:30, reserve 2+34=36 → usable 08:00-10:54 (2h54m),
    # under the 3h30m minimum.
    rules = {**DEADLINE_E2E_RULES,
             "dropoff_trail_min": (30, 34)}
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1"}],
        absences=[],
        availabilities=[{"id": 1, "center_id": 1,
                         "effective_start_date": date(2026, 1, 1),
                         "effective_end_date": None,
                         "day_of_week": 1,
                         "avail_start": "08:00", "avail_end": "11:30"}],
        one_offs=[],
    )
    rows = build_debug_rows(2026, 5, ctx, rules)
    row = _first_monday(rows)
    assert row["scheduled"] is False
    assert row["placement_window"] == "08:00-10:54"
    assert row["max_length"] == "02:54"
    assert row["reason_detail"] == (
        "avail 08:00-11:30 minus 36m drop-off reserve -> "
        "usable 08:00-10:54 (2h54m) < min 3h30m"
    )


def test_debug_eligible_day_notes_reserve():
    rules = {**DEADLINE_E2E_RULES, "dropoff_trail_min": (30, 34)}
    ctx = _deadline_ctx()  # avail 08:00-15:00 → reserve 36, eligible
    rows = build_debug_rows(2026, 5, ctx, rules)
    row = _first_monday(rows)
    assert row["scheduled"] is True
    assert row["placement_window"] == "08:00-14:24"
    assert row["reason_detail"] == (
        "drop-off reserve 36m before 15:00 avail end"
    )


def test_debug_too_narrow_day_has_pickup_reserve_detail():
    # avail 13:00-16:00, reserve 2+27=29 → usable 13:29-16:00 (2h31m),
    # under the 3h30m minimum.
    rows = build_debug_rows(2026, 5, _avail_ctx("13:00", "16:00"),
                            HEAD_E2E_RULES)
    row = _first_monday(rows)
    assert row["scheduled"] is False
    assert row["placement_window"] == "13:29-16:00"
    assert row["reason_detail"] == (
        "avail 13:00-16:00 minus 29m pick-up reserve -> "
        "usable 13:29-16:00 (2h31m) < min 3h30m"
    )


def test_debug_eligible_day_notes_pickup_reserve():
    rows = build_debug_rows(2026, 5, _avail_ctx("12:00", "16:00"),
                            HEAD_E2E_RULES)
    row = _first_monday(rows)
    assert row["scheduled"] is True
    assert row["placement_window"] == "12:29-16:00"
    assert row["reason_detail"] == (
        "pick-up reserve 29m after 12:00 avail start"
    )


def test_debug_eligible_day_notes_both_reserves():
    # avail 09:00-15:00: head 29, tail 2+30=32 → window 09:29-14:28.
    rows = build_debug_rows(2026, 5, _avail_ctx("09:00", "15:00"),
                            HEAD_E2E_RULES)
    row = _first_monday(rows)
    assert row["scheduled"] is True
    assert row["placement_window"] == "09:29-14:28"
    assert row["reason_detail"] == (
        "pick-up reserve 29m after 09:00 avail start; "
        "drop-off reserve 32m before 15:00 avail end"
    )


def test_debug_too_narrow_day_lists_both_reserves():
    # avail 10:30-14:30: (630+29, 870-32) = 10:59-13:58 → 2h59m < min.
    rows = build_debug_rows(2026, 5, _avail_ctx("10:30", "14:30"),
                            HEAD_E2E_RULES)
    row = _first_monday(rows)
    assert row["scheduled"] is False
    assert row["placement_window"] == "10:59-13:58"
    assert row["reason_detail"] == (
        "avail 10:30-14:30 minus 29m pick-up reserve and "
        "32m drop-off reserve -> usable 10:59-13:58 (2h59m) < min 3h30m"
    )


def test_debug_too_narrow_without_deadline_shows_width():
    # Legacy narrow window (12:00-13:30, no deadline): detail carries
    # the arithmetic that used to be invisible.
    rules = {**DEADLINE_E2E_RULES, "dropoff_by_avail_end": False}
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1"}],
        absences=[],
        availabilities=[{"id": 1, "center_id": 1,
                         "effective_start_date": date(2026, 1, 1),
                         "effective_end_date": None,
                         "day_of_week": 1,
                         "avail_start": "12:00", "avail_end": "13:30"}],
        one_offs=[],
    )
    rows = build_debug_rows(2026, 5, ctx, rules)
    row = _first_monday(rows)
    assert row["scheduled"] is False
    assert row["placement_window"] == "12:00-13:30"
    assert row["reason_detail"] == "usable 12:00-13:30 (1h30m) < min 3h30m"


def test_debug_open_day_has_empty_detail():
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1"}],
        absences=[], availabilities=[], one_offs=[],
    )
    rows = build_debug_rows(2026, 5, ctx, DEADLINE_E2E_RULES)
    row = _first_monday(rows)
    assert row["scheduled"] is True
    assert row["reason_detail"] == ""


# Band feature on; percent 100 -> every hashed member is morning.
BAND_PLAN_RULES = {**PLAN_RULES,
                   "band_enabled": True,
                   "morning_percent": 100,
                   "morning_window_min": 180,
                   "morning_members": (),
                   "afternoon_members": ()}


def test_build_rows_applies_member_band():
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"), BAND_PLAN_RULES,
                      random.Random(0), center_id=1)
    scheduled = [r for r in rows if r["time_in"]]
    assert scheduled
    for r in scheduled:
        assert _to_min(r["time_in"]) <= 11 * 60   # 08:00 + 3h cutoff


def test_build_rows_honors_afternoon_pin():
    rules = {**BAND_PLAN_RULES, "afternoon_members": (1,)}
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"), rules,
                      random.Random(0), center_id=1)
    scheduled = [r for r in rows if r["time_in"]]
    assert scheduled
    for r in scheduled:
        assert _to_min(r["time_in"]) >= 11 * 60


def test_build_rows_band_never_blocks_narrow_availability():
    # Afternoon-pinned member available only 08:00-11:40: every day must
    # still be scheduled (validity first), inside the availability.
    avail = [
        {"id": d, "center_id": 1,
         "effective_start_date": date(2026, 1, 1),
         "effective_end_date": None,
         "day_of_week": d, "avail_start": "08:00", "avail_end": "11:40"}
        for d in (1, 3, 5)
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
        absences=[], availabilities=avail, one_offs=[],
    )
    rules = {**BAND_PLAN_RULES, "afternoon_members": (1,)}
    rows = build_rows(2026, 5, ctx, rules, random.Random(0), center_id=1)
    scheduled = [r for r in rows if r["time_in"]]
    assert len(scheduled) == 13          # same Mon/Wed/Fri count as unbanded
    for r in scheduled:
        assert _to_min(r["time_in"]) >= _to_min("08:00")
        assert _to_min(r["time_out"]) <= _to_min("11:40")


def test_build_rows_legacy_rules_without_band_keys_still_work():
    rows = build_rows(2026, 5, _ctx_full_month(), PLAN_RULES,
                      random.Random(0), center_id=1)
    assert len(rows) == 31


def test_debug_rows_have_band_column():
    rows = build_debug_rows(2026, 5, _ctx_full_month("1"),
                            BAND_PLAN_RULES, center_id=1)
    assert rows
    assert all(r["band"] == "morning" for r in rows)


def test_debug_rows_band_blank_without_center_id():
    rows = build_debug_rows(2026, 5, _ctx_full_month("1"), PLAN_RULES)
    assert rows
    assert all(r["band"] == "" for r in rows)


def _calendar(open_days=(1, 2, 3, 4, 5, 6, 7), holidays=(),
              opening="08:00", closing="16:00"):
    return CenterCalendar(
        [{"id": i + 1, "name": name, "date": day}
         for i, (name, day) in enumerate(holidays)],
        [{"id": d, "day_name": "", "day_of_week": d,
          "opening_time": opening, "closing_time": closing}
         for d in open_days],
    )


def test_build_rows_holiday_is_blank_and_ineligible():
    cal = _calendar(holidays=[("Test Holiday", date(2026, 5, 4))])
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES,
                      random.Random(0), calendar=cal)
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["status"] == "ineligible"
    assert all(mon[k] == "" for k in TIME_KEYS)
    wed = next(r for r in rows if r["date"] == date(2026, 5, 6))
    assert wed["status"] == "attended"


def test_build_rows_closed_weekday_is_blank():
    cal = _calendar(open_days=(2, 4))               # Tue/Thu only
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES,
                      random.Random(0), calendar=cal)
    assert all(r["status"] == "ineligible" for r in rows)


def test_build_rows_uses_weekday_opening_and_closing():
    cal = _calendar(opening="09:30", closing="15:00")
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES,
                      random.Random(1), calendar=cal)
    attended = [r for r in rows if r["status"] == "attended"]
    assert attended
    for r in attended:
        assert _to_min(r["time_in"]) >= _to_min("09:30")
        assert _to_min(r["time_out"]) <= _to_min("15:00")


def test_build_rows_cache_regenerates_when_hours_change():
    """A cached day generated under 08:00 bounds must not be reused
    once that weekday opens at 12:00."""
    ctx = _ctx_full_month("1,3,5")
    cache = {}
    build_rows(2026, 5, ctx, PLAN_RULES, random.Random(0),
               time_cache=cache, center_id=1, plan="HF", travel_minutes=10,
               calendar=_calendar(opening="08:00"))
    rows = build_rows(2026, 5, ctx, PLAN_RULES, random.Random(0),
                      time_cache=cache, center_id=1, plan="HF",
                      travel_minutes=10, calendar=_calendar(opening="12:00"))
    for r in rows:
        if r["status"] == "attended":
            assert _to_min(r["time_in"]) >= _to_min("12:00")


def test_build_rows_cache_regenerates_with_availability_row():
    """Same guard, but through the placement_window branch: a member with
    a recurring availability rule still gets regenerated times when the
    weekday's opening moves from 08:00 to 12:00."""
    avail = [
        {"id": d, "center_id": 1,
         "effective_start_date": date(2026, 1, 1),
         "effective_end_date": None,
         "day_of_week": d, "avail_start": "07:00", "avail_end": "17:00"}
        for d in (1, 3, 5)
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
        absences=[], availabilities=avail, one_offs=[],
    )
    cache = {}
    build_rows(2026, 5, ctx, PLAN_RULES, random.Random(0),
               time_cache=cache, center_id=1, plan="HF", travel_minutes=10,
               calendar=_calendar(opening="08:00"))
    rows = build_rows(2026, 5, ctx, PLAN_RULES, random.Random(0),
                      time_cache=cache, center_id=1, plan="HF",
                      travel_minutes=10, calendar=_calendar(opening="12:00"))
    attended = [r for r in rows if r["status"] == "attended"]
    assert attended
    for r in attended:
        assert _to_min(r["time_in"]) >= _to_min("12:00")


def test_debug_rows_holiday_sentence():
    cal = _calendar(holidays=[("Test Holiday", date(2026, 5, 4))])
    rows = build_debug_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES,
                            calendar=cal)
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["scheduled"] is False
    assert mon["reason"] == "Center closed (Test Holiday)"


def test_debug_rows_closed_weekday_sentence():
    cal = _calendar(open_days=(2, 4))
    rows = build_debug_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES,
                            calendar=cal)
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["reason"] == "Center closed on Mondays"


def test_debug_rows_open_day_window_uses_weekday_hours():
    cal = _calendar(opening="09:00", closing="15:00")
    rows = build_debug_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES,
                            calendar=cal)
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["scheduled"] is True
    assert mon["placement_window"] == "09:00-15:00"
