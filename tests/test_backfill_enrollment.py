import datetime
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure the script is importable as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import backfill_enrollment_from_contacts as backfill


# ---------------------------------------------------------------------------
# Query / constant tests
# ---------------------------------------------------------------------------

def test_build_connection_string():
    cs = backfill._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


def test_main_missing_db_returns_2(tmp_path, capsys):
    missing = tmp_path / "nope.accdb"
    rc = backfill.main(["--db", str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "database not found" in err.lower()


def test_contacts_query_columns():
    q = backfill._CONTACTS_QUERY
    assert "[Center ID]" in q
    assert "[Last Name]" not in q
    assert "[First Name]" not in q
    assert "FROM [Contacts]" in q
    assert "WHERE" not in q  # full table scan
    assert "ORDER BY [Center ID]" in q


def test_enrollment_count_query():
    q = backfill._ENROLLMENT_COUNT_FOR_MEMBER
    assert "COUNT(*)" in q
    assert "FROM [Enrollment]" in q
    assert "WHERE [Center ID] = ?" in q


def test_enrollment_insert_query():
    q = backfill._ENROLLMENT_INSERT
    for col in ("[Center ID]", "[start_date]", "[end_date]"):
        assert col in q
    assert q.count("?") == 3


# ---------------------------------------------------------------------------
# _is_test_id
# ---------------------------------------------------------------------------

def test_is_test_id_true_cases():
    assert backfill._is_test_id(12300) is True
    assert backfill._is_test_id(99500) is True
    assert backfill._is_test_id(100) is True


def test_is_test_id_false_cases():
    assert backfill._is_test_id(12345) is False
    assert backfill._is_test_id(99999) is False
    assert backfill._is_test_id(99501) is False


# ---------------------------------------------------------------------------
# FakeCursor
# ---------------------------------------------------------------------------

class FakeCursor:
    """Records execute() calls and returns canned fetch results.

    Use queue_fetchall() before each execute that the code-under-test
    will follow with fetchall(). Use queue_fetchone() similarly.
    """
    def __init__(self):
        self.executed = []        # list of (sql, params_tuple)
        self._fetchall_queue = []
        self._fetchone_queue = []

    def queue_fetchall(self, rows):
        self._fetchall_queue.append(rows)

    def queue_fetchone(self, row):
        self._fetchone_queue.append(row)

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self

    def fetchall(self):
        return self._fetchall_queue.pop(0)

    def fetchone(self):
        return self._fetchone_queue.pop(0)


# ---------------------------------------------------------------------------
# Helpers for integration tests
# ---------------------------------------------------------------------------

class FakeConn:
    """Minimal connection stand-in that wraps a FakeCursor."""
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


def _make_fake_conn_for_contacts(contacts_rows, count_values):
    """Build a FakeCursor / FakeConn pair pre-loaded with:
    - One fetchall result for _CONTACTS_QUERY.
    - One fetchone result per member for _ENROLLMENT_COUNT_FOR_MEMBER.
    """
    cur = FakeCursor()
    # _read_contacts uses fetchall for the contacts query.
    cur.queue_fetchall(contacts_rows)
    # For each member, one fetchone for the COUNT query.
    for val in count_values:
        cur.queue_fetchone((val,))
    return FakeConn(cur), cur


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def test_main_inserts_for_members_without_enrollment(tmp_path, monkeypatch):
    contacts = [
        (12301,),
        (12302,),
    ]
    conn, cur = _make_fake_conn_for_contacts(contacts, [0, 0])

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    # Create a stub DB file so the path-exists check passes.
    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = backfill.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    inserts = [(s, p) for s, p in cur.executed
               if s == backfill._ENROLLMENT_INSERT]
    assert len(inserts) == 2

    # Verify parameters: (str(cid), datetime, None)
    for (sql, params), (cid,) in zip(inserts, contacts):
        assert params[0] == str(cid)
        assert isinstance(params[1], datetime.datetime)
        assert params[2] is None

    # Count queries should have been issued for both members.
    count_calls = [(s, p) for s, p in cur.executed
                   if s == backfill._ENROLLMENT_COUNT_FOR_MEMBER]
    assert len(count_calls) == 2

    assert conn.committed is True


def test_main_skips_members_already_enrolled(tmp_path, monkeypatch):
    contacts = [(12301,)]
    conn, cur = _make_fake_conn_for_contacts(contacts, [1])

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = backfill.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    inserts = [(s, p) for s, p in cur.executed
               if s == backfill._ENROLLMENT_INSERT]
    assert len(inserts) == 0

    # Check that the already_enrolled path was exercised — no CSV row, no
    # insert, but the count query WAS called.
    count_calls = [(s, p) for s, p in cur.executed
                   if s == backfill._ENROLLMENT_COUNT_FOR_MEMBER]
    assert len(count_calls) == 1

    # Summary should mention already_enrolled=1 in stdout.
    assert conn.committed is True


def test_exclude_test_members_skips_trailing_00(tmp_path, monkeypatch, capsys):
    contacts = [(12300,)]
    # No COUNT queued — the member should be skipped before COUNT is called.
    conn, cur = _make_fake_conn_for_contacts(contacts, [])

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = backfill.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--exclude-test-members",
    ])
    assert rc == 0

    # No COUNT query should have been issued for this member.
    count_calls = [(s, p) for s, p in cur.executed
                   if s == backfill._ENROLLMENT_COUNT_FOR_MEMBER]
    assert len(count_calls) == 0

    # No INSERT either.
    inserts = [s for s, _ in cur.executed
               if s == backfill._ENROLLMENT_INSERT]
    assert len(inserts) == 0

    out = capsys.readouterr().out
    assert "TEST-SKIP" in out
    assert "Test members excluded" in out


def test_exclude_test_members_default_off_includes_00_ids(tmp_path, monkeypatch):
    contacts = [(12300,)]
    # COUNT returns 0 -> should be inserted.
    conn, cur = _make_fake_conn_for_contacts(contacts, [0])

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = backfill.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    count_calls = [(s, p) for s, p in cur.executed
                   if s == backfill._ENROLLMENT_COUNT_FOR_MEMBER]
    # Without the flag, the COUNT query IS issued.
    assert len(count_calls) == 1

    inserts = [(s, p) for s, p in cur.executed
               if s == backfill._ENROLLMENT_INSERT]
    assert len(inserts) == 1


def test_dry_run_calls_rollback_not_commit(tmp_path, monkeypatch):
    contacts = [(12301,)]
    conn, cur = _make_fake_conn_for_contacts(contacts, [0])

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = backfill.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--dry-run",
        "--quiet",
    ])
    assert rc == 0
    assert conn.rolled_back is True
    assert conn.committed is False
