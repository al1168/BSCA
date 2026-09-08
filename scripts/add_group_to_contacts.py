"""Add the [Group] column to the existing Contacts table and,
optionally, fill it with a label.

`Group` is a free-text tag for the member (one character or a short
word, chosen by the operator in the Setup GUI). Nothing in the
scheduler reads it yet; this migration just ensures the column
exists and seeds it.

Idempotent: if `[Group]` already exists on Contacts, the ALTER is
skipped. The fill (when `--group` is given) only touches rows whose
`[Group]` is NULL or empty, so re-running never overwrites a value
that was edited by hand in Access.

`Group` is a reserved word in Access SQL, so every reference is
bracketed.
"""
import argparse
import os
import sys


_ALTER_ADD_GROUP = (
    "ALTER TABLE [Contacts] ADD COLUMN [Group] TEXT(255)"
)

_UPDATE_BLANK_GROUP = (
    "UPDATE [Contacts] SET [Group] = ? "
    "WHERE [Group] IS NULL OR [Group] = ''"
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
            "Add the [Group] TEXT(255) column to Contacts in an existing "
            "BSCA .accdb and, with --group, fill blank rows with a label."
        ),
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--group", default="",
                   help=(
                       "Label to write into [Group] for every Contacts "
                       "row whose [Group] is blank. Blank/omitted: only "
                       "ensure the column exists."
                   ))
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

    group_text = (args.group or "").strip()
    try:
        cur = conn.cursor()
        if _column_exists(cur, "Contacts", "Group"):
            print("[Group] already exists on Contacts; nothing to add.")
        else:
            cur.execute(_ALTER_ADD_GROUP)
            if not args.quiet:
                print("  ADDED    Contacts.[Group]  TEXT(255)")
            print("Added: Contacts.[Group]")

        if group_text:
            cur.execute(_UPDATE_BLANK_GROUP, group_text)
            filled = cur.rowcount
            if filled is None or filled < 0:
                filled = 0
            print(
                f"Filled {filled} Contacts row(s) with "
                f"Group = '{group_text}'"
            )
        conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
