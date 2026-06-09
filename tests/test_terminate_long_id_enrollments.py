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


# ---------------------------------------------------------------------------
# FakeCursor / FakeConn (mirrors tests/test_backfill_enrollment.py;
# adds `rowcount` because this script reads it).
# ---------------------------------------------------------------------------

class FakeCursor:
    """Records execute() calls; returns canned fetchall results. The
    `rowcount` attribute is settable per-test; defaults to 1 (single
    affected row) so happy-path tests don't need to set it explicitly."""
    def __init__(self):
        self.executed = []        # list of (sql, params_tuple)
        self._fetchall_queue = []
        self.rowcount = 1
        self._rowcount_queue = []

    def queue_fetchall(self, rows):
        self._fetchall_queue.append(rows)

    def queue_rowcount(self, n):
        """Queue a rowcount value to be returned by the NEXT execute()
        of the UPDATE query. Use when a test wants to verify the
        'Enrollment rows updated' summary counter."""
        self._rowcount_queue.append(n)

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        if self._rowcount_queue:
            self.rowcount = self._rowcount_queue.pop(0)
        return self

    def fetchall(self):
        return self._fetchall_queue.pop(0)


class FakeConn:
    def __init__(self, fake_cursor):
        self._cursor = fake_cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def _make_fake_conn(scan_rows):
    """Build a FakeConn whose cursor's fetchall (called by the scan)
    returns `scan_rows`."""
    cur = FakeCursor()
    cur.queue_fetchall(scan_rows)
    return FakeConn(cur), cur


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_missing_db_returns_2(tmp_path, capsys):
    missing = tmp_path / "nope.accdb"
    rc = term.main(["--db", str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "database not found" in err.lower()


def test_main_skips_short_ids(tmp_path, monkeypatch):
    """Short-ID rows must not trigger an UPDATE."""
    scan = [
        (24010, None),
        (25049, None),
    ]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    updates = [(s, p) for s, p in cur.executed
               if s == term._ENROLLMENT_TERMINATE]
    assert updates == []
    assert conn.committed is True


def test_main_terminates_long_id_with_null_end_date(tmp_path, monkeypatch):
    """Happy path: long-ID with NULL end_date triggers ONE UPDATE
    with parameters (datetime at 2000-01-01 00:00, cid)."""
    scan = [(2400600, None)]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    updates = [(s, p) for s, p in cur.executed
               if s == term._ENROLLMENT_TERMINATE]
    assert len(updates) == 1
    sql, params = updates[0]
    # main() converts TERMINATION_DATE (a date) to a datetime at
    # midnight before passing to pyodbc — matches the pattern used
    # by backfill_enrollment_from_contacts.py.
    assert params[0] == datetime.datetime(2000, 1, 1)
    assert params[1] == 2400600
    assert conn.committed is True


def test_main_skips_already_ended_long_id(tmp_path, monkeypatch):
    """Long-ID member whose only Enrollment row is already ended
    triggers no UPDATE and shows up in the skipped CSV."""
    scan = [(2400600, datetime.datetime(2025, 6, 30))]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    updates = [(s, p) for s, p in cur.executed
               if s == term._ENROLLMENT_TERMINATE]
    assert updates == []

    csv_path = tmp_path / f"terminate_long_id_skipped_{datetime.date.today().isoformat()}.csv"
    assert csv_path.exists()
    body = csv_path.read_text(encoding="utf-8-sig")
    assert "2400600" in body
    assert "2025-06-30" in body
    assert "end_date already set" in body


def test_main_mixed_null_and_ended_rows_for_same_member(
    tmp_path, monkeypatch,
):
    """Member-centric: a long-ID member with one NULL-end row and one
    already-ended row triggers ONE UPDATE for that member and does
    NOT appear in the skipped CSV."""
    scan = [
        (2400600, None),
        (2400600, datetime.datetime(2024, 1, 1)),
    ]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    updates = [(s, p) for s, p in cur.executed
               if s == term._ENROLLMENT_TERMINATE]
    assert len(updates) == 1, (
        "member-centric: exactly one UPDATE per member"
    )

    csv_path = tmp_path / f"terminate_long_id_skipped_{datetime.date.today().isoformat()}.csv"
    assert csv_path.exists()
    # The CSV body should contain only the header line, no data rows.
    body_lines = csv_path.read_text(encoding="utf-8-sig").splitlines()
    assert body_lines[0] == ",".join(term._CSV_COLUMNS)
    assert len(body_lines) == 1


def test_csv_skipped_row_uses_max_end_date(tmp_path, monkeypatch):
    """A member with multiple non-null end_dates lands in the CSV
    with the LATER (max) date."""
    scan = [
        (2400600, datetime.datetime(2024, 1, 1)),
        (2400600, datetime.datetime(2025, 6, 30)),
    ]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    csv_path = tmp_path / f"terminate_long_id_skipped_{datetime.date.today().isoformat()}.csv"
    body = csv_path.read_text(encoding="utf-8-sig")
    lines = body.splitlines()
    # Confirm exactly one data row (header + 1 = 2 lines)
    assert len(lines) == 2
    # The data row contains the later date.
    assert "2025-06-30" in lines[1]
    # And NOT the earlier date — catches a regression where the CSV
    # writes the min or both dates.
    assert "2024-01-01" not in lines[1]


def test_dry_run_calls_rollback_not_commit(tmp_path, monkeypatch):
    scan = [(2400600, None)]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--dry-run",
        "--quiet",
    ])
    assert rc == 0
    assert conn.rolled_back is True
    assert conn.committed is False


def test_quiet_suppresses_per_member_output(tmp_path, monkeypatch, capsys):
    """--quiet hides per-member lines but the summary still appears."""
    scan = [
        (2400600, None),
        (2401700, datetime.datetime(2024, 1, 1)),
    ]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    out = capsys.readouterr().out
    # Summary lines must appear
    assert "Terminate-long-ID summary" in out
    assert "Members terminated" in out
    # Per-member lines (terminated / skipped) must NOT appear
    assert "terminated cid=" not in out
    assert "skipped cid=" not in out


def test_non_quiet_prints_per_member_lines(tmp_path, monkeypatch, capsys):
    """Without --quiet, per-member lines do appear."""
    scan = [
        (2400600, None),
        (2401700, datetime.datetime(2024, 1, 1)),
    ]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
    ])
    assert rc == 0

    out = capsys.readouterr().out
    assert "terminated cid=2400600" in out
    assert "skipped cid=2401700" in out
