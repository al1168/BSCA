import datetime
import re
import sys
from pathlib import Path

import pytest

# Ensure the script is importable as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import shorten_double_zero_ids as sh


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_tables_list():
    """The seven [Center ID] tables, Contacts first."""
    assert sh._TABLES == [
        "Contacts",
        "Enrollment",
        "Authorization",
        "Absences",
        "Availability",
        "OneOffAvailability",
        "EmergencyContact",
    ]


def test_csv_columns():
    assert sh._CSV_COLUMNS == ["old_id", "new_id", "reason"]


def test_scan_template_shape():
    q = sh._SCAN_TEMPLATE.format(table="Enrollment")
    assert q == "SELECT [Center ID] FROM [Enrollment]"


def test_rename_template_shape():
    q = sh._RENAME_TEMPLATE.format(table="Enrollment")
    assert "UPDATE [Enrollment]" in q
    assert "SET [Center ID] = ?" in q
    assert "WHERE [Center ID] = ?" in q
    assert q.count("?") == 2


# ---------------------------------------------------------------------------
# _build_connection_string
# ---------------------------------------------------------------------------

def test_build_connection_string():
    cs = sh._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


# ---------------------------------------------------------------------------
# _qualifies / _new_id
# ---------------------------------------------------------------------------

def test_qualifies_true_cases():
    assert sh._qualifies(2213400) is True       # 7 digits, ends 00
    assert sh._qualifies(2213400.0) is True     # DOUBLE form
    assert sh._qualifies(100000) is True        # 6 digits, ends 00
    assert sh._qualifies(99999900) is True      # 8 digits, ends 00


def test_qualifies_false_cases():
    assert sh._qualifies(24010) is False        # 5 digits
    assert sh._qualifies(99900) is False        # 5 digits, ends 00
    assert sh._qualifies(2400601) is False      # long, doesn't end 00
    assert sh._qualifies(2400601.0) is False    # DOUBLE form
    assert sh._qualifies(None) is False         # NULL Center ID


def test_new_id():
    assert sh._new_id(2213400) == 22134
    assert sh._new_id(2213400.0) == 22134       # DOUBLE form
    assert sh._new_id(123400) == 1234           # result < 5 digits is fine
    assert sh._new_id(221340000) == 2213400     # caller must skip: still >5


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------

def test_parse_args_requires_db():
    with pytest.raises(SystemExit):
        sh._parse_args([])


def test_parse_args_defaults():
    args = sh._parse_args(["--db", "C:/x.accdb"])
    assert args.db == "C:/x.accdb"
    assert args.csv_out == "."
    assert args.dry_run is False
    assert args.quiet is False


def test_parse_args_all_flags():
    args = sh._parse_args([
        "--db", "C:/x.accdb",
        "--csv-out", "/tmp/out",
        "--dry-run",
        "--quiet",
    ])
    assert args.csv_out == "/tmp/out"
    assert args.dry_run is True
    assert args.quiet is True
