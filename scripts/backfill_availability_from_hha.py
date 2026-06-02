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

_AVAIL_OPEN_QUERY = (
    "SELECT [ID], [avail_end] FROM [Availability] "
    "WHERE [Center ID] = ? AND [Day Of Week] = ? "
    "AND [effective_end_date] IS NULL"
)

_AVAIL_UPDATE = (
    "UPDATE [Availability] SET [avail_end] = ? WHERE [ID] = ?"
)

_AVAIL_INSERT = (
    "INSERT INTO [Availability] "
    "([Center ID], [effective_start_date], [effective_end_date], "
    "[Day Of Week], [avail_start], [avail_end]) "
    "VALUES (?, ?, NULL, ?, ?, ?)"
)


def _hhmm_to_time(hhmm):
    """Convert 'HH:MM' to a datetime.time. Access stores time-only
    DATETIME fields with a 1899-12-30 placeholder; pyodbc accepts
    datetime.time for that column."""
    h, m = hhmm.split(":")
    return datetime.time(int(h), int(m))


def _apply_clause_to_db(cur, center_id, day, avail_end_hhmm, today,
                        stats):
    """One upsert: find the currently-open Availability row for
    (Center ID, Day Of Week). UPDATE if it exists with a different
    avail_end; INSERT if it doesn't. Tracks earliest-time-wins for
    repeat (day) within one row via the `proposed_ends` map carried
    by the caller (see _apply_row)."""
    new_end_time = _hhmm_to_time(avail_end_hhmm)
    cur.execute(_AVAIL_OPEN_QUERY, str(center_id), day)
    existing = cur.fetchone()
    if existing is not None:
        existing_id, existing_end = existing
        # existing_end is a datetime; compare on time of day.
        existing_end_time = existing_end.time() if hasattr(
            existing_end, "time") else existing_end
        if existing_end_time != new_end_time:
            cur.execute(_AVAIL_UPDATE, new_end_time, int(existing_id))
            stats["updated"] += 1
    else:
        cur.execute(
            _AVAIL_INSERT,
            str(center_id),
            today,
            day,
            _hhmm_to_time("08:00"),
            new_end_time,
        )
        stats["inserted"] += 1


def _apply_row(cur, center_id, parsed, today, stats):
    """For each apply clause, collapse to earliest avail_end per day
    (multi-clause same-day rule), then upsert."""
    by_day = {}  # day -> earliest avail_end HHMM
    for c in parsed["clauses"]:
        if c["status"] != "apply":
            continue
        end_hhmm = c["avail_end"]
        for d in c["days"]:
            current = by_day.get(d)
            if current is None or end_hhmm < current:
                if current is not None:
                    stats["multi_clause_same_day"] += 1
                by_day[d] = end_hhmm
    for d, end_hhmm in by_day.items():
        _apply_clause_to_db(cur, center_id, d, end_hhmm, today, stats)


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
        cur = conn.cursor()
        today = datetime.date.today()
        stats = {
            "scanned": 0,
            "ignored": 0,
            "skipped_row": 0,
            "applied": 0,
            "applied_with_ambig_clause": 0,
            "ambiguous": 0,
            "updated": 0,
            "inserted": 0,
            "clauses_after_close": 0,
            "multi_clause_same_day": 0,
        }
        ambiguous_rows = []  # filled in Task 12

        for cid, last, first, hha in _read_contacts(conn):
            stats["scanned"] += 1
            parsed = parse_hha_row(hha)
            if parsed["ignored"]:
                stats["ignored"] += 1
                continue
            stats["clauses_after_close"] += sum(
                1 for c in parsed["clauses"] if c["status"] == "skip"
            )
            if parsed["skipped"]:
                stats["skipped_row"] += 1
                continue
            if parsed["applied"]:
                stats["applied"] += 1
                if parsed["ambiguous"]:
                    stats["applied_with_ambig_clause"] += 1
                _apply_row(cur, cid, parsed, today, stats)
            if parsed["ambiguous"]:
                stats["ambiguous"] += 1
                ambiguous_rows.append({
                    "center_id": cid,
                    "last_name": last or "",
                    "first_name": first or "",
                    "raw_hha": hha,
                    "reason": parsed["ambiguous_reason"] or "",
                    "attempted_parse": parsed["attempted_parse"],
                })
            if not args.quiet:
                tag = ("APPLIED" if parsed["applied"] else
                       "AMBIG" if parsed["ambiguous"] else
                       "SKIPPED")
                print(f"  {tag:8s} {cid}  {hha[:60]!r}")

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        # CSV + summary are added in Tasks 12 and 13.
        print(f"Mode: {mode}")
        print(f"Stats so far: {stats}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
