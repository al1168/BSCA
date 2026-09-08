"""Backfill the Enrollment table from Contacts.

For every Contact:
  - If at least one Enrollment row exists, skip the member (idempotent).
  - If no Enrollment row exists, INSERT one with:
      - start_date = parsed Contacts.[Admission Date] when valid,
        otherwise the most-recent May 31 fallback.
      - end_date = NULL (open-ended), or 2000-01-01 for long-IDs when
        `--terminate-long-ids` is set.

Designed to be safe to run repeatedly. The `--exclude-test-members`
flag suppresses members whose Center ID ends in "00" (a convention
the operator uses to mark test/scratch members).

Members whose admission date can't be parsed (typos, NULL/empty,
unrecognized format) are still enrolled with the fallback date, AND
their row is appended to the skipped CSV so the operator can fix
the source data later.
"""
import argparse
import csv
import datetime
import os
import sys
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_CONTACTS_QUERY = (
    "SELECT [Center ID], [Admission Date] "
    "FROM [Contacts] "
    "ORDER BY [Center ID]"
)

_ENROLLMENT_COUNT_FOR_MEMBER = (
    "SELECT COUNT(*) FROM [Enrollment] WHERE [Center ID] = ?"
)

_ENROLLMENT_INSERT = (
    "INSERT INTO [Enrollment] "
    "([Center ID], [start_date], [end_date]) "
    "VALUES (?, ?, ?)"
)

_CSV_COLUMNS = ["center_id", "raw_admission_date", "action"]


# Plausible year bounds for admission dates — rejects typos like
# "20167" or 3-digit-year forms like "024".
_MIN_ADMISSION_YEAR = 1990
_MAX_ADMISSION_YEAR = 2100


def _parse_admission_date(text):
    """Return a `datetime.date` parsed from `text`, or None when text
    is missing or unparseable.

    Access columns typed Date/Time come back from pyodbc as datetime
    objects (pass through); columns typed Short Text come back as str
    and are parsed as `M/D/YYYY`, `MM/D/YYYY`, `M/DD/YYYY`,
    `MM/DD/YYYY` — i.e. anything `datetime.strptime("%m/%d/%Y")`
    handles. Either way the year is sanity-checked against
    [_MIN_ADMISSION_YEAR, _MAX_ADMISSION_YEAR]."""
    if text is None:
        return None
    if hasattr(text, "year"):  # datetime or date from a Date/Time column
        parsed = text.date() if hasattr(text, "date") else text
    else:
        s = str(text).strip()
        if not s:
            return None
        try:
            parsed = datetime.datetime.strptime(s, "%m/%d/%Y").date()
        except ValueError:
            return None
    if not (_MIN_ADMISSION_YEAR <= parsed.year <= _MAX_ADMISSION_YEAR):
        return None
    return parsed


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _is_test_id(center_id):
    """True if the Center ID, rendered as a base-10 integer, ends in '00'.
    Used by the --exclude-test-members flag to filter scratch members."""
    return str(int(center_id)).endswith("00")


def _is_long_id(center_id):
    """True if the Center ID, rendered as a base-10 integer string, is
    more than 5 characters long. Used by the --terminate-long-ids flag
    to insert long-ID enrollments as already-terminated."""
    if center_id is None:
        return False
    return len(str(int(center_id))) > 5


def _default_start_date(today):
    """Return the most-recent May 31 that's on or before `today`.

    Today is 2026-06-11 → 2026-05-31 (this year's May).
    Today is 2026-04-15 → 2025-05-31 (last year's May, since this
    year's hasn't happened yet).
    Today is 2026-05-31 → 2026-05-31 (exact match)."""
    candidate = datetime.date(today.year, 5, 31)
    if candidate > today:
        candidate = datetime.date(today.year - 1, 5, 31)
    return candidate


TERMINATION_DATE = datetime.date(2000, 1, 1)


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Backfill Enrollment from Contacts."
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
    p.add_argument("--terminate-long-ids", action="store_true",
                   help="Insert enrollments with end_date=2000-01-01 "
                        "for members whose Center ID is more than 5 "
                        "digits. Same end-date marker as the "
                        "terminate_long_id_enrollments script.")
    return p.parse_args(argv)


def _read_contacts(conn):
    """Yield (cid, admission_text) tuples. Rows with NULL Center ID
    are skipped silently. `admission_text` is the raw value of
    Contacts.[Admission Date] — None or empty when the cell is blank."""
    cur = conn.cursor()
    cur.execute(_CONTACTS_QUERY)
    for row in cur.fetchall():
        cid, admission = row
        if cid is None:
            continue
        yield int(cid), admission


def _write_skipped_csv(rows, out_dir, today):
    """Write the skipped-members CSV to
    `<out_dir>/enrollment_backfill_skipped_<YYYY-MM-DD>.csv`. Returns the
    path written. Writes the header even if `rows` is empty so the
    file's presence signals 'a backfill ran on this date'.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir,
        f"enrollment_backfill_skipped_{today.isoformat()}.csv",
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
        fallback_start_date = _default_start_date(today)
        terminated_dt = datetime.datetime(
            TERMINATION_DATE.year,
            TERMINATION_DATE.month,
            TERMINATION_DATE.day,
        )
        stats = {
            "scanned": 0,
            "test_skipped": 0,
            "already_enrolled": 0,
            "inserted": 0,
            "long_id_terminated": 0,
            "used_admission": 0,
            "used_fallback": 0,
        }
        skipped_rows = []

        for cid, admission_text in _read_contacts(conn):
            stats["scanned"] += 1

            if args.exclude_test_members and _is_test_id(cid):
                stats["test_skipped"] += 1
                if not args.quiet:
                    print(f"  TEST-SKIP {cid}  (Center ID ends in 00)")
                continue

            # Idempotency: skip if already enrolled.
            cur.execute(_ENROLLMENT_COUNT_FOR_MEMBER, str(cid))
            count = cur.fetchone()[0]
            if count > 0:
                stats["already_enrolled"] += 1
                # Not written to skipped CSV — this is normal idempotent behavior.
                continue

            # Pick start_date: parsed admission date, else fallback.
            parsed = _parse_admission_date(admission_text)
            if parsed is not None:
                start_date = parsed
                stats["used_admission"] += 1
                start_source = "admission"
            else:
                start_date = fallback_start_date
                stats["used_fallback"] += 1
                start_source = "fallback"
                skipped_rows.append({
                    "center_id": cid,
                    "raw_admission_date": (
                        "" if admission_text is None else str(admission_text)
                    ),
                    "action": (
                        f"inserted with fallback start_date "
                        f"{start_date.isoformat()}"
                    ),
                })

            start_dt = datetime.datetime(
                start_date.year, start_date.month, start_date.day,
            )

            # Pick end_date: terminated for long-IDs (with the flag),
            # NULL (open-ended) otherwise.
            end_dt = None
            terminated = False
            if args.terminate_long_ids and _is_long_id(cid):
                end_dt = terminated_dt
                terminated = True
                stats["long_id_terminated"] += 1

            cur.execute(_ENROLLMENT_INSERT, str(cid), start_dt, end_dt)
            stats["inserted"] += 1
            if not args.quiet:
                suffix = "  (TERMINATED long-ID)" if terminated else ""
                print(
                    f"  INSERTED  {cid}  start={start_date.isoformat()}"
                    f"  src={start_source}{suffix}"
                )

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        csv_path = _write_skipped_csv(skipped_rows, args.csv_out, today)

        print()
        print("Enrollment backfill summary")
        print(f"  Contacts scanned:                            "
              f"{stats['scanned']}")
        print(f"  Test members excluded (--exclude-test-members): "
              f"{stats['test_skipped']}")
        print(f"  Already enrolled (skipped):                  "
              f"{stats['already_enrolled']}")
        print(f"  Enrollment inserted:                         "
              f"{stats['inserted']}")
        print(f"    Used Contacts.[Admission Date]:            "
              f"{stats['used_admission']}")
        print(f"    Fell back to default start_date:           "
              f"{stats['used_fallback']}")
        if args.terminate_long_ids:
            print(f"  Long-ID inserts with end_date=2000-01-01:    "
                  f"{stats['long_id_terminated']}")
        print(f"  Fallback start_date: {fallback_start_date.isoformat()}")
        print(f"  Skipped CSV: {csv_path}")
        print(f"  Mode: {mode}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
