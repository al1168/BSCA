"""Tests for monthly_schedule.hha_parser.

The parser must classify each HHA free-text row into one of four
outcomes: applied (DB write emitted), ambiguous (CSV row emitted),
skipped (had time but all clauses fell after center close), or
ignored (no time content at all). See
docs/superpowers/specs/2026-06-01-hha-availability-backfill-design.md
"""
from monthly_schedule.hha_parser import parse_hha_row


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
