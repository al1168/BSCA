from datetime import date

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
