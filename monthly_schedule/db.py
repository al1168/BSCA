"""Read one member record from the Access database via pyodbc.

`pyodbc` is imported lazily so the pure helpers are testable without
the ODBC driver. Bitness note (spec §8): the installed Microsoft
Access ODBC driver must match this Python interpreter's bitness.
"""

import os

MEMBER_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[SADC] FROM [Contacts] WHERE [Center ID] = ?"
)


def build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def map_member_row(row):
    return {
        # Access returns [Center ID] as a float; normalize to int so
        # the header reads "ID: 24010", not "ID: 24010.0".
        "center_id": int(row[0]),
        "last_name": row[1],
        "first_name": row[2],
        "health_plan": row[3],
        "auth_days": row[4],
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
    "[SADC] FROM [Contacts] WHERE [Health Plan] = ? "
    "ORDER BY [Center ID]"
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
