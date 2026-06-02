"""Backfill the Authorization table from Contacts.

For every Contact:
  - If at least one Authorization row exists, UPDATE [Health Plan] on
    each row whose [Health Plan] is blank.
  - If no Authorization row exists, INSERT one from the legacy
    Contacts columns SADC / Auth BGN / Auth EXP / Health Plan.

Members with missing source data are skipped and written to a CSV.

See docs/superpowers/specs/2026-06-02-authorization-backfill-design.md
"""
import argparse
import os
import sys
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_CONTACTS_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[SADC], [Auth BGN], [Auth EXP] "
    "FROM [Contacts] "
    "ORDER BY [Center ID]"
)

_AUTH_SELECT_FOR_MEMBER = (
    "SELECT [ID], [Health Plan] FROM [Authorization] "
    "WHERE [Center ID] = ?"
)

_AUTH_UPDATE_HEALTH_PLAN = (
    "UPDATE [Authorization] SET [Health Plan] = ? WHERE [ID] = ?"
)

_AUTH_INSERT = (
    "INSERT INTO [Authorization] "
    "([Center ID], [auth_start], [auth_end], "
    "[effective_start], [effective_end], [auth_days], [Health Plan]) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Backfill Authorization from Contacts."
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--csv-out", default=".",
                   help="Directory for the skipped CSV. Default: cwd.")
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
    return 0  # placeholder; real work lands in later tasks


if __name__ == "__main__":
    sys.exit(main())
