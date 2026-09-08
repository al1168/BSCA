"""Add the [Plan Type] column to the existing Authorization table.

`Plan Type` is a free-text label for the kind of plan behind the
authorization. Nothing populates it yet — rows are left empty until
filled in by hand (or a future backfill); this migration just
ensures the column exists.

Idempotent: if `[Plan Type]` already exists on Authorization, the
script prints "already exists" and exits 0. Safe to run repeatedly.
"""
import argparse
import os
import sys


_ALTER_ADD_PLAN_TYPE = (
    "ALTER TABLE [Authorization] ADD COLUMN [Plan Type] TEXT(255)"
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
            "Add the [Plan Type] TEXT(255) column to Authorization "
            "in an existing BSCA .accdb. Left empty; filled in by "
            "hand (or a future backfill)."
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
        if _column_exists(cur, "Authorization", "Plan Type"):
            print(
                "[Plan Type] already exists on Authorization; "
                "nothing to do."
            )
            return 0
        cur.execute(_ALTER_ADD_PLAN_TYPE)
        conn.commit()
        if not args.quiet:
            print("  ADDED    Authorization.[Plan Type]  TEXT(255)")
        print("Added: Authorization.[Plan Type]")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
