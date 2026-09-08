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


PLAN_TOTALS_QUERY = (
    "SELECT [Health Plan], COUNT(*) FROM [Contacts] "
    "WHERE [Center ID] IS NOT NULL GROUP BY [Health Plan]"
)

# Access has no COUNT(DISTINCT ...); EXISTS keeps one row per member.
PLAN_ACTIVE_QUERY = (
    "SELECT c.[Health Plan], COUNT(*) FROM [Contacts] c "
    "WHERE c.[Center ID] IS NOT NULL AND EXISTS ("
    "SELECT 1 FROM [Enrollment] e "
    "WHERE e.[Center ID] = c.[Center ID] "
    "AND e.[start_date] <= ? "
    "AND (e.[end_date] IS NULL OR e.[end_date] >= ?)"
    ") GROUP BY c.[Health Plan]"
)


def _normalize_plan(value):
    """' hf ' / None -> 'HF' / '' so hand-typed plan codes merge."""
    return str(value or "").strip().upper()


def merge_plan_counts(total_rows, active_rows):
    """Merge (plan, count) rows from the two plan-count queries into
    {"plans": {CODE: {"total": t, "active": a}}, "total_active": n}.
    Blank/NULL plans land under ''. total_active spans ALL plans,
    known to the GUI or not (All Members runs schedule everyone)."""
    plans = {}
    for plan, count in total_rows:
        entry = plans.setdefault(_normalize_plan(plan),
                                 {"total": 0, "active": 0})
        entry["total"] += int(count)
    total_active = 0
    for plan, count in active_rows:
        entry = plans.setdefault(_normalize_plan(plan),
                                 {"total": 0, "active": 0})
        entry["active"] += int(count)
        total_active += int(count)
    return {"plans": plans, "total_active": total_active}


def get_plan_member_counts(db_path, month_start, month_end):
    """Per-plan member counts for the month [month_start, month_end].

    A member is ACTIVE when an Enrollment row overlaps any day of the
    month: start_date <= month_end AND (end_date IS NULL OR end_date
    >= month_start) — the same overlap rule eligibility uses. Returns
    merge_plan_counts() output. Raises FileNotFoundError/RuntimeError
    like the other helpers."""
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
        cursor.execute(PLAN_TOTALS_QUERY)
        totals = cursor.fetchall()
        # Param order: start_date <= month_END, end_date >= month_START.
        cursor.execute(PLAN_ACTIVE_QUERY, month_end, month_start)
        active = cursor.fetchall()
        return merge_plan_counts(totals, active)
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
    "[effective_start], [effective_end], [auth_days], [Member ID], "
    "[Plan Type] "
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
        "member_id": row[7],
        "plan_type": row[8],
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
    "[effective_start], [effective_end], [auth_days], [Member ID], "
    "[Plan Type] "
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


def get_one_offs(center_id: int, db_path: str) -> list:
    """Return all OneOffAvailability rows for `center_id` as a list of dicts."""
    return _fetch_all(ONE_OFFS_QUERY, center_id, db_path, map_one_off_row)


ALL_ONE_OFFS_QUERY = (
    "SELECT [ID], [Center ID], [date], [avail_start], [avail_end] "
    "FROM [OneOffAvailability]"
)


def get_all_one_offs(db_path: str) -> dict:
    """Return {center_id: [one_off dicts]} for every OneOffAvailability
    row. One ODBC round-trip vs N when used by the batch worker modes."""
    rows = _fetch_all_unfiltered(ALL_ONE_OFFS_QUERY, db_path, map_one_off_row)
    return _index_by_center_id(rows)


HOLIDAYS_QUERY = "SELECT [ID], [holiday_name], [date] FROM [Holidays]"


def map_holiday_row(row):
    """Map a raw Holidays row. `date` is a DATETIME truncated to a
    date; a NULL name becomes ''."""
    return {
        "id": int(row[0]),
        "name": str(row[1] or "").strip(),
        "date": _to_date(row[2]),
    }


def get_holidays(db_path: str) -> list:
    """Every Holidays row (center-wide, so no center_id index). Rows
    with a NULL date are dropped."""
    return _fetch_all_unfiltered(
        HOLIDAYS_QUERY, db_path, map_holiday_row, require_col=2,
    )


OPERATING_DAYS_QUERY = (
    "SELECT [ID], [day_name], [Day Of Week], [opening_time], "
    "[closing_time] FROM [OperatingDays]"
)


def map_operating_day_row(row):
    """Map a raw OperatingDays row. Times are the 1899-12-30
    placeholder DATETIMEs, extracted as 'HH:MM' like Availability."""
    return {
        "id": int(row[0]),
        "day_name": str(row[1] or ""),
        "day_of_week": int(row[2]),
        "opening_time": _datetime_to_hhmm(row[3]),
        "closing_time": _datetime_to_hhmm(row[4]),
    }


def get_operating_days(db_path: str) -> list:
    """Every OperatingDays row. Rows with a NULL [Day Of Week] are
    dropped. A weekday with no row is closed (see CenterCalendar)."""
    return _fetch_all_unfiltered(
        OPERATING_DAYS_QUERY, db_path, map_operating_day_row, require_col=2,
    )


ALL_BILLING_FIELDS_QUERY = (
    "SELECT [Center ID], [Gender], [DOB], [Admission Date], [Medicaid] "
    "FROM [Contacts] WHERE [Center ID] IS NOT NULL"
)


def get_all_billing_fields(db_path: str) -> dict:
    """Return {center_id: {gender, dob, admission_date, medicaid}} for
    every Contacts row, one ODBC round-trip. Values pass through raw —
    DOB / Admission Date are Short Text in the live DB (with occasional
    typos), so normalization is left to billing_workbook.parse_flex_date
    (which also handles a future migration to real Date/Time columns)."""
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
        cursor.execute(ALL_BILLING_FIELDS_QUERY)
        return {
            int(row[0]): {
                "gender": row[1],
                "dob": row[2],
                "admission_date": row[3],
                "medicaid": row[4],
            }
            for row in cursor.fetchall()
        }
    finally:
        conn.close()


BILLING_CODES_QUERY = (
    "SELECT [Health Plan], [SADC Code], [Trans Code] FROM [Codes]"
)


def get_billing_codes(db_path: str) -> dict:
    """Return {normalized plan code: (sadc_code, trans_code)} from the
    Codes lookup table. Plans are normalized like everywhere else
    (' hf ' -> 'HF'). Raises FileNotFoundError when the DB is absent,
    RuntimeError when it can't be opened or has no Codes table — the
    caller decides how to degrade (the billing sheet falls back to
    '????' codes)."""
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
        try:
            cursor.execute(BILLING_CODES_QUERY)
        except pyodbc.Error as exc:
            raise RuntimeError(
                f"Could not read the Codes table: {exc}"
            )
        return {
            _normalize_plan(row[0]): (
                str(row[1] or "").strip(), str(row[2] or "").strip()
            )
            for row in cursor.fetchall()
            if _normalize_plan(row[0])
        }
    finally:
        conn.close()


ACTIVITIES_QUERY = (
    "SELECT [A_ID], [Activity_Name], [Frequency], [C_name] "
    "FROM [Activities]"
)


def map_activity_row(row):
    """(' a1 ', 'News On TV', '1.2.3.4.5', '电视') ->
    ('A1', {name, frequency, c_name}) — the key is the normalized A_ID
    matching the template's activity columns."""
    return (
        str(row[0] or "").strip().upper(),
        {
            "name": str(row[1] or "").strip(),
            "frequency": str(row[2] or "").strip(),
            "c_name": str(row[3] or "").strip(),
        },
    )


def get_activities(db_path: str) -> dict:
    """Return {A_ID: {name, frequency, c_name}} from the Activities
    lookup table (the Bowery activity log's column headers). Raises
    FileNotFoundError when the DB is absent, RuntimeError when it can't
    be opened or has no Activities table — the caller degrades by
    skipping activity logs with a warning."""
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
        try:
            cursor.execute(ACTIVITIES_QUERY)
        except pyodbc.Error as exc:
            raise RuntimeError(
                f"Could not read the Activities table: {exc}"
            )
        out = {}
        for raw in cursor.fetchall():
            key, info = map_activity_row(raw)
            if key:
                out[key] = info
        return out
    finally:
        conn.close()


def _read_error(exc):
    """RuntimeError for a query that failed after the connection opened.
    The most common cause is a table the database doesn't have yet (a
    DB not re-run through the Setup program), so the message names that
    fix and keeps the original pyodbc text — gui.errors.friendly_db_error
    passes it through, and the CLI prints it as a one-liner."""
    return RuntimeError(
        "Could not read the Access database. If the error names a "
        "missing table, run the BSCA Setup program on this database. "
        f"Original error: {exc}"
    )


def _index_by_center_id(rows):
    """Group a flat list of row-dicts into {center_id: [rows]}."""
    out: dict[int, list] = {}
    for row in rows:
        out.setdefault(row["center_id"], []).append(row)
    return out


def _fetch_all_unfiltered(query: str, db_path: str, mapper, require_col=1):
    """Open one connection, run an unfiltered SELECT, map each row.
    Used by the `get_all_<table>` batch fetchers so a whole-table load
    is one ODBC round-trip instead of N. Rows whose column at index
    `require_col` is NULL are dropped (default 1 = [Center ID]; the
    center-wide calendar tables pass the index of their key column)."""
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
        try:
            cursor.execute(query)
            rows = cursor.fetchall()
        except pyodbc.Error as exc:
            raise _read_error(exc) from exc
        return [mapper(row) for row in rows
                if row[require_col] is not None]
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
        try:
            cursor.execute(query, center_id)
            rows = cursor.fetchall()
        except pyodbc.Error as exc:
            raise _read_error(exc) from exc
        return [mapper(row) for row in rows]
    finally:
        conn.close()
