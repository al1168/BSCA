"""Read one member record from the Access database via pyodbc.

`pyodbc` is imported lazily so the pure helpers are testable without
the ODBC driver. Bitness note (spec §8): the installed Microsoft
Access ODBC driver must match this Python interpreter's bitness.
"""

import os

MEMBER_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[Address], [Long Lat] FROM [Contacts] "
    "WHERE [Center ID] = ?"
)


def build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def map_member_row(row):
    return {
        # Access returns [Center ID] as a float; normalize to int.
        "center_id": int(row[0]),
        "last_name": row[1],
        "first_name": row[2],
        "health_plan": row[3],
        "address": row[4],
        "long_lat": row[5],
    }


def get_member(center_id, db_path):
    """Return the member dict for `center_id`, or None if no row.
    Raises FileNotFoundError if the DB path is absent, RuntimeError if
    the ODBC driver cannot open it."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    import pyodbc

    try:
        conn = pyodbc.connect(build_connection_string(db_path))
    except pyodbc.Error as exc:
        raise RuntimeError(
            "Could not open the Access database. Verify the Microsoft "
            "Access ODBC driver is installed and its bitness matches "
            "this Python interpreter (spec section 8). "
            f"Original error: {exc}"
        )
    try:
        cursor = conn.cursor()
        cursor.execute(MEMBER_QUERY, center_id)
        row = cursor.fetchone()
        return map_member_row(row) if row else None
    finally:
        conn.close()


MEMBERS_BY_PLAN_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[Address], [Long Lat] FROM [Contacts] "
    "WHERE [Health Plan] = ? ORDER BY [Center ID]"
)


def get_members_by_plan(plan_code, db_path):
    """Return member dicts for every member whose Health Plan equals
    `plan_code`, ordered by Center ID. Access text comparison is
    case-insensitive. Raises FileNotFoundError if the DB path is
    absent, RuntimeError if the ODBC driver cannot open it."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    import pyodbc

    try:
        conn = pyodbc.connect(build_connection_string(db_path))
    except pyodbc.Error as exc:
        raise RuntimeError(
            "Could not open the Access database. Verify the Microsoft "
            "Access ODBC driver is installed and its bitness matches "
            "this Python interpreter (spec section 8). "
            f"Original error: {exc}"
        )
    try:
        cursor = conn.cursor()
        cursor.execute(MEMBERS_BY_PLAN_QUERY, plan_code)
        return [map_member_row(row) for row in cursor.fetchall()]
    finally:
        conn.close()


ALL_MEMBERS_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[Address], [Long Lat] FROM [Contacts] ORDER BY [Center ID]"
)


def get_all_members(db_path):
    """Return every Contacts row as a list of member dicts. Same dict
    shape as get_member and get_members_by_plan.

    Rows with a NULL Center ID are silently skipped — they can't be
    scheduled (the Center ID is the FK every supporting table joins on)
    and would otherwise crash map_member_row's int() cast."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    import pyodbc

    try:
        conn = pyodbc.connect(build_connection_string(db_path))
    except pyodbc.Error as exc:
        raise RuntimeError(
            "Could not open the Access database. Verify the Microsoft "
            "Access ODBC driver is installed and its bitness matches "
            "this Python interpreter (spec section 8). "
            f"Original error: {exc}"
        )
    try:
        cursor = conn.cursor()
        cursor.execute(ALL_MEMBERS_QUERY)
        return [
            map_member_row(row)
            for row in cursor.fetchall()
            if row[0] is not None
        ]
    finally:
        conn.close()


ENROLLMENTS_QUERY = (
    "SELECT [ID], [Center ID], [start_date], [end_date] "
    "FROM [Enrollment] "
    "WHERE [Center ID] = ?"
)


def _to_date(value):
    """Access Date/Time fields come back as datetime.datetime via pyodbc.
    Normalize to datetime.date so comparisons against month_dates work.
    NULL pass-through."""
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date()
    return value


def map_enrollment_row(row):
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "start_date": _to_date(row[2]),
        "end_date": _to_date(row[3]),
    }


def get_enrollments(center_id, db_path):
    """Return all Enrollment rows for `center_id` as a list of dicts."""
    return _fetch_all(ENROLLMENTS_QUERY, center_id, db_path, map_enrollment_row)


AUTHORIZATIONS_QUERY = (
    "SELECT [ID], [Center ID], [auth_start], [auth_end], "
    "[effective_start], [effective_end], [auth_days] "
    "FROM [Authorization] "
    "WHERE [Center ID] = ?"
)


def map_authorization_row(row):
    """Map a raw Authorization row. If `effective_start` / `effective_end`
    is NULL in Access, fall back to `auth_start` / `auth_end` — the
    document period acts as the implicit effective window."""
    auth_start = _to_date(row[2])
    auth_end = _to_date(row[3])
    effective_start = _to_date(row[4])
    effective_end = _to_date(row[5])
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "auth_start": auth_start,
        "auth_end": auth_end,
        "effective_start": effective_start if effective_start is not None else auth_start,
        "effective_end": effective_end if effective_end is not None else auth_end,
        "auth_days": row[6],
    }


def get_authorizations(center_id, db_path):
    """Return all Authorization rows for `center_id` as a list of dicts."""
    return _fetch_all(AUTHORIZATIONS_QUERY, center_id, db_path,
                      map_authorization_row)


ABSENCES_QUERY = (
    "SELECT [ID], [Center ID], [Leave Type], [Start_Date], [End_Date] "
    "FROM [Absences] "
    "WHERE [Center ID] = ?"
)


def map_absence_row(row):
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "leave_type": row[2],
        "start_date": _to_date(row[3]),
        "end_date": _to_date(row[4]),
    }


def get_absences(center_id, db_path):
    """Return all Absences rows for `center_id` as a list of dicts."""
    return _fetch_all(ABSENCES_QUERY, center_id, db_path, map_absence_row)


AVAILABILITY_QUERY = (
    "SELECT [ID], [Center ID], [effective_start_date], "
    "[effective_end_date], [Day Of Week], [avail_start], [avail_end] "
    "FROM [Availability] "
    "WHERE [Center ID] = ?"
)


def _datetime_to_hhmm(value):
    """Access stores time-only fields as DATETIME with a fixed 1899
    placeholder date. Extract the time as 'HH:MM' so downstream code
    (parse_hhmm) can use it. NULL passes through unchanged."""
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    return value


def map_availability_row(row):
    """Map a raw Availability row. avail_start/avail_end are stored as
    DATETIME in Access (with a 1899-12-30 placeholder date); the mapper
    extracts the time as 'HH:MM'. `effective_end_date` is nullable."""
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "effective_start_date": _to_date(row[2]),
        "effective_end_date": _to_date(row[3]),
        "day_of_week": int(row[4]),
        "avail_start": _datetime_to_hhmm(row[5]),
        "avail_end": _datetime_to_hhmm(row[6]),
    }


def get_availability(center_id, db_path):
    """Return all Availability rows for `center_id` as a list of dicts."""
    return _fetch_all(AVAILABILITY_QUERY, center_id, db_path,
                      map_availability_row)


ALL_ENROLLMENTS_QUERY = (
    "SELECT [ID], [Center ID], [start_date], [end_date] "
    "FROM [Enrollment]"
)


def get_all_enrollments(db_path: str) -> dict:
    """Return {center_id: [enrollment dicts]} for every Enrollment row.
    One ODBC round-trip vs N when used by the batch worker modes."""
    rows = _fetch_all_unfiltered(ALL_ENROLLMENTS_QUERY, db_path, map_enrollment_row)
    return _index_by_center_id(rows)


ALL_AUTHORIZATIONS_QUERY = (
    "SELECT [ID], [Center ID], [auth_start], [auth_end], "
    "[effective_start], [effective_end], [auth_days] "
    "FROM [Authorization]"
)


def get_all_authorizations(db_path: str) -> dict:
    """Return {center_id: [authorization dicts]} for every Authorization row."""
    rows = _fetch_all_unfiltered(ALL_AUTHORIZATIONS_QUERY, db_path,
                                  map_authorization_row)
    return _index_by_center_id(rows)


ALL_ABSENCES_QUERY = (
    "SELECT [ID], [Center ID], [Leave Type], [Start_Date], [End_Date] "
    "FROM [Absences]"
)


def get_all_absences(db_path: str) -> dict:
    """Return {center_id: [absence dicts]} for every Absences row."""
    rows = _fetch_all_unfiltered(ALL_ABSENCES_QUERY, db_path, map_absence_row)
    return _index_by_center_id(rows)


ALL_AVAILABILITY_QUERY = (
    "SELECT [ID], [Center ID], [effective_start_date], "
    "[effective_end_date], [Day Of Week], [avail_start], [avail_end] "
    "FROM [Availability]"
)


def get_all_availability(db_path: str) -> dict:
    """Return {center_id: [availability dicts]} for every Availability row."""
    rows = _fetch_all_unfiltered(ALL_AVAILABILITY_QUERY, db_path,
                                  map_availability_row)
    return _index_by_center_id(rows)


ONE_OFFS_QUERY = (
    "SELECT [ID], [Center ID], [date], [avail_start], [avail_end] "
    "FROM [OneOffAvailability] "
    "WHERE [Center ID] = ?"
)


def map_one_off_row(row):
    """Map a raw OneOffAvailability row. `date` is stored as DATETIME
    in Access; the mapper truncates to date. `avail_start`/`avail_end`
    are stored as the 1899-12-30 placeholder DATETIME and extracted as
    'HH:MM' (same convention as Availability)."""
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "date": _to_date(row[2]),
        "avail_start": _datetime_to_hhmm(row[3]),
        "avail_end": _datetime_to_hhmm(row[4]),
    }


def get_one_offs(center_id, db_path):
    """Return all OneOffAvailability rows for `center_id` as a list of dicts."""
    return _fetch_all(ONE_OFFS_QUERY, center_id, db_path, map_one_off_row)


ALL_ONE_OFFS_QUERY = (
    "SELECT [ID], [Center ID], [date], [avail_start], [avail_end] "
    "FROM [OneOffAvailability]"
)


def get_all_one_offs(db_path):
    """Return {center_id: [one_off dicts]} for every OneOffAvailability
    row. One ODBC round-trip vs N when used by the batch worker modes."""
    rows = _fetch_all_unfiltered(ALL_ONE_OFFS_QUERY, db_path, map_one_off_row)
    return _index_by_center_id(rows)


def _index_by_center_id(rows):
    """Group a flat list of row-dicts into {center_id: [rows]}."""
    out: dict[int, list] = {}
    for row in rows:
        out.setdefault(row["center_id"], []).append(row)
    return out


def _fetch_all_unfiltered(query: str, db_path: str, mapper):
    """Open one connection, run an unfiltered SELECT, map each row.
    Used by the four `get_all_<table>` batch fetchers so a whole-table
    load is one ODBC round-trip instead of N."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    import pyodbc

    try:
        conn = pyodbc.connect(build_connection_string(db_path))
    except pyodbc.Error as exc:
        raise RuntimeError(
            "Could not open the Access database. Verify the Microsoft "
            "Access ODBC driver is installed and its bitness matches "
            "this Python interpreter (spec section 8). "
            f"Original error: {exc}"
        )
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        return [mapper(row) for row in cursor.fetchall() if row[1] is not None]
    finally:
        conn.close()


def _fetch_all(query, center_id, db_path, mapper):
    """Run a parameterized SELECT and map each row. Shared by the 4 new
    fetchers."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    import pyodbc

    try:
        conn = pyodbc.connect(build_connection_string(db_path))
    except pyodbc.Error as exc:
        raise RuntimeError(
            "Could not open the Access database. Verify the Microsoft "
            "Access ODBC driver is installed and its bitness matches "
            "this Python interpreter (spec section 8). "
            f"Original error: {exc}"
        )
    try:
        cursor = conn.cursor()
        cursor.execute(query, center_id)
        return [mapper(row) for row in cursor.fetchall()]
    finally:
        conn.close()
