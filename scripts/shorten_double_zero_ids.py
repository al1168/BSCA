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
