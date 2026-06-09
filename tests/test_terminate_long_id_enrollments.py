import datetime
import sys
from pathlib import Path

import pytest

# Ensure the script is importable as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import terminate_long_id_enrollments as term


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_termination_date_constant():
    assert term.TERMINATION_DATE == datetime.date(2000, 1, 1)


def test_csv_columns():
    assert term._CSV_COLUMNS == ["center_id", "existing_end_date", "reason"]


def test_enrollment_scan_query():
    q = term._ENROLLMENT_SCAN
    assert "SELECT" in q
    assert "[Center ID]" in q
    assert "[end_date]" in q
    assert "FROM [Enrollment]" in q
    assert "ORDER BY [Center ID]" in q


def test_enrollment_terminate_query():
    q = term._ENROLLMENT_TERMINATE
    assert "UPDATE [Enrollment]" in q
    assert "SET [end_date] = ?" in q
    assert "WHERE [Center ID] = ?" in q
    assert "[end_date] IS NULL" in q
    assert q.count("?") == 2


# ---------------------------------------------------------------------------
# _build_connection_string
# ---------------------------------------------------------------------------

def test_build_connection_string():
    cs = term._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


# ---------------------------------------------------------------------------
# _is_long_id
# ---------------------------------------------------------------------------

def test_is_long_id_true_cases():
    assert term._is_long_id(100000) is True       # 6 digits
    assert term._is_long_id(2400600) is True      # 7 digits
    assert term._is_long_id(2400600.0) is True    # DOUBLE form
    assert term._is_long_id(9999999999) is True   # 10 digits


def test_is_long_id_false_cases():
    assert term._is_long_id(1) is False           # 1 digit
    assert term._is_long_id(24010) is False       # 5 digits
    assert term._is_long_id(99999) is False       # 5 digits
    assert term._is_long_id(99999.0) is False     # DOUBLE form, 5 digits
    assert term._is_long_id(None) is False        # NULL Center ID


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------

def test_parse_args_requires_db():
    with pytest.raises(SystemExit):
        term._parse_args([])


def test_parse_args_defaults():
    args = term._parse_args(["--db", "C:/x.accdb"])
    assert args.db == "C:/x.accdb"
    assert args.csv_out == "."
    assert args.dry_run is False
    assert args.quiet is False


def test_parse_args_all_flags():
    args = term._parse_args([
        "--db", "C:/x.accdb",
        "--csv-out", "/tmp/out",
        "--dry-run",
        "--quiet",
    ])
    assert args.csv_out == "/tmp/out"
    assert args.dry_run is True
    assert args.quiet is True


def test_parse_args_no_exclude_test_members_flag():
    """Per the spec, --exclude-test-members does NOT exist on this
    script. Argparse should reject the unknown flag."""
    with pytest.raises(SystemExit):
        term._parse_args(["--db", "C:/x.accdb", "--exclude-test-members"])
