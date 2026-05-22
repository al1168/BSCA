"""CLI: generate a monthly schedule workbook for one SADC member."""

import argparse
import os
import random
import sys
from collections import namedtuple

from monthly_schedule.db import get_member, get_members_by_plan
from monthly_schedule.auth_days import get_authorized_weekdays
from monthly_schedule.rules import get_rules_for_plan
from monthly_schedule.rows import build_rows
from monthly_schedule.workbook import build_workbook
from monthly_schedule.travel import (
    load_api_key,
    load_cache,
    save_cache,
    resolve_travel_minutes,
    TravelError,
)

DEFAULT_DB = r"\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb"
DEFAULT_GOOGLE_CONFIG = "google_maps.config"
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


Failure = namedtuple("Failure", "center_id name stage reason")


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
    parser.add_argument("--google-config", default=DEFAULT_GOOGLE_CONFIG)
    parser.add_argument("--geo-cache", default=DEFAULT_GEO_CACHE)
    parser.add_argument("--preview-data", action="store_true")
    return parser.parse_args(argv)


def process_member(member, year, month, out_dir, preview,
                   api_key, cache):
    """Run the per-member pipeline. Returns (ok, stage, reason).
    On success ok is True and stage/reason are None. On failure
    stage is 'geocode'/'route'/'generate'/'write' with the reason."""
    try:
        travel_minutes = resolve_travel_minutes(member, api_key, cache)
    except TravelError as exc:
        return (False, exc.stage, exc.reason)
    rng = random.Random()
    try:
        authorized = get_authorized_weekdays(member["auth_days"])
        if not authorized:
            print(
                f"Warning: no authorized weekdays parsed from SADC "
                f"{member['auth_days']!r} for ID {member['center_id']}; "
                f"all time cells will be blank.",
                file=sys.stderr,
            )
        rules = dict(get_rules_for_plan(member["health_plan"]))
        buf_lo, buf_hi = rules.get("travel_buffer_min", (5, 15))
        rules["pickup_lead_min"] = (travel_minutes + buf_lo, travel_minutes + buf_hi)
        rules["dropoff_trail_min"] = (travel_minutes + buf_lo, travel_minutes + buf_hi)
        rows = build_rows(year, month, authorized, rules, rng)
    except Exception as exc:  # reported in the run summary
        return (False, "generate", f"{type(exc).__name__} — {exc}")

    if preview:
        print(
            f"=== ID {member['center_id']} "
            f"({member['last_name']}, {member['first_name']}) ==="
        )
        for row in rows:
            print({**row, "date": str(row["date"])})
        return (True, None, None)

    path = os.path.join(
        out_dir, schedule_filename(member["center_id"], year, month)
    )
    try:
        build_workbook(member, rows, path)
    except Exception as exc:  # reported in the run summary
        return (False, "write", f"{type(exc).__name__} — {exc}")
    print(f"Wrote {path}")
    return (True, None, None)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        api_key = load_api_key(args.google_config)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
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
                        Failure(cid, "", "lookup",
                                "not found in database")
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
        ok, stage, reason = process_member(
            member, args.year, args.month, out_dir,
            args.preview_data, api_key, cache,
        )
        if ok:
            success += 1
        else:
            failures.append(
                Failure(
                    member["center_id"],
                    f"{member['last_name']}, {member['first_name']}",
                    stage, reason,
                )
            )

    save_cache(args.geo_cache, cache)
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
