"""Unit tests for the pure helpers in scripts/audit_enrollment_gate.py."""
import datetime
import sys
from pathlib import Path

# Ensure the script is importable as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import audit_enrollment_gate as audit  # noqa: E402


def _row(start, end, rid=1):
    return {"id": rid, "center_id": 1, "start_date": start, "end_date": end}


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_csv_columns():
    assert audit._CSV_COLUMNS == [
        "center_id", "name", "plan", "month_failure",
        "enrolled_days_in_month", "enrollment_rows", "open_rows",
        "stale_open_row", "auth_overlap",
    ]


# ---------------------------------------------------------------------------
# format_enrollment_rows
# ---------------------------------------------------------------------------

def test_format_enrollment_rows_closed_and_open():
    rows = [
        _row(datetime.date(2025, 5, 1), datetime.date(2026, 6, 2)),
        _row(datetime.date(2026, 6, 2), None, rid=2),
    ]
    assert audit.format_enrollment_rows(rows) == (
        "2025-05-01..2026-06-02|2026-06-02..open"
    )


def test_format_enrollment_rows_empty():
    assert audit.format_enrollment_rows([]) == ""


# ---------------------------------------------------------------------------
# stale_open_row detection
# ---------------------------------------------------------------------------

def test_stale_open_row_when_older_open_row_exists():
    # An open row whose start predates the latest row's start is stale —
    # the BSCA-Members app judges termination by the LATEST row only,
    # while the scheduler treats ANY overlapping row as enrolled.
    rows = [
        _row(datetime.date(2025, 5, 1), None),                       # stale
        _row(datetime.date(2026, 11, 1), None, rid=2),               # real
    ]
    assert audit.has_stale_open_row(rows) is True


def test_no_stale_open_row_for_single_open_row():
    assert audit.has_stale_open_row(
        [_row(datetime.date(2025, 5, 1), None)]
    ) is False


def test_no_stale_open_row_when_old_rows_are_closed():
    rows = [
        _row(datetime.date(2024, 1, 1), datetime.date(2025, 1, 1)),
        _row(datetime.date(2026, 11, 1), None, rid=2),
    ]
    assert audit.has_stale_open_row(rows) is False


def test_no_stale_open_row_without_rows():
    assert audit.has_stale_open_row([]) is False


# ---------------------------------------------------------------------------
# enrolled-day count
# ---------------------------------------------------------------------------

def test_count_enrolled_days_partial_month():
    rows = [_row(datetime.date(2026, 9, 1), datetime.date(2026, 9, 15))]
    assert audit.count_enrolled_days(rows, 2026, 9) == 15


def test_count_enrolled_days_zero_when_disjoint():
    rows = [_row(datetime.date(2026, 11, 1), None)]
    assert audit.count_enrolled_days(rows, 2026, 9) == 0


# ---------------------------------------------------------------------------
# auth overlap
# ---------------------------------------------------------------------------

def _auth(start, end):
    return {"id": 1, "center_id": 1, "auth_start": start, "auth_end": end,
            "effective_start": start, "effective_end": end,
            "auth_days": "1,2,3,4,5"}


def test_auth_overlap_true_when_window_touches_month():
    auths = [_auth(datetime.date(2026, 9, 15), datetime.date(2026, 12, 31))]
    assert audit.auth_overlaps_month(auths, 2026, 9) is True


def test_auth_overlap_false_when_window_disjoint():
    auths = [_auth(datetime.date(2026, 5, 1), datetime.date(2026, 6, 30))]
    assert audit.auth_overlaps_month(auths, 2026, 9) is False


# ---------------------------------------------------------------------------
# per-member audit row
# ---------------------------------------------------------------------------

def test_audit_member_row_skipped_member():
    member = {"center_id": 24011, "last_name": "Smith",
              "first_name": "John", "health_plan": "HF"}
    enrollments = [_row(datetime.date(2026, 11, 1), None)]
    row = audit.audit_member(member, enrollments, [], [], [], [], 2026, 9)
    assert row["center_id"] == 24011
    assert row["name"] == "Smith, John"
    assert row["plan"] == "HF"
    assert row["month_failure"] == "not enrolled during this month"
    assert row["enrolled_days_in_month"] == 0
    assert row["auth_overlap"] is False


def test_audit_member_row_passing_member():
    member = {"center_id": 24001, "last_name": "Luo",
              "first_name": "Dezhi", "health_plan": "HF"}
    enrollments = [_row(datetime.date(2026, 9, 1),
                        datetime.date(2026, 9, 15))]
    auths = [_auth(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))]
    row = audit.audit_member(
        member, enrollments, auths, [], [], [], 2026, 9
    )
    assert row["month_failure"] == ""
    assert row["enrolled_days_in_month"] == 15
    assert row["auth_overlap"] is True
