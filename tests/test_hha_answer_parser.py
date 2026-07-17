import pytest

from monthly_schedule.hha_answer_parser import (
    AnswerParseError,
    hhmm,
    parse_answer,
    parse_time,
    subtract_care_window,
)


# ---------------------------------------------------------------------------
# parse_time — minutes since midnight
# ---------------------------------------------------------------------------

def test_parse_time_basic_am_pm():
    assert parse_time("8 AM") == 8 * 60
    assert parse_time("1 PM") == 13 * 60
    assert parse_time("8:30 AM") == 8 * 60 + 30
    assert parse_time("5:30 PM") == 17 * 60 + 30


def test_parse_time_noon_and_midnight():
    assert parse_time("12 PM") == 12 * 60      # noon
    assert parse_time("12:30 PM") == 12 * 60 + 30
    assert parse_time("12 AM") == 0            # midnight


def test_parse_time_is_case_and_space_insensitive():
    assert parse_time("8am") == 8 * 60
    assert parse_time(" 7 pm ") == 19 * 60
    assert parse_time("9:15PM") == 21 * 60 + 15


@pytest.mark.parametrize("bad", ["8", "25 PM", "0 AM", "8:5 PM", "eight AM", ""])
def test_parse_time_rejects_unparseable(bad):
    with pytest.raises(AnswerParseError):
        parse_time(bad)


# ---------------------------------------------------------------------------
# parse_answer — full answer cells, real rows from the reviewed CSV
# ---------------------------------------------------------------------------

def test_parse_answer_single_group():
    groups = parse_answer("1.5.6.7 (1 PM - 7 PM)")
    assert groups == [
        {"days": {1, 5, 6, 7}, "start": 13 * 60, "end": 19 * 60},
    ]


def test_parse_answer_multi_group_pipe_separated():
    groups = parse_answer(
        "1.5 (8:30 AM - 5:30 PM) | 3.6 (12 PM - 5 PM) | 7 (12:30 PM - 2:30 PM)"
    )
    assert [g["days"] for g in groups] == [{1, 5}, {3, 6}, {7}]
    assert groups[0] == {"days": {1, 5}, "start": 510, "end": 1050}
    assert groups[2] == {"days": {7}, "start": 750, "end": 870}


def test_parse_answer_tolerates_hand_filled_spacing():
    """Spacing quirks taken verbatim from the operator's hand-filled rows."""
    assert parse_answer("1.5.6.7  (1 PM- 7 PM)")[0]["days"] == {1, 5, 6, 7}
    assert parse_answer("2.5 (1 PM-5 PM) | 6.7 (8AM-12PM)")[1] == {
        "days": {6, 7}, "start": 8 * 60, "end": 12 * 60,
    }
    # Missing space before the pipe.
    groups = parse_answer("4 (8 AM - 2 PM)| 6.7 (8 AM - 1 PM)")
    assert [g["days"] for g in groups] == [{4}, {6, 7}]


@pytest.mark.parametrize("bad", [
    "",                        # blank (callers skip blanks; parsing one is an error)
    "gibberish",
    "1.8 (1 PM - 2 PM)",       # day out of 1-7
    "(1 PM - 2 PM)",           # no days
    "1 (3 PM - 1 PM)",         # start not before end
    "1 (3 PM - 3 PM)",         # zero-length
    "1 (1 PM 2 PM)",           # no dash
    "1 1 PM - 2 PM",           # no parentheses
])
def test_parse_answer_rejects_malformed(bad):
    with pytest.raises(AnswerParseError):
        parse_answer(bad)


# ---------------------------------------------------------------------------
# hhmm — display helper
# ---------------------------------------------------------------------------

def test_hhmm_formats_minutes():
    assert hhmm(8 * 60) == "08:00"
    assert hhmm(12 * 60 + 30) == "12:30"
    assert hhmm(0) == "00:00"


# ---------------------------------------------------------------------------
# subtract_care_window — spec §4. Windows are (start_min, end_min) tuples;
# the typical open window post-setup is the seeded default 08:00-13:00.
# ---------------------------------------------------------------------------

DEFAULT = (8 * 60, 13 * 60)


def test_subtract_no_overlap_after_close():
    """5 PM - 9 PM care vs 08:00-13:00: no change."""
    result = subtract_care_window(DEFAULT, (17 * 60, 21 * 60))
    assert result == {"action": "none", "window": DEFAULT, "dropped": None}


def test_subtract_no_overlap_touching_edges():
    """Care ending exactly at open / starting exactly at close: no change."""
    assert subtract_care_window(DEFAULT, (6 * 60, 8 * 60))["action"] == "none"
    assert subtract_care_window(DEFAULT, (13 * 60, 15 * 60))["action"] == "none"


def test_subtract_front_overlap_pushes_start():
    """6 AM - 12 PM care: morning care pushes avail_start to 12:00."""
    result = subtract_care_window(DEFAULT, (6 * 60, 12 * 60))
    assert result == {
        "action": "narrow", "window": (12 * 60, 13 * 60), "dropped": None,
    }


def test_subtract_back_overlap_pulls_end():
    """12 PM - 4 PM care: avail_end pulled to 12:00 (the original rule)."""
    result = subtract_care_window(DEFAULT, (12 * 60, 16 * 60))
    assert result == {
        "action": "narrow", "window": (8 * 60, 12 * 60), "dropped": None,
    }


def test_subtract_strict_inside_keeps_longer_piece():
    """8:30 AM - 12 PM care leaves 08:00-08:30 and 12:00-13:00; the
    longer piece (12:00-13:00) is kept, the other reported as dropped."""
    result = subtract_care_window(DEFAULT, (510, 12 * 60))
    assert result == {
        "action": "split",
        "window": (12 * 60, 13 * 60),
        "dropped": (8 * 60, 510),
    }


def test_subtract_strict_inside_tie_keeps_morning():
    """Equal pieces (30 min each): keep the morning piece."""
    result = subtract_care_window(DEFAULT, (510, 750))
    assert result["action"] == "split"
    assert result["window"] == (8 * 60, 510)
    assert result["dropped"] == (750, 13 * 60)


def test_subtract_full_cover_is_blocked():
    """6:30 AM - 1:30 PM care swallows 08:00-13:00 entirely."""
    result = subtract_care_window(DEFAULT, (390, 810))
    assert result == {"action": "blocked", "window": None, "dropped": None}


def test_subtract_exact_cover_is_blocked():
    result = subtract_care_window(DEFAULT, DEFAULT)
    assert result["action"] == "blocked"


def test_subtract_is_idempotent():
    """Subtracting the same care window from the already-narrowed
    result is a no-op — re-running the tool is safe."""
    care = (12 * 60, 16 * 60)
    first = subtract_care_window(DEFAULT, care)
    second = subtract_care_window(first["window"], care)
    assert second == {
        "action": "none", "window": first["window"], "dropped": None,
    }
