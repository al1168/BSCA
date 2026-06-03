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


def _is_blank(value):
    """True for NULL or a string that is empty / whitespace-only."""
    if value is None:
        return True
    return not str(value).strip()


def _process_update_branch(cur, center_id, health_plan, stats):
    """Fill blank [Health Plan] on every Authorization row for this
    member. Returns one of:
      ("updated", N)            — N rows were filled
      ("noop", 0)               — every row was already populated
      ("skipped_no_plan", 0)    — at least one blank row but Contacts
                                  has no Health Plan to fill it with
    Stats counters bookkeep updated_members and updated_rows.
    Caller is responsible for confirming count(Authorization) > 0 before
    calling this; here we re-read the rows we'll touch.
    """
    cur.execute(_AUTH_SELECT_FOR_MEMBER, str(center_id))
    rows = cur.fetchall()
    blanks = [row_id for row_id, plan in rows if _is_blank(plan)]
    if not blanks:
        return ("noop", 0)
    if _is_blank(health_plan):
        return ("skipped_no_plan", 0)
    for row_id in blanks:
        cur.execute(_AUTH_UPDATE_HEALTH_PLAN,
                    str(health_plan).strip(), int(row_id))
    stats["updated_members"] += 1
    stats["updated_rows"] += len(blanks)
    return ("updated", len(blanks))


from monthly_schedule.auth_days import (
    get_authorized_weekdays, format_auth_days,
)


def _process_insert_branch(cur, center_id, sadc, auth_bgn, auth_exp,
                           health_plan, stats):
    """Insert one Authorization row from the legacy Contacts columns.

    Returns one of:
      ("inserted", None)                 — row was inserted
      ("skipped_missing", [field, ...])  — listed legacy fields were
                                           NULL/empty; nothing inserted
    """
    auth_days_str = format_auth_days(get_authorized_weekdays(sadc))
    missing = []
    if auth_days_str == "":
        missing.append("SADC")
    if auth_bgn is None:
        missing.append("Auth BGN")
    if auth_exp is None:
        missing.append("Auth EXP")
    if _is_blank(health_plan):
        missing.append("Health Plan")
    if missing:
        return ("skipped_missing", missing)
    cur.execute(
        _AUTH_INSERT,
        str(center_id),
        auth_bgn, auth_exp,
        auth_bgn, auth_exp,
        auth_days_str,
        str(health_plan).strip(),
    )
    stats["inserted_members"] += 1
    return ("inserted", None)


if __name__ == "__main__":
    sys.exit(main())
