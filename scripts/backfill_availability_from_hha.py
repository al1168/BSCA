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

# Used by the post-HHA default-fill pass: for every member × every
# weekday with no open Availability row, INSERT one of these.
_DEFAULT_AVAIL_START = "08:00"
_DEFAULT_AVAIL_END = "16:00"

_ALL_MEMBER_IDS_QUERY = (
    "SELECT DISTINCT [Center ID] FROM [Contacts] "
    "WHERE [Center ID] IS NOT NULL"
)


def _is_test_id(center_id):
    """True if the Center ID, rendered as a base-10 integer, ends in '00'.
    Used by the --exclude-test-members flag to filter scratch members."""
    return str(int(center_id)).endswith("00")


def _hhmm_to_time(hhmm):
    """Convert 'HH:MM' to a datetime.time. Access stores time-only
    DATETIME fields with a 1899-12-30 placeholder; pyodbc accepts
    datetime.time for that column."""
    h, m = hhmm.split(":")
    return datetime.time(int(h), int(m))


def _apply_clause_to_db(cur, center_id, day, avail_end_hhmm, today,
                        stats):
    """One upsert into Availability: find the currently-open row for
(Center ID, Day Of Week) and UPDATE its avail_end if the new value
is strictly earlier (per-spec "only shorten" invariant), or INSERT
a new row if none exists. Stats counters bookkeep updates vs. inserts.
"""
    new_end_time = _hhmm_to_time(avail_end_hhmm)
    cur.execute(_AVAIL_OPEN_QUERY, str(center_id), day)
    existing = cur.fetchone()
    if existing is not None:
        existing_id, existing_end = existing
        # existing_end is a datetime; compare on time of day.
        existing_end_time = existing_end.time() if hasattr(
            existing_end, "time") else existing_end
        # Only shorten: per spec the avail_end is monotonically pulled earlier as HHA constraints accumulate, never widened.
        if new_end_time < existing_end_time:
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


def _seed_default_availability(cur, today, exclude_test, stats):
    """Insert a default 8:00-16:00 Availability row for every
    (member, weekday) pair that has no open row yet.

    Only Monday through Friday — the center does not operate on
    weekends, so seeding Sat/Sun rows is noise. Runs AFTER the HHA
    pass so any weekday HHA narrowed to an earlier end-time keeps
    that narrower row (the OPEN-row check sees it and skips).
    Unmentioned weekdays get the default. The scheduler still gates
    per-day by Authorization.auth_days, so a default row on a
    non-authorized weekday is inert.
    """
    cur.execute(_ALL_MEMBER_IDS_QUERY)
    member_ids = [
        int(row[0]) for row in cur.fetchall() if row[0] is not None
    ]
    start_t = _hhmm_to_time(_DEFAULT_AVAIL_START)
    end_t = _hhmm_to_time(_DEFAULT_AVAIL_END)
    for cid in member_ids:
        if exclude_test and _is_test_id(cid):
            continue
        for day in range(1, 6):  # ISO weekday: 1=Mon ... 5=Fri
            cur.execute(_AVAIL_OPEN_QUERY, str(cid), day)
            if cur.fetchone() is not None:
                continue
            cur.execute(
                _AVAIL_INSERT,
                str(cid), today, day, start_t, end_t,
            )
            stats["default_inserted"] += 1


_CSV_COLUMNS = [
    "center_id", "last_name", "first_name",
    "raw_hha", "reason", "attempted_parse",
]


def _write_ambiguous_csv(rows, out_dir, today):
    """Write the ambiguous-rows CSV to
    `<out_dir>/hha_backfill_ambiguous_<YYYY-MM-DD>.csv`. Returns the
    path written. Writes the header even if `rows` is empty so the
    file's presence still signals 'a backfill ran on this date'.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir,
        f"hha_backfill_ambiguous_{today.isoformat()}.csv",
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


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
    p.add_argument("--exclude-test-members", action="store_true",
                   help="Skip members whose Center ID ends in '00'.")
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
            "test_skipped": 0,
            "ignored": 0,
            "skipped_row": 0,
            "applied": 0,
            "applied_with_ambig_clause": 0,
            "ambiguous": 0,
            "updated": 0,
            "inserted": 0,
            "clauses_after_close": 0,
            "multi_clause_same_day": 0,
            "default_inserted": 0,
        }
        ambiguous_rows = []

        for cid, last, first, hha in _read_contacts(conn):
            stats["scanned"] += 1

            if args.exclude_test_members and _is_test_id(cid):
                stats["test_skipped"] += 1
                if not args.quiet:
                    print(f"  TEST-SKIP {cid}  (Center ID ends in 00)")
                continue

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

        # After HHA: seed default 8:00-16:00 for any (member, weekday)
        # the HHA pass didn't already cover. This runs before commit
        # so --dry-run rolls these inserts back too.
        _seed_default_availability(
            cur, today, args.exclude_test_members, stats,
        )

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        csv_path = _write_ambiguous_csv(
            ambiguous_rows, args.csv_out, today,
        )
        stats["csv_path"] = csv_path

        non_empty = stats["scanned"]
        print()
        print("HHA backfill summary")
        print(f"  Contacts scanned (with non-empty HHA): {non_empty}")
        print(
            f"  Test members excluded (--exclude-test-members): "
            f"{stats['test_skipped']}"
        )
        print(f"  Rows ignored (no time):                {stats['ignored']}")
        print(f"  Rows skipped (HHA fully after close):  {stats['skipped_row']}")
        print(
            f"  Rows applied:                          {stats['applied']}"
            f"    (of which {stats['applied_with_ambig_clause']} had "
            "at least one ambiguous clause)"
        )
        print(f"  Rows fully or partially ambiguous:     {stats['ambiguous']}")
        print(f"  Availability rows updated:             {stats['updated']}")
        print(f"  Availability rows inserted:            {stats['inserted']}")
        print(
            f"  Default 8-4 rows inserted (post-HHA):  "
            f"{stats['default_inserted']}"
        )
        print(
            f"  Clauses skipped (HHA_start >= 16:00):  "
            f"{stats['clauses_after_close']}"
        )
        print(
            f"  Multi-clause same-day collisions:      "
            f"{stats['multi_clause_same_day']}"
        )
        print(f"  Ambiguous CSV: {stats['csv_path']}")
        print(f"  Mode: {mode}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
