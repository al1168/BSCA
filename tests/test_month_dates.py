from datetime import date

import pytest

from monthly_schedule.month_dates import get_month_dates


def test_31_day_month():
    days = get_month_dates(2026, 5)
    assert days[0] == date(2026, 5, 1)
    assert days[-1] == date(2026, 5, 31)
    assert len(days) == 31


def test_30_day_month():
    days = get_month_dates(2026, 4)
    assert days[-1] == date(2026, 4, 30)
    assert len(days) == 30


def test_february_non_leap():
    days = get_month_dates(2026, 2)
    assert days[-1] == date(2026, 2, 28)
    assert len(days) == 28


def test_february_leap():
    days = get_month_dates(2024, 2)
    assert days[-1] == date(2024, 2, 29)
    assert len(days) == 29


# ---------------------------------------------------------------------------
# Custom day range
# ---------------------------------------------------------------------------


def test_range_trims_to_inclusive_window():
    days = get_month_dates(2026, 5, start_day=1, end_day=19)
    assert days[0] == date(2026, 5, 1)
    assert days[-1] == date(2026, 5, 19)
    assert len(days) == 19


def test_range_mid_month():
    days = get_month_dates(2026, 5, start_day=10, end_day=15)
    assert [d.day for d in days] == [10, 11, 12, 13, 14, 15]


def test_range_single_day():
    days = get_month_dates(2026, 5, start_day=15, end_day=15)
    assert days == [date(2026, 5, 15)]


def test_range_only_start_defaults_end_to_last_day():
    days = get_month_dates(2026, 4, start_day=28)
    assert days == [
        date(2026, 4, 28),
        date(2026, 4, 29),
        date(2026, 4, 30),
    ]


def test_range_only_end_defaults_start_to_first():
    days = get_month_dates(2026, 5, end_day=3)
    assert days == [
        date(2026, 5, 1),
        date(2026, 5, 2),
        date(2026, 5, 3),
    ]


def test_range_end_exceeds_month_raises():
    with pytest.raises(ValueError):
        get_month_dates(2026, 4, end_day=31)  # April has 30 days


def test_range_feb_29_in_non_leap_year_raises():
    with pytest.raises(ValueError):
        get_month_dates(2026, 2, end_day=29)


def test_range_feb_29_in_leap_year_ok():
    days = get_month_dates(2024, 2, end_day=29)
    assert days[-1] == date(2024, 2, 29)


def test_range_start_after_end_raises():
    with pytest.raises(ValueError):
        get_month_dates(2026, 5, start_day=20, end_day=10)


def test_range_start_below_one_raises():
    with pytest.raises(ValueError):
        get_month_dates(2026, 5, start_day=0, end_day=10)
