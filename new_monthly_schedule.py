"""CLI: generate monthly schedule workbooks from the four-table Access data model."""

import argparse
import csv
import os
import random
import sys
from collections import namedtuple
from datetime import date as _date

from monthly_schedule.db import (
    get_member, get_members_by_plan,
    get_enrollments, get_authorizations, get_absences, get_availability,
    get_one_offs,
)
from monthly_schedule.eligibility_context import MemberContext
from monthly_schedule.per_day import compute_month_failure, OneOffConflict
from monthly_schedule.rules import get_rules_for_plan
from monthly_schedule.rows import build_rows
from monthly_schedule.workbook import build_workbook
from monthly_schedule.travel import (
    load_cache,
    save_cache,
    resolve_travel_minutes,
    TravelError,
)

DEFAULT_DB = r"\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb"
DEFAULT_GEO_CACHE = "geo_cache.json"


def parse_center_ids(raw):
    """Parse a comma-separated Center ID string into an ordered list
    of unique ints. Whitespace is trimmed, blank entries dropped,
    duplicates removed preserving first-seen order."""
    result = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if value not in result:
            result.append(value)
    return result


def schedule_filename(center_id, year, month):
    """Workbook filename for a member/month."""
    return f"Schedule_{center_id}_{year:04d}-{month:02d}.xlsx"


def resolve_output_dir(base, plan_code, year, month):
    """Output directory for the run. Non-plan modes write directly in
    `base`; plan mode nests a `<CODE>_<YYYY-MM>` subdirectory (CODE
    upper-cased). `plan_code` is None for single/list modes."""
    if plan_code is None:
        return base
    sub = f"{plan_code.upper()}_{year:04d}-{month:02d}"
    return os.path.join(base, sub)


Failure = namedtuple("Failure", "center_id name stage reason day")

REASON_NOT_FOUND = "not found in database"


def format_summary(verb, success_count, total, scope, out_dir,
                   failures):
    """Build the end-of-run summary (spec section 5). Headline only on
    full success; an itemized `Failures:` block otherwise."""
    head = f"{verb} {success_count} of {total} member(s) for {scope}"
    if out_dir is not None:
        head += f" into {out_dir}"
    head += f"; {len(failures)} failed."
    if not failures:
        return head
    lines = [head, "Failures:"]
    for f in failures:
        name = f" ({f.name})" if f.name else ""
        lines.append(
            f"  - ID {f.center_id}{name}: {f.stage} — {f.reason}"
        )
    return "\n".join(lines)


def write_skipped_members_csv(failures, out_dir, today=None):
    """If `failures` is non-empty, write `skipped_members_<YYYY-MM-DD>.csv`
    into `out_dir` with one row per skipped member. Return the path
    written, or None when `failures` is empty (file not created).

    The `day` column is the ISO date from `failure.day` when set
    (currently only `one_off_conflict` failures), empty string otherwise."""
    if not failures:
        return None
    today = today or _date.today()
    path = os.path.join(out_dir, f"skipped_members_{today.isoformat()}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["center_id", "name", "stage", "reason", "day"])
        for f in failures:
            writer.writerow([
                f.center_id,
                f.name,
                f.stage,
                f.reason,
                f.day.isoformat() if f.day else "",
            ])
    return path


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Generate printable monthly schedule workbooks."
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--center-id", type=int)
    selector.add_argument("--center-ids")
    selector.add_argument("--plan")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--month", type=int, required=True,
        choices=range(1, 13), metavar="{1-12}",
    )
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--output-path", default=".")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--geo-cache", default=DEFAULT_GEO_CACHE)
    parser.add_argument("--preview-data", action="store_true")
    return parser.parse_args(argv)


def process_member(member, ctx, year, month, out_dir, preview,
                   api_key, cache):
    """Run the per-member pipeline. Returns (ok, stage, reason, day).
    On success ok is True and stage/reason/day are None. On failure
    stage is one of 'eligibility'/'geocode'/'route'/'one_off_conflict'/
    'generate'/'write' with the reason; day is set for one_off_conflict."""
    failure = compute_month_failure(year, month, ctx)
    if failure is not None:
        return (False, "eligibility", failure, None)

    try:
        travel_minutes = resolve_travel_minutes(member, api_key, cache)
    except TravelError as exc:
        return (False, exc.stage, exc.reason, None)

    rng = random.Random()
    try:
        rules = dict(get_rules_for_plan(member["health_plan"]))
        buf_lo, buf_hi = rules.get("travel_buffer_min", (5, 15))
        rules["pickup_lead_min"] = (travel_minutes + buf_lo,
                                    travel_minutes + buf_hi)
        rules["dropoff_trail_min"] = (travel_minutes + buf_lo,
                                      travel_minutes + buf_hi)
        rows = build_rows(year, month, ctx, rules, rng)
    except OneOffConflict as exc:
        return (False, "one_off_conflict", exc.reason, exc.day)
    except Exception as exc:  # reported in the run summary
        return (False, "generate", f"{type(exc).__name__} — {exc}", None)

    if preview:
        print(
            f"=== ID {member['center_id']} "
            f"({member['last_name']}, {member['first_name']}) ==="
        )
        for row in rows:
            print({**row, "date": str(row["date"])})
        return (True, None, None, None)

    path = os.path.join(
        out_dir, schedule_filename(member["center_id"], year, month)
    )
    try:
        build_workbook(member, rows, path)
    except Exception as exc:  # reported in the run summary
        return (False, "write", f"{type(exc).__name__} — {exc}", None)
    print(f"Wrote {path}")
    return (True, None, None, None)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    api_key = args.api_key
    cache = load_cache(args.geo_cache)

    if args.center_id is not None:
        plan_code = None
        id_list = [args.center_id]
    elif args.center_ids is not None:
        plan_code = None
        id_list = parse_center_ids(args.center_ids)
        if not id_list:
            print("No valid Center IDs provided", file=sys.stderr)
            return 2
    else:
        plan_code = args.plan
        id_list = None

    members = []
    failures = []
    try:
        if plan_code is not None:
            members = get_members_by_plan(plan_code, args.db_path)
        else:
            for cid in id_list:
                member = get_member(cid, args.db_path)
                if member is None:
                    failures.append(
                        Failure(cid, "", "lookup", REASON_NOT_FOUND, None)
                    )
                else:
                    members.append(member)
    except (FileNotFoundError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1

    period = f"{args.year:04d}-{args.month:02d}"
    if plan_code is not None:
        scope = f"plan {plan_code.upper()} {period}"
        if not members:
            print(
                f"No members found for plan {plan_code.upper()}",
                file=sys.stderr,
            )
            return 2
    else:
        scope = period

    out_dir = resolve_output_dir(
        args.output_path, plan_code, args.year, args.month
    )
    if not args.preview_data:
        os.makedirs(out_dir, exist_ok=True)

    success = 0
    for member in members:
        ctx = MemberContext(
            enrollments=get_enrollments(member["center_id"], args.db_path),
            authorizations=get_authorizations(member["center_id"], args.db_path),
            absences=get_absences(member["center_id"], args.db_path),
            availabilities=get_availability(member["center_id"], args.db_path),
            one_offs=get_one_offs(member["center_id"], args.db_path),
        )
        ok, stage, reason, day = process_member(
            member, ctx, args.year, args.month, out_dir,
            args.preview_data, api_key, cache,
        )
        if ok:
            success += 1
        else:
            failures.append(
                Failure(
                    member["center_id"],
                    f"{member['last_name']}, {member['first_name']}",
                    stage, reason, day,
                )
            )

    save_cache(args.geo_cache, cache)
    if not args.preview_data:
        skipped_csv = write_skipped_members_csv(failures, out_dir)
        if skipped_csv is not None:
            print(f"Wrote skipped members report: {skipped_csv}", file=sys.stderr)
    total = success + len(failures)
    verb = "Previewed" if args.preview_data else "Wrote"
    summary_dir = None if args.preview_data else out_dir
    print(
        format_summary(verb, success, total, scope, summary_dir,
                       failures),
        file=sys.stderr,
    )
    # total == 0 is defensive: empty --center-ids and empty --plan
    # already return 2 earlier; this guards any future zero path.
    if failures or total == 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
