"""Backfill the Availability table from Contacts.HHA free text.

Reads every non-empty HHA row, classifies it via
monthly_schedule.hha_parser, then writes end-of-day constraints to
Availability. Ambiguous rows are emitted to a dated CSV in --csv-out.

See docs/superpowers/specs/2026-06-01-hha-availability-backfill-design.md
"""
import argparse
import csv
import datetime
import os
import sys
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monthly_schedule.hha_parser import parse_hha_row  # noqa: E402


_CONTACTS_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [HHA] "
    "FROM [Contacts]"
)


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _read_contacts(conn):
    """Yield (center_id:int, last_name, first_name, hha_text) tuples.
    Rows with NULL Center ID or NULL/empty HHA are skipped here so
    downstream code only sees actionable rows.
    """
    cur = conn.cursor()
    cur.execute(_CONTACTS_QUERY)
    for row in cur.fetchall():
        center_id, last, first, hha = row
        if center_id is None:
            continue
        if hha is None or not str(hha).strip():
            continue
        yield int(center_id), last, first, str(hha)


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Backfill Availability from Contacts.HHA."
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--csv-out", default=".",
                   help="Directory for the ambiguous CSV. Default: cwd.")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse + write CSV, do NOT commit DB changes.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-row stdout; print only the summary.")
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
        count = 0
        for cid, last, first, hha in _read_contacts(conn):
            _ = parse_hha_row(hha)  # ignored — wired in next task
            count += 1
        print(f"Read {count} non-empty HHA rows. (no writes yet)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
