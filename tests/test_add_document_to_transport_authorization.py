import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import add_document_to_transport_authorization as migration


def test_dao_attachment_constant():
    """dbAttachment = 101 — the DAO Field.Type value for the native
    Access ATTACHMENT type."""
    assert migration.DAO_ATTACHMENT == 101


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


def _make_table_def(field_names):
    """Build a MagicMock TableDef whose Fields iteration yields
    MagicMocks with a `.Name` attribute, and whose `CreateField` /
    `Fields.Append` calls are inspectable. `side_effect` returns a
    fresh iterator each time so multiple iterations work."""
    fields = []
    for name in field_names:
        f = MagicMock()
        f.Name = name
        fields.append(f)
    td = MagicMock()
    td.Fields.__iter__.side_effect = lambda: iter(fields)
    return td


def test_field_exists_case_insensitive():
    td = _make_table_def(["Center ID", "auth_days", "Document"])
    assert migration._field_exists(td, "Document") is True
    assert migration._field_exists(td, "document") is True


def test_field_exists_returns_false_when_absent():
    td = _make_table_def(["Center ID", "auth_days", "Health Plan"])
    assert migration._field_exists(td, "Document") is False


def test_main_skips_when_field_already_exists(tmp_path, capsys, monkeypatch):
    """If [Document] is already on the table, no CreateField / Append
    happens and the script reports 'already exists'."""
    td = _make_table_def(["Center ID", "Document"])
    db = MagicMock()
    db.TableDefs.return_value = td

    monkeypatch.setattr(migration, "_open_database", lambda path: db)

    db_file = tmp_path / "test.accdb"
    db_file.touch()

    rc = migration.main(["--db", str(db_file)])
    assert rc == 0
    td.CreateField.assert_not_called()
    td.Fields.Append.assert_not_called()
    db.Close.assert_called_once()
    out = capsys.readouterr().out
    assert "already exists" in out.lower()


def test_main_adds_attachment_field_when_absent(
    tmp_path, capsys, monkeypatch,
):
    """When [Document] is missing, the script calls CreateField with
    DAO_ATTACHMENT and appends it to TransportAuthorization."""
    td = _make_table_def(["Center ID", "auth_days"])
    created_field = MagicMock()
    td.CreateField.return_value = created_field
    db = MagicMock()
    db.TableDefs.return_value = td

    monkeypatch.setattr(migration, "_open_database", lambda path: db)

    db_file = tmp_path / "test.accdb"
    db_file.touch()

    rc = migration.main(["--db", str(db_file)])
    assert rc == 0
    # Opened the TransportAuthorization table (not Authorization).
    db.TableDefs.assert_called_once_with("TransportAuthorization")
    td.CreateField.assert_called_once_with(
        "Document", migration.DAO_ATTACHMENT,
    )
    td.Fields.Append.assert_called_once_with(created_field)
    db.Close.assert_called_once()
    out = capsys.readouterr().out
    assert "Added: TransportAuthorization.[Document]" in out


def test_main_surfaces_dao_open_error(tmp_path, capsys, monkeypatch):
    """If _open_database raises (e.g. pywin32 missing, DAO engine not
    installed), main returns 2 with a clear stderr message."""
    def boom(path):
        raise RuntimeError("DAO engine not registered")
    monkeypatch.setattr(migration, "_open_database", boom)

    db_file = tmp_path / "test.accdb"
    db_file.touch()

    rc = migration.main(["--db", str(db_file)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "DAO engine not registered" in err
