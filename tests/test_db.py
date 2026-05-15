import pytest

from monthly_schedule.db import (
    build_connection_string,
    map_member_row,
    MEMBER_QUERY,
    MEMBERS_BY_PLAN_QUERY,
    get_member,
    get_members_by_plan,
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
    assert "[SADC]" in MEMBER_QUERY
    assert "[SADC Auth]" not in MEMBER_QUERY
    assert "WHERE [Center ID] = ?" in MEMBER_QUERY


def test_map_member_row():
    # Access returns [Center ID] as a float (e.g. 24010.0); it must be
    # normalized to an int so the header reads "ID: 24010" not "24010.0".
    row = (24010.0, "Cheng", "Lizhu", "Elderplan Homefirst", "1.3.4.5")
    result = map_member_row(row)
    assert result["center_id"] == 24010
    assert isinstance(result["center_id"], int)
    assert result == {
        "center_id": 24010,
        "last_name": "Cheng",
        "first_name": "Lizhu",
        "health_plan": "Elderplan Homefirst",
        "auth_days": "1.3.4.5",
    }


def test_get_member_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_member(24010, str(missing))


def test_members_by_plan_query_columns_and_filter():
    assert "[Center ID]" in MEMBERS_BY_PLAN_QUERY
    assert "[Last Name]" in MEMBERS_BY_PLAN_QUERY
    assert "[First Name]" in MEMBERS_BY_PLAN_QUERY
    assert "[Health Plan]" in MEMBERS_BY_PLAN_QUERY
    assert "[SADC]" in MEMBERS_BY_PLAN_QUERY
    assert "WHERE [Health Plan] = ?" in MEMBERS_BY_PLAN_QUERY
    assert "ORDER BY [Center ID]" in MEMBERS_BY_PLAN_QUERY


def test_get_members_by_plan_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_members_by_plan("HOF", str(missing))
