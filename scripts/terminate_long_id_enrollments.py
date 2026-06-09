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
    # Implemented in Task 2.
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
