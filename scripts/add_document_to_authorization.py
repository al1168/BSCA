"""Add the [Document] column to the existing Authorization table.

Each Authorization row corresponds to one signed authorization
document; the [Document] column stores the PDF/DOC bytes that back
it. This script is the one-shot migration for an `.accdb` whose
Authorization table predates that column.

Idempotent: if `[Document]` already exists on Authorization, the
script prints "already exists" and exits 0. Safe to run repeatedly.

The column is added as `OLEOBJECT` (reported as `LONGBINARY` by the
ODBC catalog). In Access this shows as the legacy "OLE Object" type
— right-click a cell, choose Insert Object → Create from File, then
browse to the PDF. The bytes live inside the .accdb; double-click
later to open with the registered handler.

Why not the modern ATTACHMENT type? It's a DAO/COM-only feature
that the Access ODBC driver rejects in `ALTER TABLE ... ADD COLUMN`
statements ("Syntax error in field definition"). If you want
multi-file attachments per row, add the field manually via the
Access design view.
"""
import argparse
import os
import sys


_ALTER_ADD_DOCUMENT = (
    "ALTER TABLE [Authorization] ADD COLUMN [Document] OLEOBJECT"
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
            "Add the [Document] column to Authorization in an "
            "existing BSCA .accdb. The column stores the file path "
            "or filename of the PDF/DOC document backing the auth."
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
        if _column_exists(cur, "Authorization", "Document"):
            print(
                "[Document] already exists on Authorization; "
                "nothing to do."
            )
            return 0
        cur.execute(_ALTER_ADD_DOCUMENT)
        conn.commit()
        if not args.quiet:
            print("  ADDED    Authorization.[Document]  OLEOBJECT")
        print("Added: Authorization.[Document]")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
