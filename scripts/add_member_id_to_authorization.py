"""Add the [Member ID] column to the existing Authorization table.

`Member ID` is the member's external identifier (Medicaid-style
string), copied from Contacts.[Member ID]. The backfill populates
it at INSERT time; this migration just ensures the column exists.

Idempotent: if `[Member ID]` already exists on Authorization, the
script prints "already exists" and exits 0. Safe to run repeatedly.
"""
import argparse
import os
import sys


_ALTER_ADD_MEMBER_ID = (
    "ALTER TABLE [Authorization] ADD COLUMN [Member ID] TEXT(255)"
)


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _column_exists(cursor, table, column):
    """Return True if `column` exists on `table`. Matches column names
    case-insensitively because Access is case-insensitive."""
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
        description=(
            "Add the [Member ID] TEXT(255) column to Authorization "
            "in an existing BSCA .accdb. Populated by the backfill "
            "from Contacts.[Member ID]."
        ),
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
        if _column_exists(cur, "Authorization", "Member ID"):
            print(
                "[Member ID] already exists on Authorization; "
                "nothing to do."
            )
            return 0
        cur.execute(_ALTER_ADD_MEMBER_ID)
        conn.commit()
        if not args.quiet:
            print("  ADDED    Authorization.[Member ID]  TEXT(255)")
        print("Added: Authorization.[Member ID]")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
