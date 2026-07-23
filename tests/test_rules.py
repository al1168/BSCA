from monthly_schedule.rules import (
    SCHEDULE_RULES,
    get_rules_for_plan,
    parse_hhmm,
    format_minutes,
    band_for_member,
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


def test_dropoff_by_avail_end_defaults_on():
    assert SCHEDULE_RULES["Default"]["dropoff_by_avail_end"] is True


def test_dropoff_by_avail_end_bool_override_passes_through():
    # Booleans must survive the overrides merge untouched (only lists
    # are converted to tuples).
    rules = get_rules_for_plan("Default", {"dropoff_by_avail_end": False})
    assert rules["dropoff_by_avail_end"] is False


def test_band_defaults_present():
    d = SCHEDULE_RULES["Default"]
    assert d["band_enabled"] is False
    assert d["morning_percent"] == 80
    assert d["morning_window_min"] == 180
    assert d["morning_members"] == ()
    assert d["afternoon_members"] == ()


def _band_rules(**over):
    return {**SCHEDULE_RULES["Default"], "band_enabled": True, **over}


def test_band_disabled_returns_none_for_everyone():
    # band_enabled is False by default; pins are ignored while off.
    rules = {**SCHEDULE_RULES["Default"],
             "morning_members": (1,), "afternoon_members": (2,)}
    for cid in (1, 2, 3, 24010):
        assert band_for_member(cid, rules) is None


def test_band_missing_key_treated_as_disabled():
    # Settings files saved before this feature have no band_enabled key.
    rules = {k: v for k, v in SCHEDULE_RULES["Default"].items()
             if k != "band_enabled"}
    assert band_for_member(1, rules) is None


def test_band_none_center_id_returns_none():
    assert band_for_member(None, _band_rules()) is None


def test_band_deterministic_across_calls():
    rules = _band_rules()
    for cid in range(200):
        assert band_for_member(cid, rules) == band_for_member(cid, rules)


def test_band_distribution_near_percent():
    # Fixed IDs -> deterministic result; md5 is uniform so 1000 IDs land
    # within a few points of 80/20 (expected 800, sd ~12.6).
    rules = _band_rules(morning_percent=80)
    morning = sum(
        band_for_member(cid, rules) == "morning" for cid in range(1000)
    )
    assert 750 <= morning <= 850


def test_band_percent_edges():
    ids = range(50)
    assert all(band_for_member(c, _band_rules(morning_percent=100))
               == "morning" for c in ids)
    assert all(band_for_member(c, _band_rules(morning_percent=0))
               == "afternoon" for c in ids)


def test_band_pins_win_over_hash():
    rules = _band_rules(morning_percent=100, afternoon_members=(7,))
    assert band_for_member(7, rules) == "afternoon"
    rules = _band_rules(morning_percent=0, morning_members=(7,))
    assert band_for_member(7, rules) == "morning"


def test_band_overlap_morning_wins():
    # GUI blocks this at save; defensively, morning wins.
    rules = _band_rules(morning_members=(7,), afternoon_members=(7,))
    assert band_for_member(7, rules) == "morning"


def test_band_ignores_junk_in_pin_lists():
    # Hand-edited settings file: string IDs are cast, junk is skipped.
    rules = _band_rules(morning_percent=0,
                        morning_members=("7", "junk", None))
    assert band_for_member(7, rules) == "morning"


def test_band_golden_values_frozen():
    """Pins the id->band mapping: any change to the hash silently
    re-buckets every real member, so it must fail loudly."""
    rules = _band_rules()
    assert band_for_member(0, rules) == "morning"
    assert band_for_member(7, rules) == "morning"
    assert band_for_member(24010, rules) == "morning"
    assert band_for_member(24011, rules) == "morning"

    rules50 = _band_rules(morning_percent=50)
    assert band_for_member(0, rules50) == "afternoon"      # bucket 50
    assert band_for_member(7, rules50) == "afternoon"      # bucket 55
    assert band_for_member(24010, rules50) == "morning"    # bucket 35
    assert band_for_member(24011, rules50) == "morning"    # bucket 4


def test_band_lists_survive_overrides_merge():
    # JSON overrides arrive as lists; get_rules_for_plan turns them into
    # tuples -- membership checks must still work.
    rules = get_rules_for_plan("Default", {
        "band_enabled": True,
        "morning_members": [1, 2],
        "afternoon_members": [3],
    })
    assert band_for_member(1, rules) == "morning"
    assert band_for_member(3, rules) == "afternoon"
