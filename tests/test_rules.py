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
    assert d["earliest_time_in"] == "08:00"
    assert d["latest_time_out"] == "16:00"
    assert d["session_length_min"] == (210, 240)
    assert d["time_in_drift_min"] == (2, 2)
    assert d["time_out_drift_min"] == (2, 2)
    assert d["pickup_lead_min"] == (8, 12)
    assert d["dropoff_trail_min"] == (8, 12)
    assert d["round_to_minutes"] == 1
    buf_lo, buf_hi = d["travel_buffer_min"]
    assert 0 < buf_lo <= buf_hi
    # the old arrival-window model is gone
    assert "arrival_window" not in d
    assert "session_span_min" not in d


def test_get_rules_for_plan_falls_back_to_default():
    assert get_rules_for_plan("Elderplan Homefirst") is SCHEDULE_RULES["Default"]
    assert get_rules_for_plan(None) is SCHEDULE_RULES["Default"]
    assert get_rules_for_plan("") is SCHEDULE_RULES["Default"]


def test_get_rules_for_plan_uses_specific_entry(monkeypatch):
    monkeypatch.setitem(SCHEDULE_RULES, "SpecialPlan", {"marker": True})
    assert get_rules_for_plan("SpecialPlan") == {"marker": True}


def test_overrides_replace_default_values():
    overrides = {
        "earliest_time_in": "07:00",
        "latest_time_out": "15:00",
        "session_length_min": [180, 200],
    }
    rules = get_rules_for_plan("Default", overrides)
    assert rules["earliest_time_in"] == "07:00"
    assert rules["latest_time_out"] == "15:00"
    assert rules["session_length_min"] == (180, 200)
    # Unmentioned keys still come from the default.
    assert rules["time_in_drift_min"] == SCHEDULE_RULES["Default"]["time_in_drift_min"]


def test_overrides_none_value_keeps_default():
    """A None override is a 'no opinion' marker — defaults still apply."""
    rules = get_rules_for_plan(
        "Default", {"earliest_time_in": None}
    )
    assert rules["earliest_time_in"] == SCHEDULE_RULES["Default"]["earliest_time_in"]


def test_overrides_does_not_mutate_default():
    """get_rules_for_plan must return a fresh dict so caller mutations
    can't leak back into the global SCHEDULE_RULES table."""
    before = dict(SCHEDULE_RULES["Default"])
    rules = get_rules_for_plan("Default", {"earliest_time_in": "07:00"})
    rules["earliest_time_in"] = "99:99"  # caller stomp
    assert SCHEDULE_RULES["Default"] == before


def test_no_overrides_returns_default_dict_unchanged():
    assert get_rules_for_plan("Default") is SCHEDULE_RULES["Default"]
    assert get_rules_for_plan("Default", None) is SCHEDULE_RULES["Default"]
    assert get_rules_for_plan("Default", {}) is SCHEDULE_RULES["Default"]
