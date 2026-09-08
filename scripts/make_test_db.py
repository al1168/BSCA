"""scripts/make_test_db.py

Create/reset an Access .accdb seeded with one of the named test
scenarios. Designed to spare the production DB from manual edits when
exercising the GUI.

Usage:
    python scripts/make_test_db.py --scenario <name> [--output PATH] [--source PATH] [--use]
"""

import argparse
import os
import shutil
import sys
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Callable


# Default reference DB (matches new_monthly_schedule.DEFAULT_DB).
DEFAULT_SOURCE = r"\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb"

# Deletion order: children first, parents last. Access FK constraints
# may or may not enforce; deleting in this order is safe regardless.
# Holidays leads the list so each scenario starts with no holidays and
# only seeds the ones it wants. OperatingDays is deliberately absent:
# its 7-day default (seeded by _ensure_calendar_tables) must survive
# every reset, or the scheduler would read the center as closed.
SUPPORTING_TABLES = ("Holidays", "OneOffAvailability", "Availability",
                     "Absences", "Authorization", "Enrollment")
DATA_TABLES = SUPPORTING_TABLES + ("Contacts",)

# Scenarios that should preserve the real Contacts table and only
# truncate the supporting tables. Used by main() to decide which
# list to hand _truncate(). Because Holidays is in SUPPORTING_TABLES,
# this also clears the company-wide Holidays rows; re-enter them
# afterwards if the scenario needs them.
SCENARIOS_KEEP_CONTACTS = {"populate_real_members"}


# ── Date math ─────────────────────────────────────────────────────────

def _month_bounds(today: date):
    """Return (M1, M15, MLAST, MNEXT_LAST) anchored to `today`."""
    m1 = today.replace(day=1)
    m15 = today.replace(day=15)
    mlast_day = monthrange(today.year, today.month)[1]
    mlast = today.replace(day=mlast_day)
    if today.month == 12:
        next_m1 = date(today.year + 1, 1, 1)
    else:
        next_m1 = date(today.year, today.month + 1, 1)
    next_last_day = monthrange(next_m1.year, next_m1.month)[1]
    mnext_last = date(next_m1.year, next_m1.month, next_last_day)
    return m1, m15, mlast, mnext_last


def _dt(d: date) -> datetime:
    """`date` -> midnight `datetime`, for Access DATETIME columns."""
    return datetime(d.year, d.month, d.day)


def _hhmm(h: int, m: int) -> datetime:
    """Build the 1899-12-30 placeholder DATETIME Access uses for
    time-only fields (matches what avail_start / avail_end store)."""
    return datetime(1899, 12, 30, h, m)


# ── DB helpers ────────────────────────────────────────────────────────

def _build_connection_string(path: str) -> str:
    return f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={path};"


def _column_exists(cursor, table: str, column: str) -> bool:
    """Return True if `column` exists on `table`. Matches names
    case-insensitively because Access is case-insensitive.

    Uses the ODBC catalog rather than a probe SELECT: the Access driver
    rejects `SELECT TOP 0 ...` outright ("reserved word or ...
    punctuation is incorrect"), so a probe can't distinguish a missing
    column from a syntax the driver refuses. Mirrors
    scripts/add_group_to_contacts.py::_column_exists."""
    rows = cursor.columns(table=table).fetchall()
    target = column.lower()
    return any(r.column_name.lower() == target for r in rows)


def _ensure_plan_type_column(conn) -> None:
    """Old reference DBs predate the [Plan Type] migration
    (scripts/add_plan_type_to_authorization.py); the scheduler's
    Authorization queries need the column, so add it when absent."""
    cur = conn.cursor()
    if not _column_exists(cur, "Authorization", "Plan Type"):
        cur.execute(
            "ALTER TABLE [Authorization] ADD COLUMN [Plan Type] TEXT(255)"
        )
        conn.commit()


def _ensure_calendar_tables(conn) -> None:
    """Reference DBs predate the Holidays / OperatingDays tables. Create
    them when absent and seed the 7-day default hours, so every scenario
    runs against the schema the scheduler now requires."""
    from scripts.create_supporting_tables import (
        _CREATE_HOLIDAYS, _CREATE_OPERATING_DAYS,
    )
    from scripts.seed_operating_days import seed_if_empty

    cur = conn.cursor()
    for ddl in (_CREATE_HOLIDAYS, _CREATE_OPERATING_DAYS):
        try:
            cur.execute(ddl)
        except Exception as exc:
            if "42S01" not in str(exc):      # anything but "already exists"
                raise
    seed_if_empty(cur)
    conn.commit()


def _truncate(conn, tables) -> None:
    """`DELETE FROM` each table in `tables`. Caller supplies the order
    (children first, parents last)."""
    cur = conn.cursor()
    for table in tables:
        try:
            cur.execute(f"DELETE FROM [{table}]")
        except Exception as exc:
            raise RuntimeError(
                f"DELETE FROM [{table}] failed. The DB may be missing "
                f"this table — see docs/database.md for the expected "
                f"schema. Original error: {exc}"
            )
    conn.commit()


def _seed_member(conn, center_id: int, last: str, first: str,
                 plan: str = "HOF",
                 address: str = "123 Test St, New York, NY 10001",
                 long_lat: str | None = None) -> None:
    """Insert one Contacts row with only the columns the scheduler reads.
    Contacts.[Center ID] is DOUBLE in Access; pyodbc widens int → float.
    Pass `long_lat` as "long,lat" (matching the column name) to bypass
    geocoding (e.g. for test seeds)."""
    cur = conn.cursor()
    if long_lat is not None:
        cur.execute(
            "INSERT INTO [Contacts] ([Center ID], [Last Name], [First Name], "
            "[Health Plan], [Address], [Long Lat]) VALUES (?, ?, ?, ?, ?, ?)",
            center_id, last, first, plan, address, long_lat,
        )
    else:
        cur.execute(
            "INSERT INTO [Contacts] ([Center ID], [Last Name], [First Name], "
            "[Health Plan], [Address]) VALUES (?, ?, ?, ?, ?)",
            center_id, last, first, plan, address,
        )


def _seed_one_off(conn, center_id: int, when: date,
                  start_hm: tuple, end_hm: tuple,
                  notes: str = "") -> None:
    """Insert one OneOffAvailability row.

    `when` is the date the exception applies to. `start_hm` / `end_hm`
    are (hour, minute) tuples, which become the 1899-12-30 placeholder
    DATETIMEs Access uses for time-only fields."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO [OneOffAvailability] "
        "([Center ID], [date], [avail_start], [avail_end], [Notes]) "
        "VALUES (?, ?, ?, ?, ?)",
        center_id, _dt(when), _hhmm(*start_hm), _hhmm(*end_hm), notes,
    )


# ── Scenarios ─────────────────────────────────────────────────────────
# Each function takes (conn, today) and inserts rows. Truncation
# happens once before the chosen seed runs; functions assume the
# tables are empty.

def seed_happy_path(conn, today: date) -> None:
    """Center 99001 'Test, Happy' — full happy-path setup plus one
    company holiday on the first Wednesday."""
    m1, m15, mlast, mnext_last = _month_bounds(today)
    enrolled_since = date(today.year - 1, today.month, 1)
    cur = conn.cursor()

    _seed_member(conn, 99001, "Test", "Happy")
    cur.execute(
        "INSERT INTO [Enrollment] ([Center ID], [start_date], [end_date]) "
        "VALUES (?, ?, NULL)",
        99001, _dt(enrolled_since),
    )
    cur.execute(
        "INSERT INTO [Authorization] ([Center ID], [auth_start], "
        "[auth_end], [effective_start], [effective_end], [auth_days]) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        "99001", _dt(m1), _dt(mnext_last),
        _dt(m1), _dt(mnext_last), "1,2,3,4,5",
    )
    for day_of_week in range(1, 6):  # Mon (1) … Fri (5)
        cur.execute(
            "INSERT INTO [Availability] ([Center ID], "
            "[effective_start_date], [effective_end_date], "
            "[Day Of Week], [avail_start], [avail_end]) "
            "VALUES (?, ?, NULL, ?, ?, ?)",
            "99001", _dt(enrolled_since), day_of_week,
            _hhmm(8, 0), _hhmm(16, 0),
        )

    # One company holiday on the first Wednesday of the month, so the
    # generated timesheet visibly skips a weekday it would otherwise fill.
    first_wed = m1
    while first_wed.isoweekday() != 3:
        first_wed = first_wed + timedelta(days=1)
    cur.execute(
        "INSERT INTO [Holidays] ([holiday_name], [date]) VALUES (?, ?)",
        "Test Holiday", _dt(first_wed),
    )
    conn.commit()


def seed_missing_data(conn, today: date) -> None:
    """Three members each missing one prerequisite, to exercise the
    three eligibility-stage failure reasons."""
    m1, m15, mlast, mnext_last = _month_bounds(today)
    enrolled_since = date(today.year - 1, today.month, 1)
    cur = conn.cursor()

    # 99002 NoEnroll, Bob — Contacts + Auth + Availability, no Enrollment.
    _seed_member(conn, 99002, "NoEnroll", "Bob")
    cur.execute(
        "INSERT INTO [Authorization] ([Center ID], [auth_start], "
        "[auth_end], [effective_start], [effective_end], [auth_days]) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        "99002", _dt(m1), _dt(mnext_last),
        _dt(m1), _dt(mnext_last), "1,2,3,4,5",
    )
    for day_of_week in range(1, 6):
        cur.execute(
            "INSERT INTO [Availability] ([Center ID], "
            "[effective_start_date], [effective_end_date], "
            "[Day Of Week], [avail_start], [avail_end]) "
            "VALUES (?, ?, NULL, ?, ?, ?)",
            "99002", _dt(enrolled_since), day_of_week,
            _hhmm(8, 0), _hhmm(16, 0),
        )

    # 99003 NoAuth, Carol — Contacts + Enrollment + Availability, no Auth.
    _seed_member(conn, 99003, "NoAuth", "Carol")
    cur.execute(
        "INSERT INTO [Enrollment] ([Center ID], [start_date], [end_date]) "
        "VALUES (?, ?, NULL)",
        99003, _dt(enrolled_since),
    )
    for day_of_week in range(1, 6):
        cur.execute(
            "INSERT INTO [Availability] ([Center ID], "
            "[effective_start_date], [effective_end_date], "
            "[Day Of Week], [avail_start], [avail_end]) "
            "VALUES (?, ?, NULL, ?, ?, ?)",
            "99003", _dt(enrolled_since), day_of_week,
            _hhmm(8, 0), _hhmm(16, 0),
        )

    # 99004 Absent, Dave — full setup PLUS one Absence covering the whole month.
    _seed_member(conn, 99004, "Absent", "Dave")
    cur.execute(
        "INSERT INTO [Enrollment] ([Center ID], [start_date], [end_date]) "
        "VALUES (?, ?, NULL)",
        99004, _dt(enrolled_since),
    )
    cur.execute(
        "INSERT INTO [Authorization] ([Center ID], [auth_start], "
        "[auth_end], [effective_start], [effective_end], [auth_days]) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        "99004", _dt(m1), _dt(mnext_last),
        _dt(m1), _dt(mnext_last), "1,2,3,4,5",
    )
    cur.execute(
        "INSERT INTO [Absences] ([Center ID], [Leave Type], "
        "[Start_Date], [End_Date]) VALUES (?, ?, ?, ?)",
        "99004", "Vacation", _dt(m1), _dt(mlast),
    )
    conn.commit()


def seed_mid_period_change(conn, today: date) -> None:
    """Center 99005 'Switch, Eve' — two Auth rows carving up the month."""
    m1, m15, mlast, mnext_last = _month_bounds(today)
    m15_plus_1 = m15 + timedelta(days=1)
    enrolled_since = date(today.year - 1, today.month, 1)
    cur = conn.cursor()

    _seed_member(conn, 99005, "Switch", "Eve")
    cur.execute(
        "INSERT INTO [Enrollment] ([Center ID], [start_date], [end_date]) "
        "VALUES (?, ?, NULL)",
        99005, _dt(enrolled_since),
    )
    # Row 1: effective M1 → M15, M/W/F
    cur.execute(
        "INSERT INTO [Authorization] ([Center ID], [auth_start], "
        "[auth_end], [effective_start], [effective_end], [auth_days]) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        "99005", _dt(m1), _dt(mlast),
        _dt(m1), _dt(m15), "1,3,5",
    )
    # Row 2: effective M15+1 → MLAST, T/Th
    cur.execute(
        "INSERT INTO [Authorization] ([Center ID], [auth_start], "
        "[auth_end], [effective_start], [effective_end], [auth_days]) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        "99005", _dt(m1), _dt(mlast),
        _dt(m15_plus_1), _dt(mlast), "2,4",
    )
    conn.commit()


def seed_plan_full(conn, today: date) -> None:
    """Five HOF members: three happy, one missing auth, one with a
    tight Tuesday window that should leave Tuesdays blank."""
    m1, m15, mlast, mnext_last = _month_bounds(today)
    enrolled_since = date(today.year - 1, today.month, 1)
    cur = conn.cursor()

    def _happy(center_id: int, last: str, first: str) -> None:
        _seed_member(conn, center_id, last, first)
        cur.execute(
            "INSERT INTO [Enrollment] ([Center ID], [start_date], "
            "[end_date]) VALUES (?, ?, NULL)",
            center_id, _dt(enrolled_since),
        )
        cur.execute(
            "INSERT INTO [Authorization] ([Center ID], [auth_start], "
            "[auth_end], [effective_start], [effective_end], [auth_days]) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            str(center_id), _dt(m1), _dt(mnext_last),
            _dt(m1), _dt(mnext_last), "1,2,3,4,5",
        )

    _happy(99010, "Plan", "Alice")
    _happy(99011, "Plan", "Bob")
    _happy(99012, "Plan", "Carol")

    # 99013 — Contacts + Enrollment, no Authorization.
    _seed_member(conn, 99013, "Plan", "Dave")
    cur.execute(
        "INSERT INTO [Enrollment] ([Center ID], [start_date], [end_date]) "
        "VALUES (?, ?, NULL)",
        99013, _dt(enrolled_since),
    )

    # 99014 — happy + a Tuesday availability rule too tight for the
    # plan's 3.5-hour session minimum, so Tuesdays come back blank.
    _happy(99014, "Plan", "Eve")
    cur.execute(
        "INSERT INTO [Availability] ([Center ID], "
        "[effective_start_date], [effective_end_date], "
        "[Day Of Week], [avail_start], [avail_end]) "
        "VALUES (?, ?, NULL, ?, ?, ?)",
        "99014", _dt(enrolled_since), 2, _hhmm(12, 0), _hhmm(14, 0),
    )
    conn.commit()


def seed_populate_real_members(conn, today: date) -> None:
    """Seed Enrollment, Authorization, Availability and Absences against
    the real Contacts IDs.

    Iterates every Contacts row (sorted by Center ID ascending) and
    inserts a happy-path setup. Every 30-cycle rotates through three
    deliberate failure shapes (positions 9, 19, 29 within each cycle)
    so the run-summary failures block is also exercised.
    """
    m1, m15, mlast, mnext_last = _month_bounds(today)
    enrolled_since = date(today.year - 1, today.month, 1)
    cur = conn.cursor()

    # Closures so each insert helper sees the date constants without
    # threading them through every call.

    def _enroll(cid: int) -> None:
        cur.execute(
            "INSERT INTO [Enrollment] ([Center ID], [start_date], "
            "[end_date]) VALUES (?, ?, NULL)",
            cid, _dt(enrolled_since),
        )

    def _authorize(cid: int) -> None:
        cur.execute(
            "INSERT INTO [Authorization] ([Center ID], [auth_start], "
            "[auth_end], [effective_start], [effective_end], [auth_days], "
            "[Plan Type]) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            str(cid), _dt(m1), _dt(mnext_last),
            _dt(m1), _dt(mnext_last), "1,2,3,4,5", "MAP",
        )

    def _make_available(cid: int) -> None:
        for day_of_week in range(1, 6):  # Mon … Fri
            cur.execute(
                "INSERT INTO [Availability] ([Center ID], "
                "[effective_start_date], [effective_end_date], "
                "[Day Of Week], [avail_start], [avail_end]) "
                "VALUES (?, ?, NULL, ?, ?, ?)",
                str(cid), _dt(enrolled_since), day_of_week,
                _hhmm(8, 0), _hhmm(16, 0),
            )

    def _mark_absent_month(cid: int) -> None:
        cur.execute(
            "INSERT INTO [Absences] ([Center ID], [Leave Type], "
            "[Start_Date], [End_Date]) VALUES (?, ?, ?, ?)",
            str(cid), "Vacation", _dt(m1), _dt(mlast),
        )

    cur.execute("SELECT [Center ID] FROM [Contacts] ORDER BY [Center ID]")
    raw_ids = [row[0] for row in cur.fetchall()]

    skipped_null = 0
    counts = {"happy": 0, "no_auth": 0, "absent": 0, "no_enrollment": 0}

    for idx, raw_id in enumerate(raw_ids):
        if raw_id is None:
            skipped_null += 1
            continue
        cid = int(raw_id)
        variant = idx % 30
        if variant == 9:
            # No Authorization
            _enroll(cid)
            _make_available(cid)
            counts["no_auth"] += 1
        elif variant == 19:
            # Absent entire month
            _enroll(cid)
            _authorize(cid)
            _make_available(cid)
            _mark_absent_month(cid)
            counts["absent"] += 1
        elif variant == 29:
            # No Enrollment
            _authorize(cid)
            _make_available(cid)
            counts["no_enrollment"] += 1
        else:
            # Happy path
            _enroll(cid)
            _authorize(cid)
            _make_available(cid)
            counts["happy"] += 1

    conn.commit()

    total = sum(counts.values())
    print(
        f"Seeded populate_real_members: {counts['happy']} happy / "
        f"{counts['no_auth']} no-auth / {counts['absent']} absent / "
        f"{counts['no_enrollment']} no-enrollment ({total} members total)"
    )
    if skipped_null:
        print(
            f"  (skipped {skipped_null} Contacts row(s) with NULL Center ID)"
        )


def _seed_one_off_conflict(conn, today: date) -> None:
    """Seed: a single member with a one-off on a day they're also
    absent on. Exercises the OneOffConflict path end-to-end.

    Layout:
      - Enrollment: this month + next month.
      - Authorization: this month + next month, Mon/Wed/Fri (1,3,5).
      - Availability: Mon 09:00-15:00 (recurring), Wed 09:00-15:00,
        Fri 09:00-15:00.
      - Absence: a single day = first Monday of this month.
      - OneOffAvailability: the SAME first Monday, 12:00-16:00 ->
        conflict reason names both rows: 'one-off availability
        12:00-16:00 on YYYY-MM-DD (OneOffAvailability row N) conflicts
        with a Sick absence covering ... (Absences row N)'.
    """
    m1, _, mlast, mnext_last = _month_bounds(today)
    cid = 100100

    # Supply Long Lat so the CLI skips the Geocoding API during tests.
    # The route entry for this coordinate must be pre-seeded in the geo
    # cache the test passes via --geo-cache (see test_smoke.py).
    _seed_member(conn, cid, "Conflict", "Sample",
                 long_lat="-74.00600,40.71280")

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO [Enrollment] ([Center ID], [start_date], [end_date]) "
        "VALUES (?, ?, ?)",
        cid, _dt(m1), _dt(mnext_last),
    )
    cur.execute(
        "INSERT INTO [Authorization] ([Center ID], [auth_start], [auth_end], "
        "[effective_start], [effective_end], [auth_days], [Health Plan], "
        "[Plan Type]) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        cid, _dt(m1), _dt(mnext_last), _dt(m1), _dt(mnext_last),
        "1,3,5", "HOF", "MLTC",
    )
    for dow in (1, 3, 5):
        cur.execute(
            "INSERT INTO [Availability] ([Center ID], "
            "[effective_start_date], [effective_end_date], [Day Of Week], "
            "[avail_start], [avail_end]) VALUES (?, ?, ?, ?, ?, ?)",
            cid, _dt(m1), None, dow, _hhmm(9, 0), _hhmm(15, 0),
        )

    # First Monday of this month is the conflict day.
    first_monday = m1
    while first_monday.isoweekday() != 1:
        first_monday = first_monday + timedelta(days=1)

    cur.execute(
        "INSERT INTO [Absences] ([Center ID], [Leave Type], "
        "[Start_Date], [End_Date], [Notes]) VALUES (?, ?, ?, ?, ?)",
        cid, "Sick", _dt(first_monday), _dt(first_monday), "",
    )

    _seed_one_off(
        conn, cid, first_monday,
        start_hm=(12, 0), end_hm=(16, 0),
        notes="doctor appt 8-12",
    )
    conn.commit()


SCENARIOS: dict[str, Callable] = {
    "happy_path": seed_happy_path,
    "missing_data": seed_missing_data,
    "mid_period_change": seed_mid_period_change,
    "one_off_conflict": _seed_one_off_conflict,
    "plan_full": seed_plan_full,
    "populate_real_members": seed_populate_real_members,
}


# ── Settings flip ─────────────────────────────────────────────────────

def _update_settings_db_path(target: str) -> None:
    """Flip bsca_settings.json's db_path to `target`, preserving every
    other key. Uses gui.app_settings so language and other prefs stay."""
    from gui import app_settings
    settings = app_settings.load()
    settings["db_path"] = os.path.abspath(target)
    app_settings.save(settings)


# ── CLI ────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create or reset an Access test DB seeded with one of the "
            "named scenarios."
        ),
    )
    parser.add_argument(
        "--scenario", required=True, choices=sorted(SCENARIOS),
        help="Which seed scenario to apply to the target DB.",
    )
    parser.add_argument(
        "--output",
        help="Target .accdb path (default: test_dbs/<scenario>.accdb).",
    )
    parser.add_argument(
        "--source", default=DEFAULT_SOURCE,
        help=(
            "Reference Access DB to copy from when creating a new target. "
            "Only used when the target file does not already exist."
        ),
    )
    parser.add_argument(
        "--use", action="store_true",
        help="Update bsca_settings.json to point the GUI at the new DB.",
    )
    args = parser.parse_args(argv)

    target = args.output or os.path.join("test_dbs", f"{args.scenario}.accdb")
    target = os.path.abspath(target)

    if not os.path.exists(target):
        if not os.path.exists(args.source):
            print(
                f"Source DB not found: {args.source}\n"
                "Pass --source to point at a different reference DB.",
                file=sys.stderr,
            )
            return 2
        target_dir = os.path.dirname(target)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(args.source, target)
        print(f"Copied {args.source} -> {target}")

    import pyodbc
    try:
        conn = pyodbc.connect(_build_connection_string(target))
    except pyodbc.Error as exc:
        print(
            f"Could not open the test DB at {target}.\n"
            f"If Access has this file open, close it first.\n"
            f"Original error: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        _ensure_plan_type_column(conn)
        # Must run before _truncate: Holidays is in the truncate list.
        _ensure_calendar_tables(conn)
        truncate_tables = (
            SUPPORTING_TABLES
            if args.scenario in SCENARIOS_KEEP_CONTACTS
            else DATA_TABLES
        )
        _truncate(conn, truncate_tables)
        SCENARIOS[args.scenario](conn, date.today())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"Seeded scenario '{args.scenario}' into {target}")

    if args.use:
        _update_settings_db_path(target)
        print(f"Updated bsca_settings.json db_path -> {target}")

    return 0


if __name__ == "__main__":
    # When run as `python scripts/make_test_db.py`, Python only puts
    # the script's own dir on sys.path. Add the project root so the
    # lazy `from gui import app_settings` inside --use works.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.exit(main())
