"""Add the [Long Lat] column to the existing Contacts table.

The scheduler reads `Contacts.[Long Lat]` (see monthly_schedule/db.py)
to skip geocoding when a pre-computed coordinate pair is already
stored on the member. This script is the one-shot migration for an
`.accdb` whose Contacts table predates that column.

Idempotent: if `[Long Lat]` already exists on Contacts, the script
prints "already exists" and exits 0. Safe to run repeatedly.

The column is added as `TEXT(255)` to match the convention used by
other string columns on the supporting tables (e.g. `[Health Plan]`).
Values are stored as `"<lat>,<long>"` strings.
"""
import argparse
import os
import sys


_ALTER_ADD_LONG_LAT = (
    "ALTER TABLE [Contacts] ADD COLUMN [Long Lat] TEXT(255)"
)


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _column_exists(cursor, table, column):
    """Return True if `column` exists on `table`.

    Uses the pyodbc columns() metadata accessor — Access exposes
    column metadata through ODBC. Matches column names
    case-insensitively because Access is case-insensitive on
    identifiers."""
    try:
        rows = cursor.columns(table=table).fetchall()
        target = column.lower()
        return any(r.column_name.lower() == target for r in rows)
    except Exception:
        # Fallback: try to SELECT the column. If it raises, the column
        # is absent (or the table is) — both are "treat as absent".
        try:
            cursor.execute(f"SELECT TOP 0 [{column}] FROM [{table}]")
            return True
        except Exception:
            return False


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Add the [Long Lat] column to Contacts in an existing BSCA .accdb."
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-column stdout; print only the summary.")
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
        if _column_exists(cur, "Contacts", "Long Lat"):
            print("[Long Lat] already exists on Contacts; nothing to do.")
            return 0
        cur.execute(_ALTER_ADD_LONG_LAT)
        conn.commit()
        if not args.quiet:
            print("  ADDED    Contacts.[Long Lat]  TEXT(255)")
        print("Added: Contacts.[Long Lat]")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
