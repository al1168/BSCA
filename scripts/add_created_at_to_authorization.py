"""Add the [created_at] column to the existing Authorization table.

`created_at` is a DATETIME populated by the backfill at INSERT time
with the row's creation timestamp. Historical rows that predate
this column stay NULL — useful to distinguish "real" creation times
from legacy data.

Idempotent: if `[created_at]` already exists on Authorization, the
script prints "already exists" and exits 0. Safe to run repeatedly.
"""
import argparse
import os
import sys


_ALTER_ADD_CREATED_AT = (
    "ALTER TABLE [Authorization] ADD COLUMN [created_at] DATETIME"
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
        description=(
            "Add the [created_at] DATETIME column to Authorization "
            "in an existing BSCA .accdb. The column is populated by "
            "the backfill at INSERT time with the row's creation "
            "timestamp; legacy rows stay NULL."
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
        if _column_exists(cur, "Authorization", "created_at"):
            print(
                "[created_at] already exists on Authorization; "
                "nothing to do."
            )
            return 0
        cur.execute(_ALTER_ADD_CREATED_AT)
        conn.commit()
        if not args.quiet:
            print("  ADDED    Authorization.[created_at]  DATETIME")
        print("Added: Authorization.[created_at]")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
