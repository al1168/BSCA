"""Tests for monthly_schedule.hha_parser.

The parser must classify each HHA free-text row into one of four
outcomes: applied (DB write emitted), ambiguous (CSV row emitted),
skipped (had time but all clauses fell after center close), or
ignored (no time content at all). See
docs/superpowers/specs/2026-06-01-hha-availability-backfill-design.md
"""
import pytest
from monthly_schedule.hha_parser import _normalize, _parse_days, _parse_time_block, parse_hha_row


def test_empty_string_is_ignored():
    result = parse_hha_row("")
    assert result["ignored"] is True
    assert result["applied"] is False
    assert result["ambiguous"] is False
    assert result["skipped"] is False
    assert result["clauses"] == []


def test_days_only_no_time_is_ignored():
    # Real sample: "1.2.3.7" — just days, nothing to do.
    result = parse_hha_row("1.2.3.7")
    assert result["ignored"] is True


def test_agency_name_only_is_ignored():
    # Real sample: "Better Choice" — agency name, no schedule info.
    result = parse_hha_row("Better Choice")
    assert result["ignored"] is True


def test_agency_with_phone_is_ignored():
    # Real sample: "新康: (212) 390-5496" — phone digits must not
    # be mis-detected as a time block.
    result = parse_hha_row("新康: (212) 390-5496")
    assert result["ignored"] is True


def test_days_with_hours_count_no_time_is_ignored():
    # Real sample: "Better Choice: 3.4.5.6.7 x 3 Hrs" — hours but
    # no explicit time block.
    result = parse_hha_row("Better Choice: 3.4.5.6.7 x 3 Hrs")
    assert result["ignored"] is True


def test_day_range_without_time_marker_is_ignored():
    # "1-7" is a day range, not a time block. Without ':MM' or 'am'/'pm'
    # somewhere we must not mistake it for time content.
    result = parse_hha_row("1-7")
    assert result["ignored"] is True


def test_phone_dash_digits_alone_is_ignored():
    # Phone "390-5496" looks dash-y but has no time marker.
    result = parse_hha_row("Always Home Care 390-5496")
    assert result["ignored"] is True


@pytest.mark.parametrize("text,expected", [
    # Trailing pm applies to both sides
    ("2:30-7pm", ("14:30", "19:00")),
    ("2pm-8pm", ("14:00", "20:00")),
    # Trailing am applies to both
    ("7am-11am", ("07:00", "11:00")),
    # Start has am, end has pm (cross noon)
    ("8am-12pm", ("08:00", "12:00")),
    # 12am in a daytime context is treated as noon
    ("8-12am", ("08:00", "12:00")),
    # End only has pm, start < end numerically with pm context
    ("3-7pm", ("15:00", "19:00")),
    # Half-time via dot ("5.45pm" -> 5:45 pm)
    ("12-5.45pm", ("12:00", "17:45")),
    # Both sides full
    ("8:30-11:30PM", ("20:30", "23:30")),
    # Unicode en-dash and whitespace
    ("2 – 7 pm", ("14:00", "19:00")),
    # Space in colon position ("8: 30PM")
    ("3:30-8: 30PM", ("15:30", "20:30")),
    # 12am edge: 12am = 00:00, but rare in HHA data; keep strict
    ("12am-1am", ("00:00", "01:00")),
    # Overnight: left is PM, so "12am" really means midnight
    ("11pm-12am", ("23:00", "00:00")),
    ("8pm-12am", ("20:00", "00:00")),
    # Already-AM left: "1am-12am" is unusual but valid; 12am stays midnight
    ("1am-12am", ("01:00", "00:00")),
])
def test_parse_time_block_accepts_real_formats(text, expected):
    assert _parse_time_block(text) == expected


@pytest.mark.parametrize("text", [
    "garbage",
    "after 1p.m.",         # only one side, no dash
    "3-",                  # truncated (real sample: "5.6.7(2:45pm-")
    "",
])
def test_parse_time_block_returns_none_for_unparseable(text):
    assert _parse_time_block(text) is None


@pytest.mark.parametrize("text,expected", [
    ("1.2.3", {1, 2, 3}),
    ("1,2,3", {1, 2, 3}),
    ("4.5.6", {4, 5, 6}),
    ("1-5", {1, 2, 3, 4, 5}),
    ("1-7", {1, 2, 3, 4, 5, 6, 7}),
    ("4-7", {4, 5, 6, 7}),
    # Mixed dot+range (real sample: "1-5.6.7" doesn't appear but
    # "1-5(...) 6.7(...)" does; per-clause this could be "1-5" alone)
    ("2.4.7", {2, 4, 7}),
    # Single day
    ("4", {4}),
    # Whitespace tolerance
    (" 1 . 2 . 3 ", {1, 2, 3}),
])
def test_parse_days_accepts_real_formats(text, expected):
    assert _parse_days(text) == expected


@pytest.mark.parametrize("text", [
    "",
    "abc",
    "8",          # out of 1-7 range
    "0",          # out of 1-7 range
])
def test_parse_days_returns_empty_set_when_no_valid_days(text):
    assert _parse_days(text) == set()


def _apply_clauses(result):
    """Helper: return list of (day, avail_end) for clauses that
    were marked apply, sorted by day for stable comparison."""
    out = []
    for c in result["clauses"]:
        if c["status"] == "apply":
            for d in sorted(c["days"]):
                out.append((d, c["avail_end"]))
    return sorted(out)


def test_user_example_ppl_thursday_friday_saturday():
    # The canonical example from the spec.
    result = parse_hha_row("PPL: (4.5.6) 2:30-7pm")
    assert result["applied"] is True
    assert result["ambiguous"] is False
    assert result["ignored"] is False
    assert _apply_clauses(result) == [
        (4, "14:30"), (5, "14:30"), (6, "14:30"),
    ]


def test_single_clause_no_agency_prefix():
    # Real sample: "5.6.7(2pm-6pm)"
    result = parse_hha_row("5.6.7(2pm-6pm)")
    assert result["applied"] is True
    assert _apply_clauses(result) == [
        (5, "14:00"), (6, "14:00"), (7, "14:00"),
    ]


def test_single_clause_day_range():
    # Real sample: "1-7(2-6pm)"
    result = parse_hha_row("1-7(2-6pm)")
    assert result["applied"] is True
    assert _apply_clauses(result) == [(d, "14:00") for d in range(1, 8)]


def test_evening_only_hha_is_skipped_row_outcome():
    # Real sample: "(1.4.6.7) 5-10pm" — HHA at 17:00, after center
    # closes at 16:00. No DB write, no CSV row.
    result = parse_hha_row("(1.4.6.7) 5-10pm")
    assert result["applied"] is False
    assert result["ambiguous"] is False
    assert result["skipped"] is True
    assert result["ignored"] is False


def test_hha_starting_exactly_at_close_is_skipped():
    # Edge case: HHA_start == 16:00. Per spec >= 16:00 is skip.
    result = parse_hha_row("1.2.3 4-8pm")
    assert result["skipped"] is True
    assert result["applied"] is False


def test_morning_hha_is_ambiguous():
    # Real sample: "1.2.3(7AM-10AM)" — HHA_start = 07:00 < 08:00.
    # Per spec we don't try to push avail_start later; flag it.
    result = parse_hha_row("1.2.3(7AM-10AM)")
    assert result["ambiguous"] is True
    assert result["ambiguous_reason"] == "morning_or_pre_open"
    assert result["applied"] is False


def test_hha_starting_exactly_at_open_is_ambiguous():
    # Edge: HHA_start == 08:00 means the whole center day is blocked.
    # Per spec <= 08:00 is morning_or_pre_open ambiguous.
    result = parse_hha_row("1.2.3.4.5.6.7 (8am-12am)")
    assert result["ambiguous"] is True
    assert result["ambiguous_reason"] == "morning_or_pre_open"


def test_normalize_replaces_unicode_punctuation():
    # Real sample: "25026.0|万友: 5.6.7 ( 3:30-8: 30PM)" already has
    # ASCII but Chinese rows can have full-width punctuation.
    assert _normalize("（4.5.6）2:30-7pm") == "(4.5.6) 2:30-7pm"


def test_normalize_strips_agency_prefix():
    # "PPL:" is agency name + colon. No digits before the colon =>
    # strip it. (We keep "(212) 226-1353" etc. because the digits
    # come before the colon there.)
    assert _normalize("PPL: (4.5.6) 2:30-7pm") == "(4.5.6) 2:30-7pm"


def test_normalize_does_not_strip_when_digit_precedes_colon():
    # "2:30" is a time, not an agency prefix. Don't strip past it.
    text = _normalize("(4.5.6) 2:30-7pm")
    assert text == "(4.5.6) 2:30-7pm"


def test_normalize_strips_chinese_agency_prefix():
    # Real sample: "万有: (6.7) 12pm-6pm" — CJK agency name.
    out = _normalize("万有: (6.7) 12pm-6pm")
    assert out == "(6.7) 12pm-6pm"


def test_normalize_lowercases_am_pm():
    assert "PM" not in _normalize("2:30-7PM")


def test_user_example_still_works_after_normalize_wiring():
    # Defensive — make sure Task 4's behavior didn't regress.
    result = parse_hha_row("PPL: (4.5.6) 2:30-7pm")
    assert _apply_clauses(result) == [
        (4, "14:30"), (5, "14:30"), (6, "14:30"),
    ]
