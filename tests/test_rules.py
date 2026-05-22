from monthly_schedule.rules import (
    SCHEDULE_RULES,
    get_rules_for_plan,
    parse_hhmm,
    format_minutes,
)


def test_parse_hhmm():
    assert parse_hhmm("08:05") == 8 * 60 + 5
    assert parse_hhmm("00:00") == 0
    assert parse_hhmm("12:25") == 745


def test_format_minutes():
    assert format_minutes(0) == "00:00"
    assert format_minutes(8 * 60 + 5) == "08:05"
    assert format_minutes(745) == "12:25"
    assert format_minutes(24 * 60) == "00:00"  # wraps within a day


def test_default_rules_present_and_shaped():
    d = SCHEDULE_RULES["Default"]
    assert d["arrival_window"] == ("08:00", "11:00")
    assert d["session_span_min"] == (210, 245)
    assert d["time_in_drift_min"] == (2, 2)
    assert d["time_out_drift_min"] == (2, 2)
    assert d["pickup_lead_min"] == (8, 12)
    assert d["dropoff_trail_min"] == (8, 12)
    assert d["round_to_minutes"] == 1
    buf_lo, buf_hi = d["travel_buffer_min"]
    assert 0 < buf_lo <= buf_hi
    assert "departure_window" not in d
    assert "min_session_hours" not in d
    assert "max_session_hours" not in d


def test_get_rules_for_plan_falls_back_to_default():
    assert get_rules_for_plan("Elderplan Homefirst") is SCHEDULE_RULES["Default"]
    assert get_rules_for_plan(None) is SCHEDULE_RULES["Default"]
    assert get_rules_for_plan("") is SCHEDULE_RULES["Default"]


def test_get_rules_for_plan_uses_specific_entry(monkeypatch):
    monkeypatch.setitem(SCHEDULE_RULES, "SpecialPlan", {"marker": True})
    assert get_rules_for_plan("SpecialPlan") == {"marker": True}
