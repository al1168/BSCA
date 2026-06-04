"""Audit Contacts.[SADC] variants.

Read-only script. Connects to the Access .accdb, reads every
`Contacts.[SADC]` value, groups by distinct string, counts members,
runs each variant through the current
`monthly_schedule.auth_days.get_authorized_weekdays` parser, and
emits the results both to stdout and a dated CSV.

The CSV ships with an empty `expected_output` column. The operator
fills it in by hand for any row where the current parser disagrees
with what they want; that completed CSV becomes the spec input for
the future parser-change plan.

See docs/superpowers/plans/ for the broader context.
"""
import argparse
import csv
import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monthly_schedule.auth_days import (  # noqa: E402
    format_auth_days,
    get_authorized_weekdays,
)


_SADC_QUERY = "SELECT [SADC] FROM [Contacts]"


_CSV_COLUMNS = [
    "sadc_value", "member_count",
    "current_parser_output", "expected_output",
]


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _is_blank(value):
    if value is None:
        return True
    return not str(value).strip()


def _aggregate(rows):
    """Group raw SADC rows by distinct value. Returns
    `(aggregated, empty_count)` where `aggregated` is a list of dicts
    sorted by `member_count` desc then `sadc_value` asc, and
    `empty_count` is the number of rows whose SADC was NULL or
    whitespace-only (those don't appear in `aggregated`)."""
    counts = {}
    empty_count = 0
    for (raw,) in rows:
        if _is_blank(raw):
            empty_count += 1
            continue
        counts[raw] = counts.get(raw, 0) + 1
    aggregated = [
        {
            "sadc_value": value,
            "member_count": n,
            "current_parser_output": format_auth_days(
                get_authorized_weekdays(value)
            ),
        }
        for value, n in counts.items()
    ]
    aggregated.sort(key=lambda r: (-r["member_count"], r["sadc_value"]))
    return aggregated, empty_count


def _write_audit_csv(aggregated, out_dir, today):
    """Write the audit CSV to
    `<out_dir>/sadc_audit_<YYYY-MM-DD>.csv`. Returns the path
    written. Header is always written; each aggregated row gets an
    empty `expected_output` cell for the operator to fill in."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir,
        f"sadc_audit_{today.isoformat()}.csv",
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        for row in aggregated:
            w.writerow({
                "sadc_value": row["sadc_value"],
                "member_count": row["member_count"],
                "current_parser_output": row["current_parser_output"],
                "expected_output": "",
            })
    return path


def _print_stdout_table(aggregated, empty_count, csv_path):
    """Render the aggregated variants to stdout, highest count first."""
    print("SADC variant audit")
    if not aggregated:
        print("  (no non-empty SADC values found)")
    else:
        max_value_len = max(
            len(r["sadc_value"]) for r in aggregated
        )
        max_parser_len = max(
            (len(r["current_parser_output"]) for r in aggregated),
            default=0,
        )
        max_parser_len = max(max_parser_len, len("current_parser"))
        header = (
            f"  {'count':>5}  "
            f"{'current_parser':<{max_parser_len}}  "
            "sadc_value"
        )
        print(header)
        print(
            f"  {'-' * 5}  "
            f"{'-' * max_parser_len}  "
            f"{'-' * min(max_value_len, 40)}"
        )
        for r in aggregated:
            print(
                f"  {r['member_count']:>5}  "
                f"{r['current_parser_output']:<{max_parser_len}}  "
                f"{r['sadc_value']}"
            )
    total_members_with_sadc = sum(r["member_count"] for r in aggregated)
    print(f"  Total distinct SADC values: {len(aggregated)}")
    print(
        f"  Total Contacts with non-empty SADC: "
        f"{total_members_with_sadc}"
    )
    print(f"  Total Contacts with empty SADC: {empty_count}")
    print(f"  CSV: {csv_path}")


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Audit Contacts.[SADC] variants. Read-only — writes a "
            "dated CSV the operator fills in by hand."
        )
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--csv-out", default=".",
                   help="Directory for the audit CSV. Default: cwd.")
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
        cur.execute(_SADC_QUERY)
        rows = cur.fetchall()
    finally:
        conn.close()
    aggregated, empty_count = _aggregate(rows)
    today = datetime.date.today()
    csv_path = _write_audit_csv(aggregated, args.csv_out, today)
    _print_stdout_table(aggregated, empty_count, csv_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
