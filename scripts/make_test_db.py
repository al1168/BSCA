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
SUPPORTING_TABLES = ("Availability", "Absences", "Authorization",
                     "Enrollment")
DATA_TABLES = SUPPORTING_TABLES + ("Contacts",)

# Scenarios that should preserve the real Contacts table and only
# truncate the four supporting tables. Used by main() to decide which
# list to hand _truncate().
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
                 address: str = "123 Test St, New York, NY 10001") -> None:
    """Insert one Contacts row with only the columns the scheduler reads.
    Contacts.[Center ID] is DOUBLE in Access; pyodbc widens int → float."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO [Contacts] ([Center ID], [Last Name], [First Name], "
        "[Health Plan], [Address]) VALUES (?, ?, ?, ?, ?)",
        center_id, last, first, plan, address,
    )


# ── Scenarios ─────────────────────────────────────────────────────────
# Each function takes (conn, today) and inserts rows. Truncation
# happens once before the chosen seed runs; functions assume the
# tables are empty.

def seed_happy_path(conn, today: date) -> None:
    """Center 99001 'Test, Happy' — full happy-path setup."""
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
    pass  # Implemented in Task 2.


SCENARIOS: dict[str, Callable] = {
    "happy_path": seed_happy_path,
    "missing_data": seed_missing_data,
    "mid_period_change": seed_mid_period_change,
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
