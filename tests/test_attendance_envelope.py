import datetime

import pytest

from monthly_schedule.attendance_envelope import (
    hhmm,
    normalize_time,
)


# ---------------------------------------------------------------------------
# hhmm
# ---------------------------------------------------------------------------

def test_hhmm_formats_minutes():
    assert hhmm(0) == "00:00"
    assert hhmm(8 * 60 + 5) == "08:05"
    assert hhmm(14 * 60) == "14:00"


# ---------------------------------------------------------------------------
# normalize_time — Attendance sheets store 12-hour clock times without AM/PM
# ---------------------------------------------------------------------------

def test_normalize_time_morning_time_object():
    assert normalize_time(datetime.time(8, 21)) == 8 * 60 + 21


def test_normalize_time_before_six_is_pm():
    assert normalize_time(datetime.time(2, 0)) == 14 * 60
    assert normalize_time(datetime.time(5, 59)) == 17 * 60 + 59


def test_normalize_time_six_is_am():
    assert normalize_time(datetime.time(6, 0)) == 6 * 60


def test_normalize_time_accepts_datetime():
    assert normalize_time(datetime.datetime(1899, 12, 30, 1, 33)) == 13 * 60 + 33


def test_normalize_time_accepts_excel_fraction():
    assert normalize_time(0.5) == 12 * 60          # noon
    assert normalize_time(0.0625) == 13 * 60 + 30  # 1.5h -> 01:30 -> PM


def test_normalize_time_accepts_hhmm_string():
    assert normalize_time("09:41") == 9 * 60 + 41
    assert normalize_time("1:20") == 13 * 60 + 20


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_normalize_time_blank_is_none(blank):
    assert normalize_time(blank) is None


def test_normalize_time_rejects_garbage():
    assert normalize_time("lunch") is None
