import pytest

from monthly_schedule.db import (
    build_connection_string,
    map_member_row,
    MEMBER_QUERY,
    get_member,
)


def test_build_connection_string():
    cs = build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


def test_member_query_columns_and_filter():
    assert "[Center ID]" in MEMBER_QUERY
    assert "[Last Name]" in MEMBER_QUERY
    assert "[First Name]" in MEMBER_QUERY
    assert "[Health Plan]" in MEMBER_QUERY
    assert "[SADC Auth]" in MEMBER_QUERY
    assert "WHERE [Center ID] = ?" in MEMBER_QUERY


def test_map_member_row():
    row = (24010, "Cheng", "Lizhu", "Elderplan Homefirst", "1.3.4.5")
    assert map_member_row(row) == {
        "center_id": 24010,
        "last_name": "Cheng",
        "first_name": "Lizhu",
        "health_plan": "Elderplan Homefirst",
        "sadc_auth": "1.3.4.5",
    }


def test_get_member_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_member(24010, str(missing))
