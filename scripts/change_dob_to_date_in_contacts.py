"""Change the Contacts.[DOB] column from short text (VARCHAR) to a
proper DATETIME column.

Idempotent:
  - If [DOB] is already DATETIME, the script prints "already
    converted" and exits 0.
  - If [DOB] is VARCHAR, the script:
      1. Pre-scans every row's DOB text. Any value that doesn't parse
         as a strict M/D/YYYY with year in [1900, current_year] is
         appended to an "unparseable" CSV so the operator can spot
         and fix the source data later.
      2. Executes `ALTER TABLE [Contacts] ALTER COLUMN [DOB] DATETIME`.
         Access handles the per-row text→datetime conversion
         internally. The pre-scan exists purely to surface suspect
         values (3-digit years, typos) — Access may silently coerce
         "11/24/195" into year 195 or 1995 in unpredictable ways;
         flagging them up front lets the operator decide.

Safe to run repeatedly. The pre-scan never mutates data; the ALTER
runs only when the column is still VARCHAR.

Use `--dry-run` to perform the pre-scan + write the CSV without
running the ALTER.
"""
import argparse
import csv
import datetime
import os
import sys


_CONTACTS_QUERY = (
    "SELECT [Center ID], [DOB] FROM [Contacts] ORDER BY [Center ID]"
)

_ALTER_DOB_TO_DATETIME = (
    "ALTER TABLE [Contacts] ALTER COLUMN [DOB] DATETIME"
)

_CSV_COLUMNS = ["center_id", "raw_dob", "reason"]


# Plausible year bounds for a date of birth. The lower bound is
# generous (no member from before 1900 is realistic). The upper
# bound is "this year" — we don't expect DOBs in the future.
_MIN_DOB_YEAR = 1900


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _parse_dob(text, max_year):
    """Return (parsed_date, reason_if_unparseable). On success
    returns (datetime.date, ""). On failure returns (None, "<reason>")
    where reason is one of:
      - "null"        — text is None
      - "empty"       — text is whitespace only
      - "bad_format"  — strptime("%m/%d/%Y") failed
      - "year_low"    — year < _MIN_DOB_YEAR
      - "year_high"   — year > max_year
    """
    if text is None:
        return None, "null"
    s = str(text).strip()
    if not s:
        return None, "empty"
    try:
        parsed = datetime.datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        return None, "bad_format"
    if parsed.year < _MIN_DOB_YEAR:
        return None, "year_low"
    if parsed.year > max_year:
        return None, "year_high"
    return parsed, ""


def _dob_column_type(cursor):
    """Return the ODBC type_name of Contacts.[DOB], or None if the
    column isn't present. Match is case-insensitive on the column
    name because Access identifiers are case-insensitive."""
    try:
        rows = cursor.columns(table="Contacts").fetchall()
    except Exception:
        return None
    for r in rows:
        if r.column_name.lower() == "dob":
            return r.type_name
    return None


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Change Contacts.[DOB] from short text to DATETIME. "
            "Idempotent: if [DOB] is already DATETIME, prints "
            "'already converted' and exits 0."
        ),
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--csv-out", default=".",
                   help=(
                       "Directory for the unparseable-DOB CSV. "
                       "Default: cwd."
                   ))
    p.add_argument("--dry-run", action="store_true",
                   help=(
                       "Pre-scan and write the CSV, but skip the "
                       "ALTER COLUMN. Useful to preview suspect rows."
                   ))
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-row stdout; print only the summary.")
    return p.parse_args(argv)


def _write_unparseable_csv(rows, out_dir, today):
    """Write the unparseable CSV to
    `<out_dir>/dob_conversion_unparseable_<YYYY-MM-DD>.csv`. Returns
    the path written. Writes the header even if `rows` is empty so
    the file's presence signals "a conversion ran on this date"."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir,
        f"dob_conversion_unparseable_{today.isoformat()}.csv",
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
        dob_type = _dob_column_type(cur)
        if dob_type is None:
            print(
                "ERROR: Contacts.[DOB] column not found.",
                file=sys.stderr,
            )
            return 2
        if dob_type.upper() in ("DATETIME", "TIMESTAMP"):
            print(
                f"Contacts.[DOB] is already {dob_type}; "
                "nothing to do."
            )
            return 0

        today = datetime.date.today()
        max_year = today.year

        stats = {
            "scanned": 0,
            "parseable": 0,
            "unparseable": 0,
        }
        unparseable_rows = []

        cur.execute(_CONTACTS_QUERY)
        rows = cur.fetchall()
        for row in rows:
            cid, raw = row
            stats["scanned"] += 1
            parsed, reason = _parse_dob(raw, max_year)
            if parsed is not None:
                stats["parseable"] += 1
                continue
            stats["unparseable"] += 1
            unparseable_rows.append({
                "center_id": "" if cid is None else int(cid),
                "raw_dob": "" if raw is None else str(raw),
                "reason": reason,
            })
            if not args.quiet:
                print(
                    f"  SUSPECT  cid={cid}  raw={raw!r}  "
                    f"reason={reason}"
                )

        csv_path = _write_unparseable_csv(
            unparseable_rows, args.csv_out, today,
        )

        if args.dry_run:
            mode = "DRY-RUN (no ALTER executed)"
        else:
            cur.execute(_ALTER_DOB_TO_DATETIME)
            conn.commit()
            mode = "APPLIED (column is now DATETIME)"

        print()
        print("DOB conversion summary")
        print(f"  Contacts scanned:        {stats['scanned']}")
        print(f"  DOBs that parse cleanly: {stats['parseable']}")
        print(f"  DOBs flagged as suspect: {stats['unparseable']}")
        print(f"  Unparseable CSV: {csv_path}")
        print(f"  Mode: {mode}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
