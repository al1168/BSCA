import random

import pytest

from monthly_schedule.rules import SCHEDULE_RULES, parse_hhmm
from monthly_schedule.daily_schedule import build_daily_schedule, validate_schedule


def _to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def test_default_bounds_produce_valid_ordering():
    rng = random.Random(42)
    for _ in range(200):
        s = build_daily_schedule(SCHEDULE_RULES["Default"], rng)
        pu = _to_min(s["pickup"])
        ar = _to_min(s["arrival"])
        ti = _to_min(s["time_in"])
        to = _to_min(s["time_out"])
        de = _to_min(s["departure"])
        do = _to_min(s["dropoff"])
        assert ti >= 8 * 60                     # Time-In not before 08:00
        assert to <= 16 * 60                    # Time-Out not after 16:00
        assert 210 <= to - ti <= 240            # length 3h30m-4h00m
        assert ti == ar + 2                     # Time-In = Arrival+2
        assert to == de - 2                     # Time-Out = Departure-2
        assert pu < ar <= ti
        assert to <= de < do


def test_block_stays_within_a_narrow_window():
    # Member available 08:00-11:40 (3h40m). Pass that as the placement
    # window: every block must sit inside it, never time-out past 11:40,
    # and the length is capped to the 3h40m of free time.
    rules = SCHEDULE_RULES["Default"]
    in_lo, out_hi = parse_hhmm("08:00"), parse_hhmm("11:40")  # 480, 700
    rng = random.Random(0)
    lengths = []
    for _ in range(2000):
        s = build_daily_schedule(rules, rng, window=(in_lo, out_hi))
        ti = _to_min(s["time_in"])
        to = _to_min(s["time_out"])
        assert ti >= in_lo
        assert to <= out_hi
        lengths.append(to - ti)
    assert min(lengths) >= 210
    assert max(lengths) <= 220          # capped at the 3h40m window


def test_arrival_can_be_anywhere_in_a_wide_window():
    # A wide window (08:00-16:00) should place time-in across a broad
    # range, not pinned to a fixed arrival window.
    rules = SCHEDULE_RULES["Default"]
    rng = random.Random(1)
    time_ins = set()
    for _ in range(2000):
        s = build_daily_schedule(rules, rng, window=(480, 960))
        time_ins.add(_to_min(s["time_in"]))
    # spread well beyond the old 08:00-11:00 arrival window (660)
    assert max(time_ins) > 12 * 60


def test_time_in_snapped_with_5_minute_step():
    rules = dict(SCHEDULE_RULES["Default"])
    rules["round_to_minutes"] = 5
    rng = random.Random(7)
    for _ in range(200):
        s = build_daily_schedule(rules, rng, window=(parse_hhmm("08:02"),
                                                     parse_hhmm("15:58")))
        ti = _to_min(s["time_in"])
        to = _to_min(s["time_out"])
        assert ti % 5 == 0
        assert to <= parse_hhmm("15:58")
        assert 210 <= to - ti <= 240


def test_keys_present():
    rng = random.Random(1)
    s = build_daily_schedule(SCHEDULE_RULES["Default"], rng)
    assert set(s) == {
        "pickup", "arrival", "time_in", "time_out", "departure", "dropoff"
    }


def test_validate_schedule_raises_on_bad_ordering():
    rules = SCHEDULE_RULES["Default"]
    with pytest.raises(ValueError):
        # pickup not before arrival
        validate_schedule(500, 480, 481, 700, 720, 730, rules)


def test_validate_schedule_raises_on_session_length():
    rules = SCHEDULE_RULES["Default"]
    with pytest.raises(ValueError):
        # 30-minute length (time_in=480, time_out=510), below the 210 min
        validate_schedule(470, 478, 480, 510, 512, 520, rules)


def test_validate_schedule_raises_on_time_in_after_time_out():
    rules = SCHEDULE_RULES["Default"]
    with pytest.raises(ValueError):
        # valid ends individually, but time_in (600) > time_out (590)
        validate_schedule(470, 478, 600, 590, 700, 710, rules)
