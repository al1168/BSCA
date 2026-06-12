import csv
import datetime
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import change_dob_to_date_in_contacts as migration


# ---------------------------------------------------------------------------
# Query / constant tests
# ---------------------------------------------------------------------------

def test_build_connection_string():
    cs = migration._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


def test_alter_statement_shape():
    q = migration._ALTER_DOB_TO_DATETIME
    assert "ALTER TABLE [Contacts]" in q
    assert "ALTER COLUMN [DOB]" in q
    assert "DATETIME" in q


def test_contacts_query_columns():
    q = migration._CONTACTS_QUERY
    assert "[Center ID]" in q
    assert "[DOB]" in q
    assert "FROM [Contacts]" in q
    assert "ORDER BY [Center ID]" in q


def test_min_year_constant():
    assert migration._MIN_DOB_YEAR == 1900


# ---------------------------------------------------------------------------
# _parse_dob
# ---------------------------------------------------------------------------

def test_parse_dob_all_four_spacings():
    """M/D/YYYY, MM/D/YYYY, M/DD/YYYY, MM/DD/YYYY all parse."""
    assert migration._parse_dob("1/1/1950", 2026) == (
        datetime.date(1950, 1, 1), "",
    )
    assert migration._parse_dob("11/1/1950", 2026) == (
        datetime.date(1950, 11, 1), "",
    )
    assert migration._parse_dob("1/15/1950", 2026) == (
        datetime.date(1950, 1, 15), "",
    )
    assert migration._parse_dob("11/15/1950", 2026) == (
        datetime.date(1950, 11, 15), "",
    )


def test_parse_dob_strips_whitespace():
    assert migration._parse_dob("  3/1/1960  ", 2026) == (
        datetime.date(1960, 3, 1), "",
    )


def test_parse_dob_returns_null_for_none():
    assert migration._parse_dob(None, 2026) == (None, "null")


def test_parse_dob_returns_empty_for_blank_string():
    assert migration._parse_dob("", 2026) == (None, "empty")
    assert migration._parse_dob("   ", 2026) == (None, "empty")


def test_parse_dob_bad_format():
    assert migration._parse_dob("not a date", 2026)[1] == "bad_format"
    assert migration._parse_dob("11/24/195", 2026)[1] == "bad_format"
    assert migration._parse_dob("2024-01-01", 2026)[1] == "bad_format"
    assert migration._parse_dob("42024", 2026)[1] == "bad_format"


def test_parse_dob_rejects_year_too_low():
    assert migration._parse_dob("1/1/1899", 2026) == (None, "year_low")


def test_parse_dob_rejects_year_too_high():
    assert migration._parse_dob("1/1/2030", 2026) == (None, "year_high")


def test_parse_dob_rejects_five_digit_year_via_format():
    """Typo '4/1/19567' — Python's strptime('%Y') treats the year as
    a fixed 4-digit field and fails when given 5 digits, so the
    reason is 'bad_format' rather than 'year_high'."""
    parsed, reason = migration._parse_dob("4/1/19567", 2026)
    assert parsed is None
    assert reason == "bad_format"


# ---------------------------------------------------------------------------
# _dob_column_type
# ---------------------------------------------------------------------------

class _FakeCursor:
    """Cursor with mockable columns() metadata."""
    def __init__(self, columns_meta):
        self._meta = columns_meta
        self.executed = []
        self._fetchall_queue = []

    def columns(self, table):
        rows = [
            SimpleNamespace(column_name=name, type_name=tname)
            for name, tname in self._meta
        ]
        return SimpleNamespace(fetchall=lambda: rows)

    def queue_fetchall(self, rows):
        self._fetchall_queue.append(rows)

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self

    def fetchall(self):
        return self._fetchall_queue.pop(0)


def test_dob_column_type_returns_varchar_when_text():
    cur = _FakeCursor([("Center ID", "DOUBLE"), ("DOB", "VARCHAR")])
    assert migration._dob_column_type(cur) == "VARCHAR"


def test_dob_column_type_returns_datetime_when_already_converted():
    cur = _FakeCursor([("Center ID", "DOUBLE"), ("DOB", "DATETIME")])
    assert migration._dob_column_type(cur) == "DATETIME"


def test_dob_column_type_case_insensitive_match():
    cur = _FakeCursor([("Center ID", "DOUBLE"), ("dob", "VARCHAR")])
    assert migration._dob_column_type(cur) == "VARCHAR"


def test_dob_column_type_returns_none_when_missing():
    cur = _FakeCursor([("Center ID", "DOUBLE"), ("Last Name", "VARCHAR")])
    assert migration._dob_column_type(cur) is None


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        pass


def test_main_missing_db_returns_2(tmp_path, capsys):
    missing = tmp_path / "nope.accdb"
    rc = migration.main(["--db", str(missing)])
    assert rc == 2
    assert "database not found" in capsys.readouterr().err.lower()


def test_main_short_circuits_when_already_datetime(
    tmp_path, monkeypatch, capsys,
):
    """If DOB is already DATETIME, the script reports and exits 0
    without running ALTER."""
    cur = _FakeCursor([("DOB", "DATETIME")])
    conn = _FakeConn(cur)
    monkeypatch.setattr("pyodbc.connect", lambda cs: conn)

    db_file = tmp_path / "test.accdb"
    db_file.touch()

    rc = migration.main([
        "--db", str(db_file),
        "--csv-out", str(tmp_path),
    ])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "already" in out
    # No ALTER, no commit.
    assert cur.executed == []
    assert conn.committed is False


def test_main_aborts_when_dob_column_missing(tmp_path, monkeypatch, capsys):
    """If Contacts has no DOB column at all, return 2 with a clear
    error rather than crashing on the ALTER."""
    cur = _FakeCursor([("Center ID", "DOUBLE"), ("Address", "VARCHAR")])
    conn = _FakeConn(cur)
    monkeypatch.setattr("pyodbc.connect", lambda cs: conn)

    db_file = tmp_path / "test.accdb"
    db_file.touch()

    rc = migration.main([
        "--db", str(db_file),
        "--csv-out", str(tmp_path),
    ])
    assert rc == 2
    err = capsys.readouterr().err.lower()
    assert "dob" in err
    assert "not found" in err


def test_main_pre_scans_then_alters_when_varchar(
    tmp_path, monkeypatch,
):
    """Happy path: VARCHAR column, all DOBs parseable. ALTER runs."""
    cur = _FakeCursor([("DOB", "VARCHAR")])
    cur.queue_fetchall([
        (12301.0, "1/1/1950"),
        (12302.0, "3/15/1962"),
    ])
    conn = _FakeConn(cur)
    monkeypatch.setattr("pyodbc.connect", lambda cs: conn)

    db_file = tmp_path / "test.accdb"
    db_file.touch()

    rc = migration.main([
        "--db", str(db_file),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    # Exactly one ALTER statement executed, and the SELECT.
    sql_executed = [s for s, _p in cur.executed]
    assert migration._ALTER_DOB_TO_DATETIME in sql_executed
    assert migration._CONTACTS_QUERY in sql_executed
    assert conn.committed is True

    # CSV has only the header (no unparseable rows).
    today_iso = datetime.date.today().isoformat()
    csv_path = tmp_path / f"dob_conversion_unparseable_{today_iso}.csv"
    assert csv_path.exists()
    lines = csv_path.read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) == 1


def test_main_logs_unparseable_rows_then_still_alters(
    tmp_path, monkeypatch,
):
    """Mixed: some parseable, some not. Bad rows go to CSV. ALTER
    still runs (Access handles its own internal conversion)."""
    cur = _FakeCursor([("DOB", "VARCHAR")])
    cur.queue_fetchall([
        (12301.0, "1/1/1950"),         # good
        (12302.0, "11/24/195"),        # 3-digit year (bad_format)
        (12303.0, "1/1/2099"),         # future year (year_high — 2099 > 2026)
        (12304.0, None),                # NULL
        (12305.0, ""),                  # empty
        (12306.0, "junk"),              # bad_format
    ])
    conn = _FakeConn(cur)
    monkeypatch.setattr("pyodbc.connect", lambda cs: conn)

    db_file = tmp_path / "test.accdb"
    db_file.touch()

    rc = migration.main([
        "--db", str(db_file),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0
    assert migration._ALTER_DOB_TO_DATETIME in [s for s, _ in cur.executed]
    assert conn.committed is True

    # CSV has 5 data rows (the 5 suspect ones).
    today_iso = datetime.date.today().isoformat()
    csv_path = tmp_path / f"dob_conversion_unparseable_{today_iso}.csv"
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 5
    cids = {int(r["center_id"]) for r in rows}
    assert cids == {12302, 12303, 12304, 12305, 12306}
    # Reasons captured correctly.
    by_cid = {int(r["center_id"]): r["reason"] for r in rows}
    assert by_cid[12302] == "bad_format"   # "11/24/195" — 3-digit year
    assert by_cid[12303] == "year_high"    # "1/1/2099" — future
    assert by_cid[12304] == "null"
    assert by_cid[12305] == "empty"
    assert by_cid[12306] == "bad_format"


def test_main_dry_run_writes_csv_but_skips_alter(tmp_path, monkeypatch):
    """`--dry-run` performs the pre-scan + writes CSV without running
    the ALTER and without committing."""
    cur = _FakeCursor([("DOB", "VARCHAR")])
    cur.queue_fetchall([
        (12301.0, "1/1/1950"),
        (12302.0, "bad"),
    ])
    conn = _FakeConn(cur)
    monkeypatch.setattr("pyodbc.connect", lambda cs: conn)

    db_file = tmp_path / "test.accdb"
    db_file.touch()

    rc = migration.main([
        "--db", str(db_file),
        "--csv-out", str(tmp_path),
        "--dry-run",
        "--quiet",
    ])
    assert rc == 0

    sql_executed = [s for s, _ in cur.executed]
    assert migration._CONTACTS_QUERY in sql_executed
    assert migration._ALTER_DOB_TO_DATETIME not in sql_executed
    assert conn.committed is False
