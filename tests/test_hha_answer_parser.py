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
