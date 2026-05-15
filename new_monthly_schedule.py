"""CLI: generate a monthly schedule workbook for one SADC member."""

import argparse
import random
import sys

from monthly_schedule.db import get_member
from monthly_schedule.auth_days import get_authorized_weekdays
from monthly_schedule.rules import get_rules_for_plan
from monthly_schedule.rows import build_rows
from monthly_schedule.workbook import build_workbook

DEFAULT_DB = r"\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb"


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
    args = parse_args(sys.argvp[1:] if argv is None else argv)

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
