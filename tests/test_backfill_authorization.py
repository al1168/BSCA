import os
import sys
from pathlib import Path

import pytest


# Ensure the script is importable as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import backfill_authorization_from_contacts as backfill


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
    for col in ("[Center ID]", "[Last Name]", "[First Name]",
                "[Health Plan]", "[SADC]", "[Auth BGN]", "[Auth EXP]"):
        assert col in q
    assert "FROM [Contacts]" in q
    assert "WHERE" not in q  # full table scan
    assert "ORDER BY [Center ID]" in q


def test_auth_select_query_for_member():
    q = backfill._AUTH_SELECT_FOR_MEMBER
    assert "[ID]" in q
    assert "[Health Plan]" in q
    assert "FROM [Authorization]" in q
    assert "WHERE [Center ID] = ?" in q


def test_auth_update_health_plan_query():
    q = backfill._AUTH_UPDATE_HEALTH_PLAN
    assert "UPDATE [Authorization]" in q
    assert "SET [Health Plan] = ?" in q
    assert "WHERE [ID] = ?" in q


def test_auth_insert_query_columns():
    q = backfill._AUTH_INSERT
    assert "INSERT INTO [Authorization]" in q
    for col in ("[Center ID]", "[auth_start]", "[auth_end]",
                "[effective_start]", "[effective_end]", "[auth_days]",
                "[Health Plan]", "[created_at]"):
        assert col in q
    # Eight values, no trailing commas, exactly eight `?` placeholders.
    assert q.count("?") == 8


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


def test_fmt_date_datetime():
    from datetime import datetime as _datetime
    assert backfill._fmt_date(_datetime(2026, 1, 1, 10, 30)) == "2026-01-01"


def test_fmt_date_string():
    assert backfill._fmt_date("2026-01-01") == "2026-01-01"
    assert backfill._fmt_date("1/1/2026") == "1/1/2026"


def test_coerce_date_none_and_blank():
    assert backfill._coerce_date(None) is None
    assert backfill._coerce_date("") is None
    assert backfill._coerce_date("   ") is None


def test_coerce_date_passthrough_datetime():
    from datetime import datetime as _datetime
    d = _datetime(2026, 1, 1, 10, 30)
    assert backfill._coerce_date(d) is d


def test_coerce_date_parses_common_formats():
    from datetime import datetime as _datetime
    assert backfill._coerce_date("2026-01-01") == _datetime(2026, 1, 1)
    assert backfill._coerce_date("1/1/2026") == _datetime(2026, 1, 1)
    assert backfill._coerce_date("01/01/2026") == _datetime(2026, 1, 1)
    assert backfill._coerce_date("1/1/26") == _datetime(2026, 1, 1)
    assert backfill._coerce_date("2026-01-01 00:00:00") == _datetime(2026, 1, 1)


def test_coerce_date_garbage_is_none():
    assert backfill._coerce_date("not a date") is None
    assert backfill._coerce_date("13/45/9999") is None


def test_is_blank():
    assert backfill._is_blank(None) is True
    assert backfill._is_blank("") is True
    assert backfill._is_blank("   ") is True
    assert backfill._is_blank("\t\n") is True
    assert backfill._is_blank("HOF") is False
    assert backfill._is_blank("  HOF  ") is False


def test_update_branch_fills_only_blank_rows():
    cur = FakeCursor()
    # Two existing rows: ID=10 blank, ID=11 already "HOFV2".
    cur.queue_fetchall([(10, None), (11, "HOFV2")])
    stats = {"updated_members": 0, "updated_rows": 0}
    result = backfill._process_update_branch(
        cur, center_id=24010, health_plan="HOF", stats=stats,
    )
    assert result == ("updated", 1)  # 1 row filled
    # Verify the SELECT then exactly one UPDATE on ID=10.
    selects = [(s, p) for s, p in cur.executed
               if s == backfill._AUTH_SELECT_FOR_MEMBER]
    updates = [(s, p) for s, p in cur.executed
               if s == backfill._AUTH_UPDATE_HEALTH_PLAN]
    assert selects == [(backfill._AUTH_SELECT_FOR_MEMBER, ("24010",))]
    assert updates == [(backfill._AUTH_UPDATE_HEALTH_PLAN, ("HOF", 10))]
    assert stats == {"updated_members": 1, "updated_rows": 1}


def test_update_branch_all_rows_already_filled():
    cur = FakeCursor()
    cur.queue_fetchall([(10, "HOF"), (11, "HOFV2")])
    stats = {"updated_members": 0, "updated_rows": 0}
    result = backfill._process_update_branch(
        cur, center_id=24010, health_plan="HOF", stats=stats,
    )
    assert result == ("noop", 0)
    # No UPDATE was issued.
    assert all(s != backfill._AUTH_UPDATE_HEALTH_PLAN
               for s, _ in cur.executed)
    assert stats == {"updated_members": 0, "updated_rows": 0}


def test_update_branch_skips_when_contacts_health_plan_blank():
    cur = FakeCursor()
    cur.queue_fetchall([(10, None)])
    stats = {"updated_members": 0, "updated_rows": 0}
    result = backfill._process_update_branch(
        cur, center_id=24010, health_plan="", stats=stats,
    )
    assert result == ("skipped_no_plan", 0)
    assert all(s != backfill._AUTH_UPDATE_HEALTH_PLAN
               for s, _ in cur.executed)
    assert stats == {"updated_members": 0, "updated_rows": 0}


from datetime import datetime as _dt


def test_insert_branch_happy_path():
    cur = FakeCursor()
    stats = {"inserted_members": 0}
    bgn = _dt(2026, 1, 1)
    exp = _dt(2026, 12, 31)
    result = backfill._process_insert_branch(
        cur, center_id=24010, sadc="1.3.5",
        auth_bgn=bgn, auth_exp=exp, health_plan="HOF", stats=stats,
    )
    assert result == ("inserted", None)
    inserts = [(s, p) for s, p in cur.executed
               if s == backfill._AUTH_INSERT]
    assert len(inserts) == 1
    _, params = inserts[0]
    # ([Center ID], auth_start, auth_end, eff_start, eff_end,
    #  auth_days, [Health Plan], created_at)
    assert params[:7] == ("24010", bgn, exp, bgn, exp, "1,3,5", "HOF")
    # created_at is set to "now" — assert it's a fresh datetime
    # rather than pinning to an exact value.
    import datetime as _dt_mod
    assert isinstance(params[7], _dt_mod.datetime)
    assert (_dt_mod.datetime.now() - params[7]).total_seconds() < 5
    assert stats["inserted_members"] == 1


def test_insert_branch_skip_missing_all():
    cur = FakeCursor()
    stats = {"inserted_members": 0}
    result = backfill._process_insert_branch(
        cur, center_id=24010, sadc=None,
        auth_bgn=None, auth_exp=None, health_plan="", stats=stats,
    )
    assert result == ("skipped_missing", ["SADC", "Auth BGN",
                                          "Auth EXP", "Health Plan"])
    # No INSERT was issued.
    assert all(s != backfill._AUTH_INSERT for s, _ in cur.executed)
    assert stats["inserted_members"] == 0


def test_insert_branch_skip_missing_subset():
    cur = FakeCursor()
    stats = {"inserted_members": 0}
    result = backfill._process_insert_branch(
        cur, center_id=24010, sadc="1,3,5",
        auth_bgn=_dt(2026, 1, 1), auth_exp=None,
        health_plan="HOF", stats=stats,
    )
    assert result == ("skipped_missing", ["Auth EXP"])
    assert stats["inserted_members"] == 0


def test_insert_branch_sadc_garbage_treated_as_missing():
    cur = FakeCursor()
    stats = {"inserted_members": 0}
    # "TBD" parses to an empty set of weekdays.
    result = backfill._process_insert_branch(
        cur, center_id=24010, sadc="TBD",
        auth_bgn=_dt(2026, 1, 1), auth_exp=_dt(2026, 12, 31),
        health_plan="HOF", stats=stats,
    )
    assert result == ("skipped_missing", ["SADC"])
    assert stats["inserted_members"] == 0


def test_insert_branch_parses_string_dates():
    cur = FakeCursor()
    stats = {"inserted_members": 0}
    result = backfill._process_insert_branch(
        cur, center_id=24010, sadc="1,3,5",
        auth_bgn="1/1/2026", auth_exp="12/31/2026",
        health_plan="HOF", stats=stats,
    )
    assert result == ("inserted", None)
    inserts = [(s, p) for s, p in cur.executed
               if s == backfill._AUTH_INSERT]
    assert len(inserts) == 1
    _, params = inserts[0]
    # The string dates must be normalized to datetime before binding.
    assert params[:7] == (
        "24010", _dt(2026, 1, 1), _dt(2026, 12, 31),
        _dt(2026, 1, 1), _dt(2026, 12, 31), "1,3,5", "HOF",
    )
    # created_at is a fresh now-timestamp.
    import datetime as _dt_mod
    assert isinstance(params[7], _dt_mod.datetime)


def test_insert_branch_unparseable_date_treated_as_missing():
    cur = FakeCursor()
    stats = {"inserted_members": 0}
    result = backfill._process_insert_branch(
        cur, center_id=24010, sadc="1,3,5",
        auth_bgn="not a date", auth_exp="12/31/2026",
        health_plan="HOF", stats=stats,
    )
    assert result == ("skipped_missing", ["Auth BGN"])
    assert all(s != backfill._AUTH_INSERT for s, _ in cur.executed)


import csv
import datetime


def test_write_skipped_csv_header_only(tmp_path):
    path = backfill._write_skipped_csv(
        [], str(tmp_path), datetime.date(2026, 6, 2),
    )
    assert path.endswith("auth_backfill_skipped_2026-06-02.csv")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows == [["center_id", "last_name", "first_name",
                     "action", "missing_fields"]]


def test_write_skipped_csv_with_rows(tmp_path):
    rows_in = [
        {"center_id": 24012, "last_name": "Wong", "first_name": "Mei",
         "action": "no_health_plan_for_update",
         "missing_fields": "Health Plan"},
        {"center_id": 24013, "last_name": "Chen", "first_name": "Li",
         "action": "missing_legacy_fields",
         "missing_fields": "SADC; Auth EXP"},
    ]
    path = backfill._write_skipped_csv(
        rows_in, str(tmp_path), datetime.date(2026, 6, 2),
    )
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows == [
        {"center_id": "24012", "last_name": "Wong", "first_name": "Mei",
         "action": "no_health_plan_for_update",
         "missing_fields": "Health Plan"},
        {"center_id": "24013", "last_name": "Chen", "first_name": "Li",
         "action": "missing_legacy_fields",
         "missing_fields": "SADC; Auth EXP"},
    ]


def test_write_skipped_csv_creates_output_dir(tmp_path):
    out = tmp_path / "nested" / "dir"
    path = backfill._write_skipped_csv(
        [], str(out), datetime.date(2026, 6, 2),
    )
    assert os.path.exists(path)


def test_read_contacts_skips_null_center_id():
    class StubConn:
        def cursor(self):
            return self

        def execute(self, sql):
            self.sql = sql
            return self

        def fetchall(self):
            return [
                (None, "Skip", "Me", "HOF", "1,3,5", None, None),
                (24010, "Real", "One", "HOF", "1,3,5", None, None),
            ]

    conn = StubConn()
    rows = list(backfill._read_contacts(conn))
    assert len(rows) == 1
    assert rows[0][0] == 24010  # int
    assert conn.sql == backfill._CONTACTS_QUERY


# ---------------------------------------------------------------------------
# Tests for --exclude-test-members
# ---------------------------------------------------------------------------

def test_is_test_id_true_cases():
    assert backfill._is_test_id(12300) is True
    assert backfill._is_test_id(99500) is True
    assert backfill._is_test_id(100) is True


def test_is_test_id_false_cases():
    assert backfill._is_test_id(12345) is False
    assert backfill._is_test_id(99999) is False
    assert backfill._is_test_id(99501) is False


def test_help_lists_exclude_test_members():
    ns = backfill._parse_args(["--db", "x"])
    assert hasattr(ns, "exclude_test_members")
    assert ns.exclude_test_members is False

    ns2 = backfill._parse_args(["--db", "x", "--exclude-test-members"])
    assert ns2.exclude_test_members is True


class _FakeConn:
    """Minimal pyodbc connection stand-in for main() integration tests.

    contacts_rows — rows returned by the first fetchall() (the _CONTACTS_QUERY).
    Each subsequent fetchall() returns [] (no existing Authorization rows).
    """
    def __init__(self, contacts_rows):
        self._contacts_rows = contacts_rows
        self._cursor = None
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        if self._cursor is None:
            self._cursor = _FakeConnCursor(self._contacts_rows)
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class _FakeConnCursor:
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
        # Subsequent fetchall calls (e.g. _AUTH_SELECT_FOR_MEMBER) → no rows.
        return []

    def fetchone(self):
        return None


def test_summary_shows_test_skipped_zero_without_flag(tmp_path, capsys, monkeypatch):
    fake_conn = _FakeConn(contacts_rows=[])
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake_conn)

    # Use a fake db path that exists (tmp_path itself is a dir; we need a file).
    db_file = tmp_path / "test.accdb"
    db_file.touch()

    rc = backfill.main(["--db", str(db_file), "--csv-out", str(tmp_path)])
    assert rc == 0

    out = capsys.readouterr().out
    assert "Test members excluded (--exclude-test-members): 0" in out


def test_exclude_test_members_skips_trailing_00_before_auth_lookup(
    tmp_path, capsys, monkeypatch
):
    # Contact with cid=12300 (ends in 00).
    contacts_rows = [(12300, "Doe", "John", "HOF", "1,3,5", None, None)]
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
    # _AUTH_SELECT_FOR_MEMBER, _AUTH_INSERT, _AUTH_UPDATE_HEALTH_PLAN must
    # never have been called.
    executed_sqls = [sql for sql, _ in cur.executed]
    assert backfill._AUTH_SELECT_FOR_MEMBER not in executed_sqls
    assert backfill._AUTH_INSERT not in executed_sqls
    assert backfill._AUTH_UPDATE_HEALTH_PLAN not in executed_sqls

    out = capsys.readouterr().out
    assert "Test members excluded (--exclude-test-members): 1" in out

    # Without --dry-run, commit should have been called.
    assert fake_conn.committed is True
