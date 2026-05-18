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
        pu = _to_min(s["pickup"])
        ar = _to_min(s["arrival"])
        ti = _to_min(s["time_in"])
        to = _to_min(s["time_out"])
        de = _to_min(s["departure"])
        do = _to_min(s["dropoff"])
        assert 8 * 60 <= ar <= 11 * 60          # Arrival 08:00-11:00
        assert 210 <= de - ar <= 245            # span 3h30m-4h5m
        assert ti == ar + 2                     # Time-In = Arrival+2
        assert to == de - 2                     # Time-Out = Departure-2
        assert pu < ar <= ti
        assert to <= de < do


def test_keys_present():
    rng = random.Random(1)
    s = build_daily_schedule(SCHEDULE_RULES["Default"], rng)
    assert set(s) == {
        "pickup", "arrival", "time_in", "time_out", "departure", "dropoff"
    }


def test_arrival_snapped_with_5_minute_step():
    rng = random.Random(7)
    rules = {
        "arrival_window": ("08:02", "08:58"),
        "session_span_min": (210, 245),
        "pickup_lead_min": (8, 12),
        "dropoff_trail_min": (8, 12),
        "time_in_drift_min": (2, 2),
        "time_out_drift_min": (2, 2),
        "round_to_minutes": 5,
    }
    for _ in range(100):
        s = build_daily_schedule(rules, rng)
        ar = _to_min(s["arrival"])
        de = _to_min(s["departure"])
        assert ar % 5 == 0
        assert 210 <= de - ar <= 245
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
        # 30-minute span, below session_span_min lower bound (210)
        validate_schedule(470, 480, 480, 510, 510, 520, rules)


def test_validate_schedule_raises_on_time_in_after_time_out():
    rules = SCHEDULE_RULES["Default"]
    with pytest.raises(ValueError):
        # valid ends individually, but time_in (600) > time_out (590)
        validate_schedule(470, 480, 600, 590, 700, 710, rules)
