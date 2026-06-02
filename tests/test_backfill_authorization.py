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
                "[Health Plan]"):
        assert col in q
    # Seven values, no trailing commas, exactly seven `?` placeholders.
    assert q.count("?") == 7
