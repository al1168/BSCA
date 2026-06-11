"""Create the six supporting tables in an Access .accdb that already
contains a Contacts table.

Given a fresh .accdb whose only table is `Contacts`, this script
issues six CREATE TABLE statements to bring up the `Enrollment`,
`Authorization`, `Absences`, `Availability`, `OneOffAvailability`,
and `EmergencyContact` tables — every column the scheduler and the
backfill scripts read, including the `[Health Plan]` column on
`Authorization`.

The script is a one-shot DDL bootstrap. No data is touched. If a
supporting table already exists it is skipped and the script
continues with the remaining CREATE statements.

After this script succeeds, run the backfill scripts to populate
the new tables from Contacts:

  - scripts/backfill_authorization_from_contacts.py
  - scripts/backfill_availability_from_hha.py

See docs/database.md for the schema reference.
"""
import argparse
import os
import sys


_CREATE_ENROLLMENT = (
    "CREATE TABLE [Enrollment] ("
    "[ID] AUTOINCREMENT PRIMARY KEY, "
    "[Center ID] DOUBLE, "
    "[start_date] DATETIME, "
    "[end_date] DATETIME"
    ")"
)

_CREATE_AUTHORIZATION = (
    "CREATE TABLE [Authorization] ("
    "[ID] AUTOINCREMENT PRIMARY KEY, "
    "[Center ID] DOUBLE, "
    "[auth_start] DATETIME, "
    "[auth_end] DATETIME, "
    "[effective_start] DATETIME, "
    "[effective_end] DATETIME, "
    "[auth_days] TEXT(255), "
    "[notes] MEMO, "
    "[Health Plan] TEXT(255)"
    ")"
)

_CREATE_ABSENCES = (
    "CREATE TABLE [Absences] ("
    "[ID] AUTOINCREMENT PRIMARY KEY, "
    "[Center ID] DOUBLE, "
    "[Leave Type] TEXT(255), "
    "[Start_Date] DATETIME, "
    "[End_Date] DATETIME, "
    "[Notes] MEMO"
    ")"
)

_CREATE_AVAILABILITY = (
    "CREATE TABLE [Availability] ("
    "[ID] AUTOINCREMENT PRIMARY KEY, "
    "[Center ID] DOUBLE, "
    "[effective_start_date] DATETIME, "
    "[effective_end_date] DATETIME, "
    "[Day Of Week] LONG, "
    "[avail_start] DATETIME, "
    "[avail_end] DATETIME, "
    "[Notes] MEMO"
    ")"
)

_CREATE_ONE_OFF_AVAILABILITY = (
    "CREATE TABLE [OneOffAvailability] ("
    "[ID] AUTOINCREMENT PRIMARY KEY, "
    "[Center ID] DOUBLE, "
    "[date] DATETIME, "
    "[avail_start] DATETIME, "
    "[avail_end] DATETIME, "
    "[Notes] MEMO"
    ")"
)

_CREATE_EMERGENCY_CONTACT = (
    "CREATE TABLE [EmergencyContact] ("
    "[ID] AUTOINCREMENT PRIMARY KEY, "
    "[Center ID] DOUBLE, "
    "[Full Name] TEXT(255), "
    "[Phone Number] TEXT(50), "
    "[Relationship] TEXT(100)"
    ")"
)

_DDLS = [
    ("Enrollment", _CREATE_ENROLLMENT),
    ("Authorization", _CREATE_AUTHORIZATION),
    ("Absences", _CREATE_ABSENCES),
    ("Availability", _CREATE_AVAILABILITY),
    ("OneOffAvailability", _CREATE_ONE_OFF_AVAILABILITY),
    ("EmergencyContact", _CREATE_EMERGENCY_CONTACT),
]


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Create the six supporting tables (Enrollment, "
            "Authorization, Absences, Availability, OneOffAvailability, "
            "EmergencyContact) in an Access .accdb that already "
            "contains Contacts."
        )
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-table stdout; print only the summary.")
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
        created = []
        skipped = []
        for name, ddl in _DDLS:
            try:
                cur.execute(ddl)
                created.append(name)
                if not args.quiet:
                    print(f"  CREATED  {name}")
            except Exception as exc:
                # 42S01 = table already exists; skip gracefully.
                if "42S01" in str(exc):
                    skipped.append(name)
                    if not args.quiet:
                        print(f"  SKIPPED  {name} (already exists)")
                else:
                    raise
        conn.commit()
        parts = []
        if created:
            parts.append(f"Created: {', '.join(created)}")
        if skipped:
            parts.append(f"Skipped (already exist): {', '.join(skipped)}")
        print("; ".join(parts) if parts else "Nothing to do.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
