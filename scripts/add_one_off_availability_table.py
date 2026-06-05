"""Add the OneOffAvailability table to an existing BSCA .accdb.

This is an idempotent migration for databases that were already
bootstrapped with the original four supporting tables (Enrollment,
Authorization, Absences, Availability) before OneOffAvailability
existed. Safe to run repeatedly: if the table already exists, the
script exits cleanly with an "already exists" message instead of
raising.

See docs/superpowers/specs/2026-06-04-one-off-availability-design.md.
"""
import argparse
import os
import sys


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


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _table_exists(cursor, name):
    """Return True if `name` is an existing user table.

    Uses the pyodbc tables() metadata accessor (Access exposes its
    schema through ODBC). Filtering by table_type='TABLE' excludes
    system tables and queries."""
    try:
        rows = cursor.tables(table=name, tableType="TABLE").fetchall()
        return any(r.table_name == name for r in rows)
    except Exception:
        # Fall back to a SELECT TOP 0 — if the table is absent, Access
        # raises; treat the raise as "absent".
        try:
            cursor.execute(f"SELECT TOP 0 * FROM [{name}]")
            return True
        except Exception:
            return False


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Add the OneOffAvailability table to an existing BSCA .accdb."
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
        if _table_exists(cur, "OneOffAvailability"):
            print("OneOffAvailability already exists; nothing to do.")
            return 0
        cur.execute(_CREATE_ONE_OFF_AVAILABILITY)
        conn.commit()
        if not args.quiet:
            print("  CREATED  OneOffAvailability")
        print("Created: OneOffAvailability")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
