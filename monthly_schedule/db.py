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


ENROLLMENTS_QUERY = (
    "SELECT [ID], [Center ID], [start_date], [end_date] "
    "FROM [Enrollment] "
    "WHERE [Center ID] = ?"
)


def map_enrollment_row(row):
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "start_date": row[2],
        "end_date": row[3],
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
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "auth_start": row[2],
        "auth_end": row[3],
        "effective_start": row[4],
        "effective_end": row[5],
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
        "start_date": row[3],
        "end_date": row[4],
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


def map_availability_row(row):
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "effective_start_date": row[2],
        "effective_end_date": row[3],
        "day_of_week": int(row[4]),
        "avail_start": row[5],
        "avail_end": row[6],
    }


def get_availability(center_id, db_path):
    """Return all Availability rows for `center_id` as a list of dicts."""
    return _fetch_all(AVAILABILITY_QUERY, center_id, db_path,
                      map_availability_row)


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
