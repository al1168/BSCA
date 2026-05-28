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
    assert "[SADC]" not in MEMBER_QUERY
    assert "[Address]" in MEMBER_QUERY
    assert "[Long Lat]" in MEMBER_QUERY
    assert "[SADC Auth]" not in MEMBER_QUERY
    assert "WHERE [Center ID] = ?" in MEMBER_QUERY


def test_map_member_row():
    # Access returns [Center ID] as a float; normalize to int.
    row = (24010.0, "Cheng", "Lizhu", "Elderplan Homefirst",
           "1 Main St, NY", "40.71,-73.99")
    result = map_member_row(row)
    assert result == {
        "center_id": 24010,
        "last_name": "Cheng",
        "first_name": "Lizhu",
        "health_plan": "Elderplan Homefirst",
        "address": "1 Main St, NY",
        "long_lat": "40.71,-73.99",
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
    assert "[SADC]" not in MEMBERS_BY_PLAN_QUERY
    assert "[Address]" in MEMBERS_BY_PLAN_QUERY
    assert "[Long Lat]" in MEMBERS_BY_PLAN_QUERY
    assert "WHERE [Health Plan] = ?" in MEMBERS_BY_PLAN_QUERY
    assert "ORDER BY [Center ID]" in MEMBERS_BY_PLAN_QUERY


def test_get_members_by_plan_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_members_by_plan("HOF", str(missing))


from monthly_schedule.db import (
    ENROLLMENTS_QUERY,
    AUTHORIZATIONS_QUERY,
    ABSENCES_QUERY,
    AVAILABILITY_QUERY,
    get_enrollments,
    get_authorizations,
    get_absences,
    get_availability,
    map_enrollment_row,
    map_authorization_row,
    map_absence_row,
    map_availability_row,
)


def test_enrollments_query_columns_and_filter():
    assert "[Center ID]" in ENROLLMENTS_QUERY
    assert "[start_date]" in ENROLLMENTS_QUERY
    assert "[end_date]" in ENROLLMENTS_QUERY
    assert "FROM [Enrollment]" in ENROLLMENTS_QUERY
    assert "WHERE [Center ID] = ?" in ENROLLMENTS_QUERY


def test_authorizations_query_columns_and_filter():
    for col in ("[Center ID]", "[auth_start]", "[auth_end]",
                "[effective_start]", "[effective_end]", "[auth_days]"):
        assert col in AUTHORIZATIONS_QUERY
    assert "FROM [Authorization]" in AUTHORIZATIONS_QUERY
    assert "WHERE [Center ID] = ?" in AUTHORIZATIONS_QUERY


def test_absences_query_columns_and_filter():
    for col in ("[Center ID]", "[Leave Type]", "[Start_Date]", "[End_Date]"):
        assert col in ABSENCES_QUERY
    assert "FROM [Absences]" in ABSENCES_QUERY
    assert "WHERE [Center ID] = ?" in ABSENCES_QUERY


def test_availability_query_columns_and_filter():
    for col in ("[Center ID]", "[effective_start_date]",
                "[effective_end_date]", "[Day Of Week]",
                "[avail_start]", "[avail_end]"):
        assert col in AVAILABILITY_QUERY
    assert "FROM [Availability]" in AVAILABILITY_QUERY
    assert "WHERE [Center ID] = ?" in AVAILABILITY_QUERY


def test_map_enrollment_row():
    from datetime import date
    row = (1, 24010.0, date(2026, 1, 1), None)
    assert map_enrollment_row(row) == {
        "id": 1,
        "center_id": 24010,
        "start_date": date(2026, 1, 1),
        "end_date": None,
    }


def test_map_authorization_row():
    from datetime import date
    row = (5, 24010.0, date(2026, 1, 1), date(2026, 12, 31),
           date(2026, 1, 1), date(2026, 6, 30), "1,3,5")
    assert map_authorization_row(row) == {
        "id": 5,
        "center_id": 24010,
        "auth_start": date(2026, 1, 1),
        "auth_end": date(2026, 12, 31),
        "effective_start": date(2026, 1, 1),
        "effective_end": date(2026, 6, 30),
        "auth_days": "1,3,5",
    }


def test_map_absence_row():
    from datetime import date
    row = (7, 24010.0, "Vacation", date(2026, 5, 10), date(2026, 5, 16))
    assert map_absence_row(row) == {
        "id": 7,
        "center_id": 24010,
        "leave_type": "Vacation",
        "start_date": date(2026, 5, 10),
        "end_date": date(2026, 5, 16),
    }


def test_map_availability_row():
    from datetime import date, datetime
    # Access returns avail_start/avail_end as DATETIME with a placeholder
    # 1899-12-30 date; the mapper extracts the time portion as 'HH:MM'.
    row = (3, 24010.0, date(2026, 1, 1), None, 2,
           datetime(1899, 12, 30, 10, 0), datetime(1899, 12, 30, 15, 0))
    assert map_availability_row(row) == {
        "id": 3,
        "center_id": 24010,
        "effective_start_date": date(2026, 1, 1),
        "effective_end_date": None,
        "day_of_week": 2,
        "avail_start": "10:00",
        "avail_end": "15:00",
    }


def test_map_availability_row_handles_null_times():
    from monthly_schedule.db import map_availability_row
    from datetime import date
    row = (3, 24010.0, date(2026, 1, 1), None, 2, None, None)
    assert map_availability_row(row)["avail_start"] is None
    assert map_availability_row(row)["avail_end"] is None


def test_map_authorization_row_nullable_effective_dates():
    from datetime import date
    from monthly_schedule.db import map_authorization_row
    # effective_start / effective_end NULL → fall back to auth_start / auth_end
    row = (5, 24010.0, date(2026, 1, 1), date(2026, 12, 31),
           None, None, "1,3,5")
    result = map_authorization_row(row)
    assert result["effective_start"] == date(2026, 1, 1)
    assert result["effective_end"] == date(2026, 12, 31)


def test_get_enrollments_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_enrollments(24010, str(missing))


def test_get_authorizations_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_authorizations(24010, str(missing))


def test_get_absences_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_absences(24010, str(missing))


def test_get_availability_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_availability(24010, str(missing))
