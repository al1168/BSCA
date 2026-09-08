"""Audit which members would (not) get a timesheet for a given month.

Read-only script. Connects to the Access .accdb, replays the exact
month-level eligibility gate the generator uses
(`monthly_schedule.per_day.compute_month_failure`) for every Contacts
member, and emits one CSV row per member: the gate verdict, how many
days of the month their Enrollment rows cover, the rows themselves,
and a `stale_open_row` flag for the data pattern that defeats the
gate — an old open (NULL end-date) enrollment lingering next to the
member's real, later enrollment. The BSCA-Members app judges
termination by the LATEST row only, while the scheduler treats ANY
overlapping row as enrolled, so those stale rows are what to clean up
when a "not enrolled" member still receives a sheet.

Usage:
    python scripts/audit_enrollment_gate.py --db path\\to.accdb \
        --year 2026 --month 9 [--csv-out DIR]
"""
import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monthly_schedule.db import (  # noqa: E402
    get_all_absences,
    get_all_authorizations,
    get_all_availability,
    get_all_enrollments,
    get_all_members,
    get_all_one_offs,
    get_holidays,
    get_operating_days,
)
from monthly_schedule.center_calendar import CenterCalendar  # noqa: E402
from monthly_schedule.eligibility_context import MemberContext  # noqa: E402
from monthly_schedule.month_dates import get_month_dates  # noqa: E402
from monthly_schedule.per_day import compute_month_failure  # noqa: E402


_CSV_COLUMNS = [
    "center_id", "name", "plan", "month_failure",
    "enrolled_days_in_month", "enrollment_rows", "open_rows",
    "stale_open_row", "auth_overlap",
]


def format_enrollment_rows(rows):
    """Render enrollment rows compactly: `start..end|start..open`."""
    parts = []
    for row in rows:
        end = row["end_date"]
        parts.append(
            f"{row['start_date'].isoformat()}.."
            f"{end.isoformat() if end is not None else 'open'}"
        )
    return "|".join(parts)


def has_stale_open_row(rows):
    """True when an open (NULL end-date) row starts before the latest
    row's start — the leftover that makes a terminated/re-enrolled
    member look enrolled forever to the scheduler."""
    if len(rows) < 2:
        return False
    latest_start = max(row["start_date"] for row in rows)
    return any(
        row["end_date"] is None and row["start_date"] < latest_start
        for row in rows
    )


def count_enrolled_days(rows, year, month):
    """Number of days in the month covered by any enrollment row."""
    count = 0
    for day in get_month_dates(year, month):
        for row in rows:
            end = row["end_date"]
            if row["start_date"] <= day and (end is None or day <= end):
                count += 1
                break
    return count


def auth_overlaps_month(auths, year, month):
    """True when any authorization's effective window touches the month."""
    days = get_month_dates(year, month)
    first, last = days[0], days[-1]
    return any(
        row["effective_start"] <= last and row["effective_end"] >= first
        for row in auths
    )


def audit_member(member, enrollments, auths, absences, availabilities,
                 one_offs, year, month, calendar=None):
    """Build one audit-CSV row dict for a member.

    `calendar` is the center's CenterCalendar (holidays, closed
    weekdays, per-weekday hours); None means always open."""
    ctx = MemberContext(enrollments, auths, absences, availabilities,
                        one_offs)
    failure = compute_month_failure(year, month, ctx, calendar=calendar)
    return {
        "center_id": member["center_id"],
        "name": f"{member['last_name']}, {member['first_name']}",
        "plan": member.get("health_plan") or "",
        "month_failure": failure or "",
        "enrolled_days_in_month": count_enrolled_days(
            enrollments, year, month
        ),
        "enrollment_rows": format_enrollment_rows(enrollments),
        "open_rows": sum(
            1 for row in enrollments if row["end_date"] is None
        ),
        "stale_open_row": has_stale_open_row(enrollments),
        "auth_overlap": auth_overlaps_month(auths, year, month),
    }


def _write_csv(rows, out_dir, year, month):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir, f"enrollment_gate_audit_{year:04d}-{month:02d}.csv"
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return path


def _print_summary(rows, csv_path):
    by_reason = {}
    for row in rows:
        key = row["month_failure"] or "(sheet generated)"
        by_reason[key] = by_reason.get(key, 0) + 1
    print("Enrollment-gate audit")
    for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>5}  {reason}")
    stale = [r for r in rows if r["stale_open_row"]]
    print(f"  Members with a stale open enrollment row: {len(stale)}")
    for row in stale:
        print(
            f"    {row['center_id']}  {row['name']}  "
            f"[{row['enrollment_rows']}]"
        )
    print(f"  CSV: {csv_path}")


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Replay the month-level eligibility gate for every member "
            "and report why each would or would not get a timesheet. "
            "Read-only."
        )
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--month", type=int, required=True,
                   help="1..12 — the schedule month to audit.")
    p.add_argument("--csv-out", default=".",
                   help="Directory for the audit CSV. Default: cwd.")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if not os.path.exists(args.db):
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)
        return 2
    try:
        get_month_dates(args.year, args.month)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        members = get_all_members(args.db)
        enroll_idx = get_all_enrollments(args.db)
        auth_idx = get_all_authorizations(args.db)
        absence_idx = get_all_absences(args.db)
        avail_idx = get_all_availability(args.db)
        one_off_idx = get_all_one_offs(args.db)
        center_calendar = CenterCalendar(
            get_holidays(args.db), get_operating_days(args.db)
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    rows = [
        audit_member(
            member,
            enroll_idx.get(member["center_id"], []),
            auth_idx.get(member["center_id"], []),
            absence_idx.get(member["center_id"], []),
            avail_idx.get(member["center_id"], []),
            one_off_idx.get(member["center_id"], []),
            args.year, args.month, calendar=center_calendar,
        )
        for member in members
    ]
    csv_path = _write_csv(rows, args.csv_out, args.year, args.month)
    _print_summary(rows, csv_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
