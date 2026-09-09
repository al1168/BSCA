"""Seed the OperatingDays table with the seven default rows
(Monday–Sunday, 08:00–16:00) — but only when the table is empty.

The scheduler treats a weekday with no OperatingDays row as closed,
so a freshly created table would silently close the center every day.
This one-shot fill gives every new database the 7-days-a-week default.

Idempotent: if the table already has any rows (defaults or hand edits
from the Members app's Company Calendar dialog) nothing is written, so
re-running the Setup chain never overwrites staff changes.

Runs in the Setup chain right after create_supporting_tables.
"""
import argparse
import os
import sys
from datetime import datetime


# Deliberate standalone copy of monthly_schedule.center_calendar.DAY_NAME:
# this script must run on its own (python scripts/seed_operating_days.py)
# without importing monthly_schedule.
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday")

# Time-only DATETIME values use Access's 1899-12-30 placeholder date,
# the same encoding as Availability.avail_start / avail_end.
DEFAULT_OPENING = datetime(1899, 12, 30, 8, 0)
DEFAULT_CLOSING = datetime(1899, 12, 30, 16, 0)

_COUNT_ROWS = "SELECT COUNT(*) FROM [OperatingDays]"

_INSERT_ROW = (
    "INSERT INTO [OperatingDays] "
    "([day_name], [Day Of Week], [opening_time], [closing_time]) "
    "VALUES (?, ?, ?, ?)"
)


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def seed_if_empty(cursor):
    """Insert the seven default rows when the table has none.
    Returns (existing_row_count, inserted_row_count)."""
    cursor.execute(_COUNT_ROWS)
    (existing,) = cursor.fetchone()
    existing = int(existing or 0)
    if existing:
        return existing, 0
    for day_of_week, name in enumerate(DAY_NAMES, start=1):
        cursor.execute(
            _INSERT_ROW, name, day_of_week, DEFAULT_OPENING, DEFAULT_CLOSING,
        )
    return 0, len(DAY_NAMES)


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Fill an empty OperatingDays table with Monday–Sunday "
            "08:00–16:00. Leaves a non-empty table untouched."
        ),
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if not os.path.exists(args.db):
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)
        return 2

    import pyodbc
    try:
        conn = pyodbc.connect(_build_connection_string(args.db))
    except pyodbc.Error as exc:
        print(
            "ERROR: could not open the Access database. Verify the "
            "Microsoft Access ODBC driver is installed and its "
            "bitness matches this Python interpreter. "
            f"Original error: {exc}",
            file=sys.stderr,
        )
        return 2

    try:
        cur = conn.cursor()
        existing, inserted = seed_if_empty(cur)
        conn.commit()
    finally:
        conn.close()

    if inserted:
        print(f"Seeded {inserted} operating days (Mon-Sun, 08:00-16:00)")
    else:
        print(f"OperatingDays already has {existing} rows; left unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
