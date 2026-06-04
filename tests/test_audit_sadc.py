import csv
import datetime
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import audit_sadc as audit


def test_build_connection_string():
    cs = audit._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


def test_main_missing_db_returns_2(tmp_path, capsys):
    missing = tmp_path / "nope.accdb"
    rc = audit.main(["--db", str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "database not found" in err.lower()


def test_sadc_query_shape():
    assert "[SADC]" in audit._SADC_QUERY
    assert "FROM [Contacts]" in audit._SADC_QUERY
    assert "WHERE" not in audit._SADC_QUERY


def test_aggregate_groups_and_sorts_by_count_desc():
    rows = [
        ("1.2.3.4.5",),
        ("1.2.3.4.5",),
        ("1.2.3.4.5",),
        ("1.2.3",),
        ("1.2.3",),
        ("1.2.3.4.5.6.7->3DAYS",),
    ]
    aggregated, empty_count = audit._aggregate(rows)
    assert empty_count == 0
    assert aggregated == [
        {"sadc_value": "1.2.3.4.5", "member_count": 3,
         "current_parser_output": "1,2,3,4,5"},
        {"sadc_value": "1.2.3", "member_count": 2,
         "current_parser_output": "1,2,3"},
        {"sadc_value": "1.2.3.4.5.6.7->3DAYS", "member_count": 1,
         "current_parser_output": "1,2,3,4,5,6,7"},
    ]


def test_aggregate_counts_empty_separately():
    rows = [
        ("1.2.3",),
        (None,),
        ("",),
        ("   ",),
        ("1.2.3",),
    ]
    aggregated, empty_count = audit._aggregate(rows)
    assert empty_count == 3
    assert aggregated == [
        {"sadc_value": "1.2.3", "member_count": 2,
         "current_parser_output": "1,2,3"},
    ]


def test_aggregate_tie_break_alphabetic():
    rows = [("B",), ("A",), ("A",), ("B",)]
    aggregated, _ = audit._aggregate(rows)
    # Equal counts -> alphabetic ascending so output is stable.
    assert [r["sadc_value"] for r in aggregated] == ["A", "B"]


def test_write_audit_csv_header_only(tmp_path):
    path = audit._write_audit_csv(
        [], str(tmp_path), datetime.date(2026, 6, 3),
    )
    assert path.endswith("sadc_audit_2026-06-03.csv")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows == [["sadc_value", "member_count",
                     "current_parser_output", "expected_output"]]


def test_write_audit_csv_with_rows_appends_blank_expected(tmp_path):
    aggregated = [
        {"sadc_value": "1.2.3.4.5", "member_count": 3,
         "current_parser_output": "1,2,3,4,5"},
        {"sadc_value": "1.2.3.4.5->1.2.3", "member_count": 2,
         "current_parser_output": "1,2,3,4,5"},
    ]
    path = audit._write_audit_csv(
        aggregated, str(tmp_path), datetime.date(2026, 6, 3),
    )
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows == [
        {"sadc_value": "1.2.3.4.5", "member_count": "3",
         "current_parser_output": "1,2,3,4,5", "expected_output": ""},
        {"sadc_value": "1.2.3.4.5->1.2.3", "member_count": "2",
         "current_parser_output": "1,2,3,4,5", "expected_output": ""},
    ]


def test_write_audit_csv_creates_output_dir(tmp_path):
    out = tmp_path / "nested" / "dir"
    path = audit._write_audit_csv(
        [], str(out), datetime.date(2026, 6, 3),
    )
    assert os.path.exists(path)
