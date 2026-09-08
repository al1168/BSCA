import sys
import types
from datetime import date, datetime

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
                "[effective_start]", "[effective_end]", "[auth_days]",
                "[Member ID]", "[Plan Type]"):
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
           date(2026, 1, 1), date(2026, 6, 30), "1,3,5", "134972571",
           "MAP")
    assert map_authorization_row(row) == {
        "id": 5,
        "center_id": 24010,
        "auth_start": date(2026, 1, 1),
        "auth_end": date(2026, 12, 31),
        "effective_start": date(2026, 1, 1),
        "effective_end": date(2026, 6, 30),
        "auth_days": "1,3,5",
        "member_id": "134972571",
        "plan_type": "MAP",
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
           None, None, "1,3,5", None, None)
    result = map_authorization_row(row)
    assert result["effective_start"] == date(2026, 1, 1)
    assert result["effective_end"] == date(2026, 12, 31)
    assert result["member_id"] is None
    assert result["plan_type"] is None


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


def test_all_members_query_columns_and_no_filter():
    from monthly_schedule.db import ALL_MEMBERS_QUERY
    for col in ("[Center ID]", "[Last Name]", "[First Name]",
                "[Health Plan]", "[Address]", "[Long Lat]"):
        assert col in ALL_MEMBERS_QUERY
    assert "FROM [Contacts]" in ALL_MEMBERS_QUERY
    assert "ORDER BY [Center ID]" in ALL_MEMBERS_QUERY
    # No WHERE clause — fetches every row.
    assert "WHERE" not in ALL_MEMBERS_QUERY


def test_get_all_members_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_all_members
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_all_members(str(missing))


def test_all_enrollments_query_columns_and_no_filter():
    from monthly_schedule.db import ALL_ENROLLMENTS_QUERY
    for col in ("[ID]", "[Center ID]", "[start_date]", "[end_date]"):
        assert col in ALL_ENROLLMENTS_QUERY
    assert "FROM [Enrollment]" in ALL_ENROLLMENTS_QUERY
    assert "WHERE" not in ALL_ENROLLMENTS_QUERY


def test_all_authorizations_query_columns_and_no_filter():
    from monthly_schedule.db import ALL_AUTHORIZATIONS_QUERY
    for col in ("[ID]", "[Center ID]", "[auth_start]", "[auth_end]",
                "[effective_start]", "[effective_end]", "[auth_days]",
                "[Member ID]", "[Plan Type]"):
        assert col in ALL_AUTHORIZATIONS_QUERY
    assert "FROM [Authorization]" in ALL_AUTHORIZATIONS_QUERY
    assert "WHERE" not in ALL_AUTHORIZATIONS_QUERY


def test_all_absences_query_columns_and_no_filter():
    from monthly_schedule.db import ALL_ABSENCES_QUERY
    for col in ("[ID]", "[Center ID]", "[Leave Type]",
                "[Start_Date]", "[End_Date]"):
        assert col in ALL_ABSENCES_QUERY
    assert "FROM [Absences]" in ALL_ABSENCES_QUERY
    assert "WHERE" not in ALL_ABSENCES_QUERY


def test_all_availability_query_columns_and_no_filter():
    from monthly_schedule.db import ALL_AVAILABILITY_QUERY
    for col in ("[ID]", "[Center ID]", "[effective_start_date]",
                "[effective_end_date]", "[Day Of Week]",
                "[avail_start]", "[avail_end]"):
        assert col in ALL_AVAILABILITY_QUERY
    assert "FROM [Availability]" in ALL_AVAILABILITY_QUERY
    assert "WHERE" not in ALL_AVAILABILITY_QUERY


def test_get_all_enrollments_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_all_enrollments
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_all_enrollments(str(missing))


def test_get_all_authorizations_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_all_authorizations
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_all_authorizations(str(missing))


def test_get_all_absences_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_all_absences
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_all_absences(str(missing))


def test_get_all_availability_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_all_availability
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_all_availability(str(missing))


from monthly_schedule.db import (
    PLAN_TOTALS_QUERY,
    PLAN_ACTIVE_QUERY,
    merge_plan_counts,
    get_plan_member_counts,
)


def test_plan_totals_query_shape():
    q = PLAN_TOTALS_QUERY
    assert "[Health Plan]" in q
    assert "COUNT(*)" in q
    assert "[Contacts]" in q
    assert "[Center ID] IS NOT NULL" in q
    assert "GROUP BY" in q


def test_plan_active_query_shape():
    q = PLAN_ACTIVE_QUERY
    assert "EXISTS" in q
    assert "[Enrollment]" in q
    assert "e.[start_date] <= ?" in q
    assert "e.[end_date] IS NULL OR e.[end_date] >= ?" in q
    assert "GROUP BY" in q
    # COUNT(DISTINCT ...) is not valid Access SQL — the EXISTS form is required.
    assert "DISTINCT" not in q


def test_merge_plan_counts_math():
    totals = [("HF", 100), ("BCBS", 50)]
    active = [("HF", 96), ("BCBS", 44)]
    out = merge_plan_counts(totals, active)
    assert out["plans"]["HF"] == {"total": 100, "active": 96}
    assert out["plans"]["BCBS"] == {"total": 50, "active": 44}
    assert out["total_active"] == 140


def test_merge_plan_counts_normalizes_codes():
    # Access text comparison is case-insensitive and users hand-type
    # plan codes — ' hf ' and 'HF' are the same plan.
    out = merge_plan_counts([(" hf ", 2), ("HF", 3)], [("hf", 4)])
    assert out["plans"]["HF"] == {"total": 5, "active": 4}
    assert out["total_active"] == 4


def test_merge_plan_counts_blank_plan_bucketed():
    # NULL/blank Health Plan rows count under "" so the All Members
    # total stays honest (All Members runs schedule everyone).
    out = merge_plan_counts([(None, 7), ("", 1)], [(None, 3)])
    assert out["plans"][""] == {"total": 8, "active": 3}
    assert out["total_active"] == 3


def test_merge_plan_counts_active_plan_missing_from_totals():
    # Defensive: an active row for a plan absent from totals must not crash.
    out = merge_plan_counts([], [("HF", 2)])
    assert out["plans"]["HF"] == {"total": 0, "active": 2}
    assert out["total_active"] == 2


def test_get_plan_member_counts_missing_db_raises(tmp_path):
    import datetime
    with pytest.raises(FileNotFoundError):
        get_plan_member_counts(
            str(tmp_path / "nope.accdb"),
            datetime.date(2026, 7, 1), datetime.date(2026, 7, 31),
        )


def test_get_plan_member_counts_param_order(monkeypatch, tmp_path):
    """start_date <= month_END binds first, end_date >= month_START
    second — a swap silently turns 'overlaps the month' into
    'enrolled for the entire month'."""
    import datetime
    import sys
    import types

    db_file = tmp_path / "fake.accdb"
    db_file.write_bytes(b"")

    executed = []

    class FakeCursor:
        def execute(self, query, *params):
            executed.append((query, params))
        def fetchall(self):
            return []

    class FakeConn:
        def cursor(self):
            return FakeCursor()
        def close(self):
            pass

    fake_pyodbc = types.SimpleNamespace(
        Error=Exception, connect=lambda _cs: FakeConn()
    )
    monkeypatch.setitem(sys.modules, "pyodbc", fake_pyodbc)

    start = datetime.date(2026, 7, 1)
    end = datetime.date(2026, 7, 31)
    get_plan_member_counts(str(db_file), start, end)

    active_calls = [p for q, p in executed if "EXISTS" in q]
    assert active_calls == [(end, start)]   # month_end first, month_start second


def test_all_billing_fields_query_columns():
    from monthly_schedule.db import ALL_BILLING_FIELDS_QUERY
    for col in ("[Center ID]", "[Gender]", "[DOB]",
                "[Admission Date]", "[Medicaid]"):
        assert col in ALL_BILLING_FIELDS_QUERY
    assert "FROM [Contacts]" in ALL_BILLING_FIELDS_QUERY
    # NULL Center IDs can't key the roster dict.
    assert "WHERE [Center ID] IS NOT NULL" in ALL_BILLING_FIELDS_QUERY


def test_get_all_billing_fields_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_all_billing_fields
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_all_billing_fields(str(missing))


def test_billing_codes_query_columns():
    from monthly_schedule.db import BILLING_CODES_QUERY
    for col in ("[Health Plan]", "[SADC Code]", "[Trans Code]"):
        assert col in BILLING_CODES_QUERY
    assert "FROM [Codes]" in BILLING_CODES_QUERY


def test_get_billing_codes_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_billing_codes
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_billing_codes(str(missing))


def test_get_billing_codes_missing_table_raises_runtime(monkeypatch,
                                                        tmp_path):
    """A DB without the Codes table surfaces as RuntimeError (the
    worker catches it and falls back to '????' codes)."""
    import sys
    import types
    from monthly_schedule.db import get_billing_codes

    db_file = tmp_path / "fake.accdb"
    db_file.write_bytes(b"")

    class OdbcError(Exception):
        pass

    class FakeCursor:
        def execute(self, query, *params):
            raise OdbcError("no such table 'Codes'")

    class FakeConn:
        def cursor(self):
            return FakeCursor()
        def close(self):
            pass

    fake_pyodbc = types.SimpleNamespace(
        Error=OdbcError, connect=lambda _cs: FakeConn()
    )
    monkeypatch.setitem(sys.modules, "pyodbc", fake_pyodbc)
    with pytest.raises(RuntimeError, match="Codes table"):
        get_billing_codes(str(db_file))


def test_activities_query_columns():
    from monthly_schedule.db import ACTIVITIES_QUERY
    assert "[A_ID]" in ACTIVITIES_QUERY
    assert "[Activity_Name]" in ACTIVITIES_QUERY
    assert "[Frequency]" in ACTIVITIES_QUERY
    assert "[C_name]" in ACTIVITIES_QUERY
    assert "FROM [Activities]" in ACTIVITIES_QUERY


def test_map_activity_row():
    from monthly_schedule.db import map_activity_row
    key, info = map_activity_row((" a1 ", "News On TV", "1.2.3.4.5", "电视"))
    assert key == "A1"
    assert info == {"name": "News On TV", "frequency": "1.2.3.4.5",
                    "c_name": "电视"}


def test_map_activity_row_blank_fields():
    from monthly_schedule.db import map_activity_row
    key, info = map_activity_row(("A14", None, None, None))
    assert key == "A14"
    assert info == {"name": "", "frequency": "", "c_name": ""}


def test_get_activities_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_activities
    with pytest.raises(FileNotFoundError):
        get_activities(str(tmp_path / "nope.accdb"))


def test_map_holiday_row():
    from monthly_schedule.db import map_holiday_row
    row = (3, " Labor Day ", datetime(2026, 9, 7, 0, 0))
    assert map_holiday_row(row) == {
        "id": 3, "name": "Labor Day", "date": date(2026, 9, 7),
    }


def test_map_holiday_row_blank_name():
    from monthly_schedule.db import map_holiday_row
    assert map_holiday_row((4, None, datetime(2026, 1, 1)))["name"] == ""


def test_map_operating_day_row():
    from monthly_schedule.db import map_operating_day_row
    row = (1, "Monday", 1, datetime(1899, 12, 30, 8, 0),
           datetime(1899, 12, 30, 16, 0))
    assert map_operating_day_row(row) == {
        "id": 1, "day_name": "Monday", "day_of_week": 1,
        "opening_time": "08:00", "closing_time": "16:00",
    }


def test_get_holidays_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_holidays
    with pytest.raises(FileNotFoundError):
        get_holidays(str(tmp_path / "nope.accdb"))


def test_get_operating_days_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_operating_days
    with pytest.raises(FileNotFoundError):
        get_operating_days(str(tmp_path / "nope.accdb"))


def test_fetch_all_unfiltered_require_col(monkeypatch, tmp_path):
    """require_col picks which column must be non-NULL for a row to be
    kept (default 1 = Center ID; the calendar tables use 2)."""
    from monthly_schedule.db import _fetch_all_unfiltered
    db = tmp_path / "x.accdb"
    db.write_bytes(b"")
    rows = [(1, None, 5), (2, "x", None)]

    class FakeCursor:
        def execute(self, q):
            pass

        def fetchall(self):
            return rows

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    fake_pyodbc = types.SimpleNamespace(
        connect=lambda cs: FakeConn(), Error=Exception,
    )
    monkeypatch.setitem(sys.modules, "pyodbc", fake_pyodbc)
    assert _fetch_all_unfiltered("q", str(db), lambda r: r) == [(2, "x", None)]
    assert _fetch_all_unfiltered("q", str(db), lambda r: r,
                                 require_col=2) == [(1, None, 5)]


class FakeOdbcError(Exception):
    """Stand-in for pyodbc.Error / pyodbc.ProgrammingError."""


def _fake_pyodbc_raising_on_execute(message):
    """A fake pyodbc module whose cursor.execute raises an ODBC error —
    the shape of a missing-table failure ('cannot find the input
    table')."""
    class FakeCursor:
        def execute(self, query, *params):
            raise FakeOdbcError(message)

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    return types.SimpleNamespace(
        Error=FakeOdbcError, connect=lambda _cs: FakeConn()
    )


def test_fetch_all_unfiltered_missing_table_raises_runtime(monkeypatch,
                                                           tmp_path):
    """A missing table surfaces as RuntimeError carrying the original
    pyodbc text, so the CLI/GUI can show the normal database error
    instead of a raw traceback."""
    from monthly_schedule.db import _fetch_all_unfiltered
    db = tmp_path / "x.accdb"
    db.write_bytes(b"")
    monkeypatch.setitem(
        sys.modules, "pyodbc",
        _fake_pyodbc_raising_on_execute(
            "cannot find the input table or query 'Holidays'"
        ),
    )
    with pytest.raises(RuntimeError) as excinfo:
        _fetch_all_unfiltered("q", str(db), lambda r: r)
    assert "Holidays" in str(excinfo.value)
    assert "cannot find the input table" in str(excinfo.value)


def test_fetch_all_missing_table_raises_runtime(monkeypatch, tmp_path):
    """Same for the parameterized (per-center) fetch helper."""
    from monthly_schedule.db import _fetch_all
    db = tmp_path / "x.accdb"
    db.write_bytes(b"")
    monkeypatch.setitem(
        sys.modules, "pyodbc",
        _fake_pyodbc_raising_on_execute(
            "cannot find the input table or query 'Holidays'"
        ),
    )
    with pytest.raises(RuntimeError) as excinfo:
        _fetch_all("q", 24010, str(db), lambda r: r)
    assert "Holidays" in str(excinfo.value)
    assert "cannot find the input table" in str(excinfo.value)
