"""Shorten double-zero Center IDs across every [Center ID] table.

Center IDs longer than 5 digits that end in '00' are renamed with one
trailing '00' stripped (2213400 -> 22134) in all seven tables that
carry [Center ID]: Contacts, Enrollment, Authorization, Absences,
Availability, OneOffAvailability, EmergencyContact.

Members whose shortened ID already exists anywhere are skipped
entirely and reported to a CSV — no partial rename, never auto-merged.
end_date values (including the 2000-01-01 terminations set by
terminate_long_id_enrollments.py) are never touched.

Safe to run repeatedly: a fully renamed member no longer qualifies,
and skips are read-only.
"""
import argparse
import csv
import datetime
import os
import sys
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_TABLES = [
    "Contacts",
    "Enrollment",
    "Authorization",
    "Absences",
    "Availability",
    "OneOffAvailability",
    "EmergencyContact",
]

_SCAN_TEMPLATE = "SELECT [Center ID] FROM [{table}]"

_RENAME_TEMPLATE = (
    "UPDATE [{table}] SET [Center ID] = ? WHERE [Center ID] = ?"
)

_CSV_COLUMNS = ["old_id", "new_id", "reason"]


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _qualifies(center_id):
    """True if the Center ID, rendered as a base-10 integer string, is
    more than 5 characters long AND ends with '00'. Mirrors
    `_is_long_id` in terminate_long_id_enrollments.py for handling the
    DOUBLE-typed Center ID field without trailing '.0' confusion."""
    if center_id is None:
        return False
    s = str(int(center_id))
    return len(s) > 5 and s.endswith("00")


def _new_id(center_id):
    """The shortened ID: exactly one trailing '00' stripped. The
    caller is responsible for skipping results still >5 digits."""
    return int(center_id) // 100


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Rename Center IDs longer than 5 digits that end in '00' "
            "to their stripped form (2213400 -> 22134) across all "
            "[Center ID] tables. Collisions are skipped and reported."
        ),
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--csv-out", default=".",
                   help="Directory for the skipped CSV. Default: cwd.")
    p.add_argument("--dry-run", action="store_true",
                   help="Do everything, roll back instead of commit.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-member stdout; print only the summary.")
    return p.parse_args(argv)


def _write_skipped_csv(rows, out_dir, today):
    """Write the skipped-members CSV to
    `<out_dir>/shorten_ids_skipped_<YYYY-MM-DD>.csv`. Returns the path
    written. Writes the header even if `rows` is empty so the file's
    presence signals 'a run happened on this date'."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir,
        f"shorten_ids_skipped_{today.isoformat()}.csv",
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

        # Per-table sets of distinct integer Center IDs (NULLs
        # skipped). Used for both candidate discovery and the
        # collision check.
        ids_by_table = {}
        for table in _TABLES:
            cur.execute(_SCAN_TEMPLATE.format(table=table))
            ids_by_table[table] = {
                int(row[0]) for row in cur.fetchall()
                if row[0] is not None
            }

        # Candidates come from the UNION of all tables so orphaned
        # child-table rows (qualifying ID, no Contacts row) rename too.
        all_ids = set().union(*ids_by_table.values())
        candidates = sorted(cid for cid in all_ids if _qualifies(cid))

        stats = {
            "renamed": 0,
            "skipped_collision": 0,
            "skipped_too_long": 0,
        }
        rows_updated = {table: 0 for table in _TABLES}
        skipped_rows = []

        for old_id in candidates:
            new_id = _new_id(old_id)

            if len(str(new_id)) > 5:
                reason = "still longer than 5 digits after stripping 00"
                skipped_rows.append(
                    {"old_id": old_id, "new_id": new_id, "reason": reason}
                )
                stats["skipped_too_long"] += 1
                if not args.quiet:
                    print(f"  skipped {old_id} -> {new_id} ({reason})")
                continue

            collisions = [
                t for t in _TABLES if new_id in ids_by_table[t]
            ]
            if collisions:
                reason = (
                    "target ID already exists in: " + ", ".join(collisions)
                )
                skipped_rows.append(
                    {"old_id": old_id, "new_id": new_id, "reason": reason}
                )
                stats["skipped_collision"] += 1
                if not args.quiet:
                    print(f"  skipped {old_id} -> {new_id} ({reason})")
                continue

            # No collision: rename in every table. Tables without the
            # old ID report rowcount 0 and don't pollute the counters.
            # The prefetched sets stay valid without re-scanning: the
            # mapping old->new is injective, and a qualifying old ID
            # (>5 digits) can never equal a rename target (<=5 digits).
            member_rows = 0
            tables_touched = 0
            for table in _TABLES:
                cur.execute(
                    _RENAME_TEMPLATE.format(table=table), new_id, old_id
                )
                if cur.rowcount > 0:
                    rows_updated[table] += cur.rowcount
                    member_rows += cur.rowcount
                    tables_touched += 1
            stats["renamed"] += 1
            if not args.quiet:
                print(
                    f"  renamed {old_id} -> {new_id} "
                    f"({member_rows} rows across {tables_touched} tables)"
                )

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        csv_path = _write_skipped_csv(skipped_rows, args.csv_out, today)

        print()
        print("Shorten-double-zero-ID summary")
        print(f"  Candidate IDs found (>5 digits, ends 00):  "
              f"{len(candidates)}")
        print(f"  Members renamed:                           "
              f"{stats['renamed']}")
        print("  Rows updated per table:")
        for table in _TABLES:
            print(f"    {table + ':':<21}{rows_updated[table]}")
        print(f"  Members skipped (collision):               "
              f"{stats['skipped_collision']}")
        print(f"  Members skipped (still too long):          "
              f"{stats['skipped_too_long']}")
        print(f"  Skipped CSV: {csv_path}")
        print(f"  Mode: {mode}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
