import sys
from pathlib import Path

import pytest


# Ensure the script is importable as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import backfill_availability_from_hha as backfill


# ---------------------------------------------------------------------------
# Tests for _is_test_id helper and --exclude-test-members
# ---------------------------------------------------------------------------

def test_is_test_id_true_cases():
    assert backfill._is_test_id(12300) is True
    assert backfill._is_test_id(99500) is True
    assert backfill._is_test_id(100) is True


def test_is_test_id_false_cases():
    assert backfill._is_test_id(12345) is False
    assert backfill._is_test_id(99999) is False
    assert backfill._is_test_id(99501) is False


def test_exclude_test_members_flag_parses():
    ns = backfill._parse_args(["--db", "x"])
    assert hasattr(ns, "exclude_test_members")
    assert ns.exclude_test_members is False

    ns2 = backfill._parse_args(["--db", "x", "--exclude-test-members"])
    assert ns2.exclude_test_members is True


def test_main_missing_db_returns_2(tmp_path, capsys):
    missing = tmp_path / "nope.accdb"
    rc = backfill.main(["--db", str(missing)])
    assert rc == 2
    assert "database not found" in capsys.readouterr().err.lower()


class _FakeConn:
    """Minimal pyodbc connection stand-in for main() integration tests.

    contacts_rows are returned by the first fetchall() (the _CONTACTS_QUERY).
    All subsequent fetchall()/fetchone() calls return [] / None — used by
    _AVAIL_OPEN_QUERY to indicate no existing Availability rows.
    """
    def __init__(self, contacts_rows):
        self._contacts_rows = contacts_rows
        self._cursor = None
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        if self._cursor is None:
            self._cursor = _FakeCursor(self._contacts_rows)
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class _FakeCursor:
    def __init__(self, contacts_rows):
        self._contacts_rows = contacts_rows
        self._contacts_fetched = False
        self.executed = []

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self

    def fetchall(self):
        if not self._contacts_fetched:
            self._contacts_fetched = True
            return self._contacts_rows
        return []

    def fetchone(self):
        return None


def test_summary_shows_test_skipped_zero_without_flag(
    tmp_path, capsys, monkeypatch
):
    fake_conn = _FakeConn(contacts_rows=[])
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake_conn)

    db_file = tmp_path / "test.accdb"
    db_file.touch()

    rc = backfill.main(["--db", str(db_file), "--csv-out", str(tmp_path)])
    assert rc == 0

    out = capsys.readouterr().out
    assert "Test members excluded (--exclude-test-members): 0" in out


def test_exclude_test_members_skips_trailing_00_before_parse(
    tmp_path, capsys, monkeypatch
):
    # Contact with cid=12300, hha = a real-looking HHA string that WOULD
    # otherwise be parsed and applied. The flag must skip before parse.
    contacts_rows = [(12300, "Doe", "John", "M-F 8a-12p HHA")]
    fake_conn = _FakeConn(contacts_rows=contacts_rows)
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake_conn)

    db_file = tmp_path / "test.accdb"
    db_file.touch()

    rc = backfill.main([
        "--db", str(db_file),
        "--csv-out", str(tmp_path),
        "--exclude-test-members",
    ])
    assert rc == 0

    cur = fake_conn._cursor
    executed_sqls = [sql for sql, _ in cur.executed]
    # The only execute should be _CONTACTS_QUERY. No Availability writes.
    assert backfill._AVAIL_OPEN_QUERY not in executed_sqls
    assert backfill._AVAIL_UPDATE not in executed_sqls
    assert backfill._AVAIL_INSERT not in executed_sqls

    out = capsys.readouterr().out
    assert "Test members excluded (--exclude-test-members): 1" in out
    assert "TEST-SKIP 12300" in out

    assert fake_conn.committed is True
