"""Apply reviewed HHA answers to the Availability table.

Reads the human-reviewed answers CSV (the `hhbackfill` file), parses
each non-empty `answer`, and narrows the currently-open Availability
window per (member, day) so availability never overlaps home-care
hours. Splits, fully-blocked days, parse errors and unknown members
go to a dated review CSV; all DB writes happen in one transaction.

See docs/superpowers/specs/2026-07-17-apply-hha-answers-design.md
"""
import argparse
import csv
import datetime
import os
import sys
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monthly_schedule.hha_answer_parser import (  # noqa: E402
    AnswerParseError,
    hhmm,
    parse_answer,
    subtract_care_window,
)

# The post-setup seeded default window; used when a (member, day) named
# in an answer has no open Availability row (spec §4).
_DEFAULT_WINDOW = (8 * 60, 13 * 60)

_AVAIL_OPEN_QUERY = (
    "SELECT [ID], [avail_start], [avail_end] FROM [Availability] "
    "WHERE [Center ID] = ? AND [Day Of Week] = ? "
    "AND [effective_end_date] IS NULL"
)
_AVAIL_UPDATE = (
    "UPDATE [Availability] SET [avail_start] = ?, [avail_end] = ? "
    "WHERE [ID] = ?"
)
_AVAIL_INSERT = (
    "INSERT INTO [Availability] "
    "([Center ID], [effective_start_date], [effective_end_date], "
    "[Day Of Week], [avail_start], [avail_end]) "
    "VALUES (?, ?, NULL, ?, ?, ?)"
)
_CONTACT_EXISTS_QUERY = (
    "SELECT [Center ID] FROM [Contacts] WHERE [Center ID] = ?"
)

_REVIEW_COLUMNS = [
    "center_id", "last_name", "first_name", "day", "flag",
    "hha_window", "old_window", "new_window", "note",
]


def _minutes_to_time(minutes):
    return datetime.time(minutes // 60, minutes % 60)


def _time_to_minutes(value):
    """Access stores time-of-day as DATETIME with a 1899-12-30 date
    part; pyodbc returns datetime.datetime. Accept datetime.time too."""
    t = value.time() if hasattr(value, "time") else value
    return t.hour * 60 + t.minute


def _window_str(window):
    return f"{hhmm(window[0])}-{hhmm(window[1])}"


def _read_answer_rows(csv_path):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = {"center_id", "answer"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"answers CSV missing columns: {sorted(missing)}")
        return list(reader)


def _member_exists(cur, center_id):
    cur.execute(_CONTACT_EXISTS_QUERY, int(center_id))
    return cur.fetchone() is not None


def _fetch_open_window(cur, center_id, day):
    """Return (row_id, (start_min, end_min)) for the open Availability
    row, or None if the member has no open row for that weekday."""
    cur.execute(_AVAIL_OPEN_QUERY, str(center_id), day)
    row = cur.fetchone()
    if row is None:
        return None
    row_id, start, end = row
    return int(row_id), (_time_to_minutes(start), _time_to_minutes(end))


def _write_review_csv(rows, out_dir, today):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir, f"hha_answers_review_{today.isoformat()}.csv",
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_REVIEW_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Apply reviewed HHA answers to Availability.",
    )
    p.add_argument("--csv", required=True,
                   help="Path to the reviewed answers CSV.")
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--csv-out", default=None,
                   help="Directory for the review CSV. "
                        "Default: the answers CSV's directory.")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse + report, roll back all DB changes.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-day stdout; print only the summary.")
    return p.parse_args(argv)


def _apply_member_day(cur, cid, day, intervals, today, args, stats,
                      review_rows, names):
    """Subtract every care interval for one (member, day) from its open
    window and write the result. Appends review rows for split/blocked."""
    last, first = names
    found = _fetch_open_window(cur, cid, day)
    if found is None:
        row_id, window = None, _DEFAULT_WINDOW
    else:
        row_id, window = found
    original = window
    hha_desc = "; ".join(_window_str(iv) for iv in intervals)

    blocked = False
    dropped = None
    for care in intervals:
        result = subtract_care_window(window, care)
        if result["action"] == "blocked":
            blocked = True
            break
        if result["action"] == "split":
            dropped = result["dropped"]
        window = result["window"]

    if blocked:
        stats["blocked_days"] += 1
        review_rows.append({
            "center_id": cid, "last_name": last, "first_name": first,
            "day": day, "flag": "blocked", "hha_window": hha_desc,
            "old_window": _window_str(original), "new_window": "",
            "note": "care covers the whole window; not written",
        })
        return

    if window == original:
        stats["days_unchanged"] += 1
        return

    if dropped is not None:
        stats["split_days"] += 1
        review_rows.append({
            "center_id": cid, "last_name": last, "first_name": first,
            "day": day, "flag": "split", "hha_window": hha_desc,
            "old_window": _window_str(original),
            "new_window": _window_str(window),
            "note": f"kept longer piece; dropped {_window_str(dropped)}",
        })

    if row_id is None:
        cur.execute(
            _AVAIL_INSERT, str(cid), today, day,
            _minutes_to_time(window[0]), _minutes_to_time(window[1]),
        )
        stats["days_inserted"] += 1
    else:
        cur.execute(
            _AVAIL_UPDATE,
            _minutes_to_time(window[0]), _minutes_to_time(window[1]),
            row_id,
        )
        stats["days_updated"] += 1

    if not args.quiet:
        print(
            f"  {cid} day {day}: {_window_str(original)} -> "
            f"{_window_str(window)}  (HHA {hha_desc})"
        )


def main(argv=None):
    args = _parse_args(argv)
    if not os.path.exists(args.csv):
        print(f"ERROR: answers CSV not found: {args.csv}", file=sys.stderr)
        return 2
    if not os.path.exists(args.db):
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)
        return 2

    try:
        answer_rows = _read_answer_rows(args.csv)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
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
            "rows": 0, "blank": 0, "members_applied": 0,
            "parse_errors": 0, "members_not_found": 0,
            "days_updated": 0, "days_inserted": 0, "days_unchanged": 0,
            "split_days": 0, "blocked_days": 0,
        }
        review_rows = []

        for row in answer_rows:
            stats["rows"] += 1
            cid_raw = (row.get("center_id") or "").strip()
            answer = (row.get("answer") or "").strip()
            last = (row.get("last_name") or "").strip()
            first = (row.get("first_name") or "").strip()

            if not answer:
                stats["blank"] += 1
                continue

            try:
                groups = parse_answer(answer)
                cid = int(cid_raw)
            except (AnswerParseError, ValueError) as exc:
                stats["parse_errors"] += 1
                review_rows.append({
                    "center_id": cid_raw, "last_name": last,
                    "first_name": first, "day": "",
                    "flag": "parse_error", "hha_window": "",
                    "old_window": "", "new_window": "",
                    "note": str(exc),
                })
                continue

            if not _member_exists(cur, cid):
                stats["members_not_found"] += 1
                review_rows.append({
                    "center_id": cid, "last_name": last,
                    "first_name": first, "day": "",
                    "flag": "member_not_found", "hha_window": "",
                    "old_window": "", "new_window": "",
                    "note": "Center ID not in Contacts; nothing written",
                })
                continue

            stats["members_applied"] += 1
            day_intervals = {}
            for g in groups:
                for d in sorted(g["days"]):
                    day_intervals.setdefault(d, []).append(
                        (g["start"], g["end"]))
            for d, intervals in sorted(day_intervals.items()):
                _apply_member_day(
                    cur, cid, d, intervals, today, args, stats,
                    review_rows, (last, first),
                )

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        out_dir = args.csv_out or os.path.dirname(
            os.path.abspath(args.csv))
        csv_path = _write_review_csv(review_rows, out_dir, today)

        print()
        print("Apply HHA answers summary")
        print(f"  Rows read:                   {stats['rows']}")
        print(f"  Blank answers skipped: {stats['blank']}")
        print(f"  Members applied:             {stats['members_applied']}")
        print(f"  Parse errors:                {stats['parse_errors']}")
        print(f"  Members not found:           {stats['members_not_found']}")
        print(f"  Days updated: {stats['days_updated']}")
        print(f"  Days inserted:               {stats['days_inserted']}")
        print(f"  Days unchanged (no overlap): {stats['days_unchanged']}")
        print(f"  Split days (kept longer piece): {stats['split_days']}")
        print(f"  Blocked days (not written):  {stats['blocked_days']}")
        print(f"  Review CSV: {csv_path}")
        print(f"  Mode: {mode}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
