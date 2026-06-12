import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import create_supporting_tables as build


def test_build_connection_string():
    cs = build._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


def test_main_missing_db_returns_2(tmp_path, capsys):
    missing = tmp_path / "nope.accdb"
    rc = build.main(["--db", str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "database not found" in err.lower()


def test_create_enrollment_ddl():
    q = build._CREATE_ENROLLMENT
    assert "CREATE TABLE [Enrollment]" in q
    assert "[ID] AUTOINCREMENT PRIMARY KEY" in q
    for col in ("[Center ID]", "[start_date]", "[end_date]"):
        assert col in q


def test_create_authorization_ddl():
    q = build._CREATE_AUTHORIZATION
    assert "CREATE TABLE [Authorization]" in q
    assert "[ID] AUTOINCREMENT PRIMARY KEY" in q
    for col in ("[Center ID]", "[auth_start]", "[auth_end]",
                "[effective_start]", "[effective_end]", "[auth_days]",
                "[notes]", "[Health Plan]"):
        assert col in q


def test_create_absences_ddl():
    q = build._CREATE_ABSENCES
    assert "CREATE TABLE [Absences]" in q
    assert "[ID] AUTOINCREMENT PRIMARY KEY" in q
    for col in ("[Center ID]", "[Leave Type]", "[Start_Date]",
                "[End_Date]", "[Notes]"):
        assert col in q


def test_create_availability_ddl():
    q = build._CREATE_AVAILABILITY
    assert "CREATE TABLE [Availability]" in q
    assert "[ID] AUTOINCREMENT PRIMARY KEY" in q
    for col in ("[Center ID]", "[effective_start_date]",
                "[effective_end_date]", "[Day Of Week]",
                "[avail_start]", "[avail_end]", "[Notes]"):
        assert col in q


def test_create_one_off_availability_ddl():
    q = build._CREATE_ONE_OFF_AVAILABILITY
    assert "CREATE TABLE [OneOffAvailability]" in q
    assert "[ID] AUTOINCREMENT PRIMARY KEY" in q
    for col in ("[Center ID]", "[date]", "[avail_start]", "[avail_end]", "[Notes]"):
        assert col in q


def test_create_emergency_contact_ddl():
    q = build._CREATE_EMERGENCY_CONTACT
    assert "CREATE TABLE [EmergencyContact]" in q
    assert "[ID] AUTOINCREMENT PRIMARY KEY" in q
    for col in ("[Center ID]", "[Full Name]", "[Phone Number]", "[Relationship]"):
        assert col in q


def test_ddls_in_declared_order():
    assert build._DDLS == [
        ("Enrollment", build._CREATE_ENROLLMENT),
        ("Authorization", build._CREATE_AUTHORIZATION),
        ("Absences", build._CREATE_ABSENCES),
        ("Availability", build._CREATE_AVAILABILITY),
        ("OneOffAvailability", build._CREATE_ONE_OFF_AVAILABILITY),
        ("EmergencyContact", build._CREATE_EMERGENCY_CONTACT),
    ]


def test_authorization_ddl_has_document_column():
    """The Authorization DDL includes the [Document] OLEOBJECT
    column for storing the embedded PDF/DOC bytes of the auth."""
    q = build._CREATE_AUTHORIZATION
    assert "[Document] OLEOBJECT" in q
