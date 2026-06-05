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
import csv
import datetime
import os
import sys
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monthly_schedule.auth_days import (  # noqa: E402
    format_auth_days,
    get_authorized_weekdays,
)


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

_CSV_COLUMNS = [
    "center_id", "last_name", "first_name",
    "action", "missing_fields",
]


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _is_blank(value):
    """True for NULL or a string that is empty / whitespace-only."""
    if value is None:
        return True
    return not str(value).strip()


def _is_test_id(center_id):
    """True if the Center ID, rendered as a base-10 integer, ends in '00'.
    Used by the --exclude-test-members flag to filter scratch members."""
    return str(int(center_id)).endswith("00")


def _fmt_date(value):
    """Render a per-row date for stdout. Access columns typed
    Date/Time come back from pyodbc as datetime; columns typed
    Short Text (some real-world Contacts use this for Auth BGN /
    Auth EXP) come back as str. Handle both."""
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y-%m-%d %H:%M:%S",
)


def _coerce_date(value):
    """Normalize a Contacts.[Auth BGN] / Contacts.[Auth EXP] value
    into a datetime that pyodbc can bind into the Authorization
    table's DATETIME columns. Access columns typed Date/Time come
    back from pyodbc as datetime (pass-through); columns typed Short
    Text come back as str and need parsing.

    Returns None if the value is NULL, blank, or doesn't match any
    supported format — that signals the caller to treat the field as
    missing and skip the member."""
    if value is None:
        return None
    if hasattr(value, "year"):  # datetime or date
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


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
    p.add_argument("--exclude-test-members", action="store_true",
                   help="Skip members whose Center ID ends in '00'.")
    return p.parse_args(argv)


def _read_contacts(conn):
    """Yield (cid:int, last, first, health_plan, sadc, auth_bgn,
    auth_exp) tuples. Rows with NULL Center ID are skipped silently."""
    cur = conn.cursor()
    cur.execute(_CONTACTS_QUERY)
    for row in cur.fetchall():
        cid, last, first, plan, sadc, bgn, exp = row
        if cid is None:
            continue
        yield (int(cid), last, first, plan, sadc, bgn, exp)


def _write_skipped_csv(rows, out_dir, today):
    """Write the skipped-members CSV to
    `<out_dir>/auth_backfill_skipped_<YYYY-MM-DD>.csv`. Returns the
    path written. Writes the header even if `rows` is empty so the
    file's presence signals 'a backfill ran on this date'.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir,
        f"auth_backfill_skipped_{today.isoformat()}.csv",
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


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


def _process_insert_branch(cur, center_id, sadc, auth_bgn, auth_exp,
                           health_plan, stats):
    """Insert one Authorization row from the legacy Contacts columns.

    Returns one of:
      ("inserted", None)                 — row was inserted
      ("skipped_missing", [field, ...])  — listed legacy fields were
                                           NULL/empty; nothing inserted
    """
    auth_days_str = format_auth_days(get_authorized_weekdays(sadc))
    bgn = _coerce_date(auth_bgn)
    exp = _coerce_date(auth_exp)
    missing = []
    if auth_days_str == "":
        missing.append("SADC")
    if bgn is None:
        missing.append("Auth BGN")
    if exp is None:
        missing.append("Auth EXP")
    if _is_blank(health_plan):
        missing.append("Health Plan")
    if missing:
        return ("skipped_missing", missing)
    cur.execute(
        _AUTH_INSERT,
        str(center_id),
        bgn, exp,
        bgn, exp,
        auth_days_str,
        str(health_plan).strip(),
    )
    stats["inserted_members"] += 1
    return ("inserted", None)


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
        today = datetime.date.today()
        stats = {
            "scanned": 0,
            "test_skipped": 0,
            "updated_members": 0,
            "updated_rows": 0,
            "noop_members": 0,
            "skipped_no_plan_members": 0,
            "inserted_members": 0,
            "skipped_missing_members": 0,
        }
        skipped_rows = []

        for cid, last, first, plan, sadc, bgn, exp in _read_contacts(conn):
            stats["scanned"] += 1

            if args.exclude_test_members and _is_test_id(cid):
                stats["test_skipped"] += 1
                if not args.quiet:
                    print(f"  TEST-SKIP {cid}  (Center ID ends in 00)")
                continue

            # Branch decision: any existing Authorization row for this
            # member?
            cur.execute(_AUTH_SELECT_FOR_MEMBER, str(cid))
            existing = cur.fetchall()
            if existing:
                # UPDATE branch. _process_update_branch re-issues the
                # SELECT internally; pass the already-fetched rows by
                # re-binding the cursor is unnecessary because Access
                # cursors don't allow result reuse cleanly. The second
                # SELECT is cheap.
                result, n = _process_update_branch(
                    cur, cid, plan, stats,
                )
                if result == "updated":
                    if not args.quiet:
                        print(f"  UPDATED   {cid}  filled {n} row(s) "
                              f"with {str(plan).strip()!r}")
                elif result == "noop":
                    stats["noop_members"] += 1
                else:  # "skipped_no_plan"
                    stats["skipped_no_plan_members"] += 1
                    skipped_rows.append({
                        "center_id": cid,
                        "last_name": last or "",
                        "first_name": first or "",
                        "action": "no_health_plan_for_update",
                        "missing_fields": "Health Plan",
                    })
                    if not args.quiet:
                        print(f"  SKIPPED   {cid}  no Health Plan on "
                              f"Contacts (had {len(existing)} existing "
                              f"auth {'row' if len(existing) == 1 else 'rows'})")
            else:
                # INSERT branch.
                result, payload = _process_insert_branch(
                    cur, cid, sadc, bgn, exp, plan, stats,
                )
                if result == "inserted":
                    if not args.quiet:
                        days = format_auth_days(
                            get_authorized_weekdays(sadc)
                        )
                        print(f"  INSERTED  {cid}  "
                              f"{str(plan).strip()}, {days}, "
                              f"{_fmt_date(bgn)} -> {_fmt_date(exp)}")
                else:  # "skipped_missing"
                    stats["skipped_missing_members"] += 1
                    skipped_rows.append({
                        "center_id": cid,
                        "last_name": last or "",
                        "first_name": first or "",
                        "action": "missing_legacy_fields",
                        "missing_fields": "; ".join(payload),
                    })
                    if not args.quiet:
                        print(f"  SKIPPED   {cid}  no existing auth + "
                              f"missing: {', '.join(payload)}")

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        csv_path = _write_skipped_csv(skipped_rows, args.csv_out, today)

        print()
        print("Authorization backfill summary")
        print(f"  Contacts scanned:                            "
              f"{stats['scanned']}")
        print(f"  Test members excluded (--exclude-test-members): "
              f"{stats['test_skipped']}")
        print(f"  Existing-auth members: Health Plan filled:   "
              f"{stats['updated_members']}   "
              f"(rows updated: {stats['updated_rows']})")
        print(f"  Existing-auth members: already populated:    "
              f"{stats['noop_members']}")
        print(f"  Existing-auth members: skipped (no plan):    "
              f"{stats['skipped_no_plan_members']}")
        print(f"  No-auth members: Authorization inserted:     "
              f"{stats['inserted_members']}")
        print(f"  No-auth members: skipped (missing legacy):   "
              f"{stats['skipped_missing_members']}")
        print(f"  Skipped CSV: {csv_path}")
        print(f"  Mode: {mode}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
