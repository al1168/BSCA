import datetime

import pytest

from monthly_schedule.attendance_envelope import (
    Estimate,
    collect_samples,
    estimate_windows,
    hhmm,
    normalize_time,
    parse_sheet_filename,
    round_window,
    window_flags,
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


# ---------------------------------------------------------------------------
# round_window — start down, end up, to 5 minutes
# ---------------------------------------------------------------------------

def test_round_window_rounds_outward():
    assert round_window(8 * 60 + 21, 12 * 60 + 23) == (8 * 60 + 20, 12 * 60 + 25)


def test_round_window_keeps_exact_multiples():
    assert round_window(8 * 60 + 20, 12 * 60 + 25) == (8 * 60 + 20, 12 * 60 + 25)


# ---------------------------------------------------------------------------
# window_flags
# ---------------------------------------------------------------------------

def test_window_flags_plain_morning_window():
    assert window_flags(8 * 60 + 20, 12 * 60 + 25, closing_min=14 * 60) == []


def test_window_flags_past_close():
    assert window_flags(9 * 60 + 55, 14 * 60 + 25, closing_min=14 * 60) == ["past_close"]


def test_window_flags_afternoon_only_and_past_close():
    assert window_flags(12 * 60 + 30, 17 * 60 + 25, closing_min=14 * 60) == [
        "past_close", "afternoon_only",
    ]


def test_window_flags_afternoon_boundary_is_inclusive():
    assert "afternoon_only" in window_flags(10 * 60 + 30, 15 * 60, closing_min=16 * 60)
    assert "afternoon_only" not in window_flags(10 * 60 + 29, 15 * 60, closing_min=16 * 60)


def test_window_flags_narrow():
    assert window_flags(8 * 60, 11 * 60 + 55, closing_min=14 * 60) == ["narrow"]
    assert "narrow" not in window_flags(8 * 60, 12 * 60, closing_min=14 * 60)


# ---------------------------------------------------------------------------
# estimate_windows — {weekday: [(in, out), ...]} -> {1..7: Estimate}
# ---------------------------------------------------------------------------

def _samples(n, lo_in, hi_in, lo_out, hi_out):
    """n samples spread evenly between the given bounds."""
    if n == 1:
        return [(lo_in, lo_out)]
    return [
        (lo_in + (hi_in - lo_in) * i // (n - 1),
         lo_out + (hi_out - lo_out) * i // (n - 1))
        for i in range(n)
    ]


def test_estimate_windows_per_weekday_envelope_rounded_outward():
    member = {
        d: _samples(13, 8 * 60 + 21, 8 * 60 + 33, 12 * 60 + 18, 12 * 60 + 33)
        for d in (1, 2, 3, 4, 5)
    }
    est = estimate_windows(member, min_samples=4)
    assert est[1] == Estimate(start=8 * 60 + 20, end=12 * 60 + 35,
                              samples=13, flags=[])


def test_estimate_windows_low_samples_widen_to_member_envelope():
    member = {
        1: _samples(13, 8 * 60 + 21, 8 * 60 + 33, 12 * 60 + 18, 12 * 60 + 33),
        6: [(8 * 60 + 40, 12 * 60 + 40), (8 * 60 + 41, 12 * 60 + 42)],
    }
    est = estimate_windows(member, min_samples=4)
    # Saturday union: start = min(8:40, 8:21)=8:21 -> 8:20;
    #                 end   = max(12:42, 12:33)=12:42 -> 12:45
    assert est[6] == Estimate(start=8 * 60 + 20, end=12 * 60 + 45,
                              samples=2, flags=["low_samples"])


def test_estimate_windows_no_data_weekday_gets_member_envelope():
    member = {1: _samples(13, 8 * 60 + 21, 8 * 60 + 33, 12 * 60 + 18, 12 * 60 + 33)}
    est = estimate_windows(member, min_samples=4)
    assert set(est) == {1, 2, 3, 4, 5, 6, 7}
    assert est[3] == Estimate(start=8 * 60 + 20, end=12 * 60 + 35,
                              samples=0, flags=["member_wide"])


def test_estimate_windows_empty_member_is_empty():
    assert estimate_windows({}, min_samples=4) == {}


def test_estimate_windows_afternoon_member_keeps_afternoon():
    member = {2: _samples(13, 12 * 60 + 32, 12 * 60 + 47, 16 * 60 + 50, 16 * 60 + 59)}
    est = estimate_windows(member, min_samples=4)
    assert est[2].start == 12 * 60 + 30
    assert est[2].end == 17 * 60
