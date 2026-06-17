import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import add_created_at_to_authorization as migration


def test_build_connection_string():
    cs = migration._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


def test_alter_statement_shape():
    q = migration._ALTER_ADD_CREATED_AT
    assert "ALTER TABLE [Authorization]" in q
    assert "ADD COLUMN [created_at]" in q
    assert "DATETIME" in q


def test_parse_args_quiet_default_off():
    ns = migration._parse_args(["--db", "x"])
    assert ns.db == "x"
    assert ns.quiet is False


def test_parse_args_quiet_on():
    ns = migration._parse_args(["--db", "x", "--quiet"])
    assert ns.quiet is True


def test_main_missing_db_returns_2(tmp_path, capsys):
    missing = tmp_path / "nope.accdb"
    rc = migration.main(["--db", str(missing)])
    assert rc == 2
    assert "database not found" in capsys.readouterr().err.lower()


class _FakeCursor:
    def __init__(self, existing_columns):
        self._existing = list(existing_columns)
        self.executed = []

    def columns(self, table):
        rows = [
            SimpleNamespace(column_name=name)
            for name in self._existing
        ]
        return SimpleNamespace(fetchall=lambda: rows)

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self


def test_column_exists_true_case_insensitive():
    cur = _FakeCursor(
        existing_columns=["Center ID", "auth_days", "created_at"],
    )
    assert migration._column_exists(
        cur, "Authorization", "created_at",
    ) is True
    # Case-insensitive lookup.
    assert migration._column_exists(
        cur, "Authorization", "CREATED_AT",
    ) is True


def test_column_exists_false_when_absent():
    cur = _FakeCursor(
        existing_columns=["Center ID", "auth_days", "Health Plan"],
    )
    assert migration._column_exists(
        cur, "Authorization", "created_at",
    ) is False


class _FakeConn:
    def __init__(self, existing_columns):
        self._cursor = _FakeCursor(existing_columns)
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        pass


def test_main_skips_when_column_already_exists(tmp_path, capsys, monkeypatch):
    fake_conn = _FakeConn(existing_columns=["Center ID", "created_at"])
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake_conn)
    db_file = tmp_path / "test.accdb"
    db_file.touch()

    rc = migration.main(["--db", str(db_file)])
    assert rc == 0
    assert fake_conn._cursor.executed == []  # no ALTER
    assert fake_conn.committed is False
    out = capsys.readouterr().out
    assert "already exists" in out.lower()


def test_main_adds_column_when_absent(tmp_path, capsys, monkeypatch):
    fake_conn = _FakeConn(existing_columns=["Center ID", "auth_days"])
    monkeypatch.setattr("pyodbc.connect", lambda cs: fake_conn)
    db_file = tmp_path / "test.accdb"
    db_file.touch()

    rc = migration.main(["--db", str(db_file)])
    assert rc == 0
    # Exactly one ALTER was executed.
    executed_sqls = [sql for sql, _ in fake_conn._cursor.executed]
    assert executed_sqls == [migration._ALTER_ADD_CREATED_AT]
    assert fake_conn.committed is True
    out = capsys.readouterr().out
    assert "Added: Authorization.[created_at]" in out
