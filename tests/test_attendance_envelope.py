import datetime

import pytest

from monthly_schedule.attendance_envelope import (
    collect_samples,
    hhmm,
    normalize_time,
    parse_sheet_filename,
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


# ---------------------------------------------------------------------------
# parse_sheet_filename
# ---------------------------------------------------------------------------

def test_parse_sheet_filename_real_pattern():
    assert parse_sheet_filename(
        "(1001).Zhang, Mingli Attendance 2026-08.xlsm"
    ) == (1001, "Zhang, Mingli", "2026-08")


def test_parse_sheet_filename_tolerates_spaces_and_case():
    assert parse_sheet_filename(
        "(25).Lin,  Bo Hua  Attendance 2026-07.XLSM"
    ) == (25, "Lin,  Bo Hua", "2026-07")


@pytest.mark.parametrize("name", [
    "Daily Sign-in-out 2026-08.xlsm",
    "(1001).Zhang, Mingli TP 2026-08.xlsm",
    "Zhang, Mingli Attendance 2026-08.xlsm",
    "~$(1001).Zhang, Mingli Attendance 2026-08.xlsm",
])
def test_parse_sheet_filename_rejects_other_files(name):
    assert parse_sheet_filename(name) is None


# ---------------------------------------------------------------------------
# collect_samples — rows: (center_id, iso_weekday, time_in_min, time_out_min)
# ---------------------------------------------------------------------------

def test_collect_samples_groups_by_member_and_weekday():
    rows = [
        (1001, 1, 500, 745),
        (1001, 1, 505, 750),
        (1001, 2, 510, 755),
        (1002, 1, 600, 840),
    ]
    samples, dropped = collect_samples(rows)
    assert samples == {
        (1001, 1): [(500, 745), (505, 750)],
        (1001, 2): [(510, 755)],
        (1002, 1): [(600, 840)],
    }
    assert dropped == 0


def test_collect_samples_drops_out_not_after_in():
    rows = [(1001, 1, 500, 500), (1001, 1, 600, 550), (1001, 1, 500, 745)]
    samples, dropped = collect_samples(rows)
    assert samples == {(1001, 1): [(500, 745)]}
    assert dropped == 2


def test_collect_samples_skips_rows_missing_a_time():
    rows = [(1001, 1, None, 745), (1001, 1, 500, None), (1001, 1, 500, 745)]
    samples, dropped = collect_samples(rows)
    assert samples == {(1001, 1): [(500, 745)]}
    assert dropped == 0
