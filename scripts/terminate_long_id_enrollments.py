"""Mark long-ID Enrollment rows as terminated.

For every Enrollment row whose member's [Center ID] is more than 5
digits long AND whose end_date is currently NULL: set end_date to
2000-01-01. Rows that already have a non-null end_date are left
alone.

Processing is member-centric: a member with multiple Enrollment rows
(some open, some closed) gets ONE update and is reported ONCE.

Designed to be safe to run repeatedly. The eligibility logic in
monthly_schedule/per_day.py filters out members whose enrollment
ended before the target month, so terminated members silently drop
out of every future schedule run.
"""
import argparse
import csv
import datetime
import os
import sys
from collections import defaultdict
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


TERMINATION_DATE = datetime.date(2000, 1, 1)


_ENROLLMENT_SCAN = (
    "SELECT [Center ID], [end_date] FROM [Enrollment] "
    "ORDER BY [Center ID]"
)

_ENROLLMENT_TERMINATE = (
    "UPDATE [Enrollment] SET [end_date] = ? "
    "WHERE [Center ID] = ? AND [end_date] IS NULL"
)

_CSV_COLUMNS = ["center_id", "existing_end_date", "reason"]


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _is_long_id(center_id):
    """True if the Center ID, rendered as a base-10 integer string,
    is more than 5 characters long. Mirrors `_is_test_id` in
    backfill_enrollment_from_contacts.py for handling the DOUBLE-typed
    Center ID field without trailing '.0' confusion."""
    if center_id is None:
        return False
    return len(str(int(center_id))) > 5


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Terminate Enrollment rows for members whose Center ID "
            "is more than 5 digits long, by setting end_date = 2000-01-01."
        ),
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--csv-out", default=".",
                   help="Directory for the skipped CSV. Default: cwd.")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse + write CSV, do NOT commit DB changes.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-member stdout; print only the summary.")
    return p.parse_args(argv)


def _write_skipped_csv(rows, out_dir, today):
    """Write the skipped-members CSV to
    `<out_dir>/terminate_long_id_skipped_<YYYY-MM-DD>.csv`. Returns the
    path written. Writes the header even if `rows` is empty so the
    file's presence signals 'a termination ran on this date'."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir,
        f"terminate_long_id_skipped_{today.isoformat()}.csv",
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


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

        # Scan + group by Center ID. Skip None and short-ID rows here
        # so they don't pollute the group map or the counts.
        cur.execute(_ENROLLMENT_SCAN)
        scan_rows = cur.fetchall()
        rows_by_cid = defaultdict(list)
        rows_scanned = len(scan_rows)
        for cid, end_date in scan_rows:
            if cid is None or not _is_long_id(cid):
                continue
            rows_by_cid[int(cid)].append(end_date)

        stats = {
            "rows_scanned": rows_scanned,
            "long_id_members": len(rows_by_cid),
            "members_terminated": 0,
            "rows_updated": 0,
            "members_skipped": 0,
        }
        skipped_rows = []

        # Convert TERMINATION_DATE to a datetime at midnight for
        # pyodbc — matches the pattern used by
        # backfill_enrollment_from_contacts.py for Access DATETIME
        # columns.
        term_dt = datetime.datetime(
            TERMINATION_DATE.year,
            TERMINATION_DATE.month,
            TERMINATION_DATE.day,
        )

        # Process each long-ID member exactly once.
        for cid in sorted(rows_by_cid):
            end_dates = rows_by_cid[cid]
            if any(ed is None for ed in end_dates):
                # At least one open Enrollment row — terminate this member.
                cur.execute(_ENROLLMENT_TERMINATE, term_dt, cid)
                stats["members_terminated"] += 1
                stats["rows_updated"] += cur.rowcount
                if not args.quiet:
                    print(
                        f"  terminated cid={cid} "
                        f"({cur.rowcount} rows)"
                    )
            else:
                # Every row already ended — record in the CSV.
                latest = max(end_dates)
                latest_iso = (
                    latest.date().isoformat()
                    if isinstance(latest, datetime.datetime)
                    else latest.isoformat()
                )
                skipped_rows.append({
                    "center_id": cid,
                    "existing_end_date": latest_iso,
                    "reason": "end_date already set",
                })
                stats["members_skipped"] += 1
                if not args.quiet:
                    print(
                        f"  skipped cid={cid} "
                        f"(existing end_date={latest_iso})"
                    )

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        csv_path = _write_skipped_csv(skipped_rows, args.csv_out, today)

        print()
        print("Terminate-long-ID summary")
        print(f"  Enrollment rows scanned:             "
              f"{stats['rows_scanned']}")
        print(f"  Long-ID members found (>5 digits):   "
              f"{stats['long_id_members']}")
        print(f"  Members terminated (end_date set):   "
              f"{stats['members_terminated']}")
        print(f"  Enrollment rows updated:             "
              f"{stats['rows_updated']}")
        print(f"  Members skipped (all already ended): "
              f"{stats['members_skipped']}")
        print(f"  Skipped CSV: {csv_path}")
        print(f"  Mode: {mode}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
