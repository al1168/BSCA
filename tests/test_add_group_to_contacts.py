import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import add_group_to_contacts as migration


def test_build_connection_string():
    cs = migration._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


def test_alter_statement_shape():
    q = migration._ALTER_ADD_GROUP
    assert "ALTER TABLE [Contacts]" in q
    assert "ADD COLUMN [Group]" in q
    assert "TEXT(255)" in q


def test_update_statement_only_touches_blank_rows():
    q = migration._UPDATE_BLANK_GROUP
    assert q.startswith("UPDATE [Contacts] SET [Group] = ?")
    assert "[Group] IS NULL" in q
    assert "[Group] = ''" in q


def test_parse_args_defaults():
    ns = migration._parse_args(["--db", "x"])
    assert ns.db == "x"
    assert ns.group == ""
    assert ns.quiet is False


def test_parse_args_group_and_quiet():
    ns = migration._parse_args(["--db", "x", "--group", "A", "--quiet"])
    assert ns.group == "A"
    assert ns.quiet is True


def test_main_missing_db_returns_2(tmp_path, capsys):
    missing = tmp_path / "nope.accdb"
    rc = migration.main(["--db", str(missing)])
    assert rc == 2
    assert "database not found" in capsys.readouterr().err.lower()


class _FakeCursor:
    def __init__(self, existing_columns, update_rowcount=3):
        self._existing = list(existing_columns)
        self._update_rowcount = update_rowcount
        self.executed = []
        self.rowcount = -1

    def columns(self, table):
        rows = [
            SimpleNamespace(column_name=name)
            for name in self._existing
        ]
        return SimpleNamespace(fetchall=lambda: rows)

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        if sql.startswith("UPDATE"):
            self.rowcount = self._update_rowcount
        else:
            self.rowcount = -1
        return self


def test_column_exists_true_case_insensitive():
    cur = _FakeCursor(existing_columns=["Center ID", "Group"])
    assert migration._column_exists(cur, "Contacts", "Group") is True
    assert migration._column_exists(cur, "Contacts", "group") is True


def test_column_exists_false_when_absent():
    cur = _FakeCursor(existing_columns=["Center ID", "Health Plan"])
    assert migration._column_exists(cur, "Contacts", "Group") is False


class _FakeConn:
    def __init__(self, existing_columns, update_rowcount=3):
        self._cursor = _FakeCursor(existing_columns, update_rowcount)
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        pass


def _touch_db(tmp_path):
    db_file = tmp_path / "test.accdb"
    db_file.touch()
    return str(db_file)


def test_main_adds_column_without_group_text(tmp_path, capsys, monkeypatch):
    fake_conn = _FakeConn(existing_columns=["Center ID"])
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake_conn)

    rc = migration.main(["--db", _touch_db(tmp_path)])
    assert rc == 0
    executed = fake_conn._cursor.executed
    assert executed == [(migration._ALTER_ADD_GROUP, ())]
    assert fake_conn.committed is True
    out = capsys.readouterr().out
    assert "Added: Contacts.[Group]" in out
    assert "Filled" not in out


def test_main_blank_group_text_is_treated_as_absent(
    tmp_path, capsys, monkeypatch,
):
    fake_conn = _FakeConn(existing_columns=["Center ID", "Group"])
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake_conn)

    rc = migration.main(["--db", _touch_db(tmp_path), "--group", "   "])
    assert rc == 0
    assert fake_conn._cursor.executed == []
    out = capsys.readouterr().out
    assert "already exists" in out.lower()
    assert "Filled" not in out


def test_main_adds_column_then_fills_blank_rows(
    tmp_path, capsys, monkeypatch,
):
    fake_conn = _FakeConn(existing_columns=["Center ID"], update_rowcount=7)
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake_conn)

    rc = migration.main(["--db", _touch_db(tmp_path), "--group", " B "])
    assert rc == 0
    assert fake_conn._cursor.executed == [
        (migration._ALTER_ADD_GROUP, ()),
        (migration._UPDATE_BLANK_GROUP, ("B",)),
    ]
    assert fake_conn.committed is True
    out = capsys.readouterr().out
    assert "Added: Contacts.[Group]" in out
    assert "Filled 7 Contacts row(s) with Group = 'B'" in out


def test_main_existing_column_only_fills(tmp_path, capsys, monkeypatch):
    fake_conn = _FakeConn(
        existing_columns=["Center ID", "Group"], update_rowcount=0,
    )
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake_conn)

    rc = migration.main(["--db", _touch_db(tmp_path), "--group", "Blue"])
    assert rc == 0
    assert fake_conn._cursor.executed == [
        (migration._UPDATE_BLANK_GROUP, ("Blue",)),
    ]
    assert fake_conn.committed is True
    out = capsys.readouterr().out
    assert "already exists" in out.lower()
    assert "Filled 0 Contacts row(s) with Group = 'Blue'" in out
