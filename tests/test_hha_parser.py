"""Tests for monthly_schedule.hha_parser.

The parser must classify each HHA free-text row into one of four
outcomes: applied (DB write emitted), ambiguous (CSV row emitted),
skipped (had time but all clauses fell after center close), or
ignored (no time content at all). See
docs/superpowers/specs/2026-06-01-hha-availability-backfill-design.md
"""
import pytest
from monthly_schedule.hha_parser import _parse_days, _parse_time_block, parse_hha_row


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
