import random

import pytest

from monthly_schedule.rules import SCHEDULE_RULES, parse_hhmm
from monthly_schedule.daily_schedule import build_daily_schedule, validate_schedule


def _to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def test_default_rules_produce_valid_ordering():
    rng = random.Random(42)
    for _ in range(200):
        s = build_daily_schedule(SCHEDULE_RULES["Default"], rng)
        pu, ar, ti = _to_min(s["pickup"]), _to_min(s["arrival"]), _to_min(s["time_in"])
        to, de, do = _to_min(s["time_out"]), _to_min(s["departure"]), _to_min(s["dropoff"])
        assert pu < ar <= ti
        assert to <= de < do
        session_h = (de - ar) / 60
        assert 3 <= session_h <= 6


def test_keys_present():
    rng = random.Random(1)
    s = build_daily_schedule(SCHEDULE_RULES["Default"], rng)
    assert set(s) == {
        "pickup", "arrival", "time_in", "time_out", "departure", "dropoff"
    }


def test_tight_window_with_5_minute_snap():
    rng = random.Random(7)
    rules = {
        "arrival_window": ("08:02", "08:08"),
        "departure_window": ("12:01", "12:09"),
        "min_session_hours": 3,
        "max_session_hours": 6,
        "pickup_lead_min": (8, 12),
        "dropoff_trail_min": (8, 12),
        "time_in_drift_min": (0, 3),
        "time_out_drift_min": (0, 3),
        "round_to_minutes": 5,
    }
    for _ in range(100):
        s = build_daily_schedule(rules, rng)
        ar, de = _to_min(s["arrival"]), _to_min(s["departure"])
        assert ar % 5 == 0
        assert de % 5 == 0
        assert _to_min(s["pickup"]) < ar
        assert de < _to_min(s["dropoff"])


def test_validate_schedule_raises_on_bad_ordering():
    rules = SCHEDULE_RULES["Default"]
    with pytest.raises(ValueError):
        # pickup not before arrival
        validate_schedule(500, 480, 481, 700, 720, 730, rules)


def test_validate_schedule_raises_on_session_length():
    rules = SCHEDULE_RULES["Default"]
    with pytest.raises(ValueError):
        # 30-minute session, below min_session_hours
        validate_schedule(470, 480, 480, 510, 510, 520, rules)


def test_validate_schedule_raises_on_time_in_after_time_out():
    rules = SCHEDULE_RULES["Default"]
    with pytest.raises(ValueError):
        # valid ends individually, but time_in (600) > time_out (590)
        validate_schedule(470, 480, 600, 590, 700, 710, rules)
