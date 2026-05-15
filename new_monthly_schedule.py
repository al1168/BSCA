"""CLI: generate a monthly schedule workbook for one SADC member."""

import argparse
import os
import random
import sys
from collections import namedtuple

from monthly_schedule.db import get_member
from monthly_schedule.auth_days import get_authorized_weekdays
from monthly_schedule.rules import get_rules_for_plan
from monthly_schedule.rows import build_rows
from monthly_schedule.workbook import build_workbook

DEFAULT_DB = r"\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb"


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
        description="Generate a printable monthly schedule workbook."
    )
    parser.add_argument("--center-id", type=int, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--month", type=int, required=True,
        choices=range(1, 13), metavar="{1-12}",
    )
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--preview-data", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        member = get_member(args.center_id, args.db_path)
    except (FileNotFoundError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    if member is None:
        print(
            f"No member found with Center ID {args.center_id}",
            file=sys.stderr,
        )
        return 2

    authorized = get_authorized_weekdays(member["auth_days"])
    if not authorized:
        print(
            f"Warning: no authorized weekdays parsed from SADC "
            f"{member['auth_days']!r}; all time cells will be blank.",
            file=sys.stderr,
        )

    rules = get_rules_for_plan(member["health_plan"])
    rng = random.Random()
    rows = build_rows(args.year, args.month, authorized, rules, rng)

    if args.preview_data:
        for row in rows:
            print({**row, "date": str(row["date"])})
        return 0

    output_path = args.output_path or (
        f"./Schedule_{args.center_id}_"
        f"{args.year:04d}-{args.month:02d}.xlsx"
    )
    build_workbook(member, rows, output_path)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
