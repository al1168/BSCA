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


# ---------------------------------------------------------------------------
# Post-HHA default-fill: every (member, weekday) without an open
# Availability row gets a default 08:00-16:00 entry.
# ---------------------------------------------------------------------------


import datetime as _dt


class _SmartFakeCursor:
    """SQL-aware cursor for default-fill tests.

    Dispatches fetchall/fetchone by the most recently executed SQL so
    we can simulate distinct return values for _CONTACTS_QUERY,
    _ALL_MEMBER_IDS_QUERY, and _AVAIL_OPEN_QUERY in a single run.
    """

    def __init__(self, contacts_rows, all_member_ids, existing_avail):
        self._contacts_rows = list(contacts_rows)
        self._all_member_ids = list(all_member_ids)
        self._existing_avail = set(existing_avail)
        self._last_sql = None
        self._last_params = None
        self.executed = []

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        self._last_sql = sql
        self._last_params = params
        return self

    def fetchall(self):
        if self._last_sql == backfill._CONTACTS_QUERY:
            self._last_sql = None
            return self._contacts_rows
        if self._last_sql == backfill._ALL_MEMBER_IDS_QUERY:
            self._last_sql = None
            return [(mid,) for mid in self._all_member_ids]
        return []

    def fetchone(self):
        if self._last_sql == backfill._AVAIL_OPEN_QUERY:
            cid_str, day = self._last_params
            try:
                cid = int(cid_str)
            except (TypeError, ValueError):
                return None
            if (cid, day) in self._existing_avail:
                # pyodbc returns (id, avail_end_as_datetime); avail_end's
                # .time() must be > 08:00 so the "only shorten" path
                # doesn't fire from the HHA loop tests.
                return (
                    1,
                    _dt.datetime.combine(
                        _dt.date(1899, 12, 30), _dt.time(16, 0)
                    ),
                )
            return None
        return None


class _SmartFakeConn:
    def __init__(self, contacts_rows=None, all_member_ids=None,
                 existing_avail=None):
        self._cursor = _SmartFakeCursor(
            contacts_rows or [],
            all_member_ids or [],
            existing_avail or [],
        )
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


def test_default_fill_inserts_8_to_4_for_every_weekday(
    tmp_path, monkeypatch, capsys
):
    """A member with no HHA and no existing Availability gets 7 default
    08:00-16:00 rows (one per weekday Mon-Sun)."""
    fake = _SmartFakeConn(
        contacts_rows=[],
        all_member_ids=[24010],
        existing_avail=[],
    )
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake)
    db_file = tmp_path / "x.accdb"
    db_file.touch()

    rc = backfill.main([
        "--db", str(db_file), "--csv-out", str(tmp_path),
    ])
    assert rc == 0
    inserts = [
        params for sql, params in fake._cursor.executed
        if sql == backfill._AVAIL_INSERT
    ]
    assert len(inserts) == 7
    assert sorted({p[2] for p in inserts}) == [1, 2, 3, 4, 5, 6, 7]
    for cid_str, _today, _day, start_t, end_t in inserts:
        assert cid_str == "24010"
        assert start_t == backfill._hhmm_to_time("08:00")
        assert end_t == backfill._hhmm_to_time("16:00")
    out = capsys.readouterr().out
    assert "Default 8-4 rows inserted (post-HHA):  7" in out


def test_default_fill_skips_days_with_existing_rows(
    tmp_path, monkeypatch
):
    """Days already covered by HHA or manual entry keep their narrower
    row — the default fill does NOT overwrite them."""
    fake = _SmartFakeConn(
        contacts_rows=[],
        all_member_ids=[24010],
        existing_avail=[(24010, 2), (24010, 4)],  # Tue, Thu already set
    )
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake)
    db_file = tmp_path / "x.accdb"
    db_file.touch()

    rc = backfill.main([
        "--db", str(db_file), "--csv-out", str(tmp_path),
    ])
    assert rc == 0
    inserts = [
        params for sql, params in fake._cursor.executed
        if sql == backfill._AVAIL_INSERT
    ]
    days_inserted = sorted({p[2] for p in inserts})
    assert days_inserted == [1, 3, 5, 6, 7]  # Tue & Thu skipped


def test_default_fill_respects_exclude_test_members(
    tmp_path, monkeypatch
):
    """--exclude-test-members applies to default-fill too — Center IDs
    ending in '00' get neither HHA processing nor default seeding."""
    fake = _SmartFakeConn(
        contacts_rows=[],
        all_member_ids=[12300, 24010],
        existing_avail=[],
    )
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake)
    db_file = tmp_path / "x.accdb"
    db_file.touch()

    rc = backfill.main([
        "--db", str(db_file), "--csv-out", str(tmp_path),
        "--exclude-test-members",
    ])
    assert rc == 0
    inserts = [
        params for sql, params in fake._cursor.executed
        if sql == backfill._AVAIL_INSERT
    ]
    cids_inserted = {p[0] for p in inserts}
    assert cids_inserted == {"24010"}
    assert len(inserts) == 7


def test_default_fill_runs_after_hha_contacts_query(
    tmp_path, monkeypatch
):
    """The default-fill SELECT for all member IDs runs AFTER the HHA
    Contacts query, so any rows the HHA pass inserts are visible to
    the existence check."""
    fake = _SmartFakeConn(
        contacts_rows=[(24010, "Doe", "Jane", None)],  # No HHA text
        all_member_ids=[24010],
        existing_avail=[],
    )
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake)
    db_file = tmp_path / "x.accdb"
    db_file.touch()

    rc = backfill.main([
        "--db", str(db_file), "--csv-out", str(tmp_path),
    ])
    assert rc == 0
    sqls = [sql for sql, _ in fake._cursor.executed]
    contacts_idx = sqls.index(backfill._CONTACTS_QUERY)
    member_ids_idx = sqls.index(backfill._ALL_MEMBER_IDS_QUERY)
    assert contacts_idx < member_ids_idx


def test_default_fill_dry_run_rolls_back(tmp_path, monkeypatch):
    """--dry-run rolls back default-fill inserts along with HHA changes."""
    fake = _SmartFakeConn(
        contacts_rows=[],
        all_member_ids=[24010],
        existing_avail=[],
    )
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake)
    db_file = tmp_path / "x.accdb"
    db_file.touch()

    rc = backfill.main([
        "--db", str(db_file), "--csv-out", str(tmp_path), "--dry-run",
    ])
    assert rc == 0
    assert fake.rolled_back is True
    assert fake.committed is False
