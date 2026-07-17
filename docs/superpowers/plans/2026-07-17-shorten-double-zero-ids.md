# Shorten Double-Zero Center IDs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A CLI script that renames every Center ID longer than 5 digits ending in `00` to its stripped form (`2213400` → `22134`) across all seven `[Center ID]` tables, skipping and reporting collisions.

**Architecture:** Single maintenance script `scripts/shorten_double_zero_ids.py` mirroring `scripts/terminate_long_id_enrollments.py` (argparse → scan → per-member decision loop → single commit → CSV + summary). Scans all seven tables into per-table ID sets up front; candidates are the qualifying IDs in the union of the sets (so orphaned child rows rename too); collision check is set membership. Tests use the FakeCursor/FakeConn pattern from `tests/test_terminate_long_id_enrollments.py` — no real Access connection.

**Tech Stack:** Python 3.11, pyodbc (Microsoft Access ODBC driver), pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-shorten-double-zero-ids-design.md`

---

## Task 1: Script scaffold — constants, pure helpers, argparse

**Files:**
- Create: `scripts/shorten_double_zero_ids.py`
- Create: `tests/test_shorten_double_zero_ids.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_shorten_double_zero_ids.py` with exactly:

```python
import datetime
import re
import sys
from pathlib import Path

import pytest

# Ensure the script is importable as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import shorten_double_zero_ids as sh


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_tables_list():
    """The seven [Center ID] tables, Contacts first."""
    assert sh._TABLES == [
        "Contacts",
        "Enrollment",
        "Authorization",
        "Absences",
        "Availability",
        "OneOffAvailability",
        "EmergencyContact",
    ]


def test_csv_columns():
    assert sh._CSV_COLUMNS == ["old_id", "new_id", "reason"]


def test_scan_template_shape():
    q = sh._SCAN_TEMPLATE.format(table="Enrollment")
    assert q == "SELECT [Center ID] FROM [Enrollment]"


def test_rename_template_shape():
    q = sh._RENAME_TEMPLATE.format(table="Enrollment")
    assert "UPDATE [Enrollment]" in q
    assert "SET [Center ID] = ?" in q
    assert "WHERE [Center ID] = ?" in q
    assert q.count("?") == 2


# ---------------------------------------------------------------------------
# _build_connection_string
# ---------------------------------------------------------------------------

def test_build_connection_string():
    cs = sh._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


# ---------------------------------------------------------------------------
# _qualifies / _new_id
# ---------------------------------------------------------------------------

def test_qualifies_true_cases():
    assert sh._qualifies(2213400) is True       # 7 digits, ends 00
    assert sh._qualifies(2213400.0) is True     # DOUBLE form
    assert sh._qualifies(100000) is True        # 6 digits, ends 00
    assert sh._qualifies(99999900) is True      # 8 digits, ends 00


def test_qualifies_false_cases():
    assert sh._qualifies(24010) is False        # 5 digits
    assert sh._qualifies(99900) is False        # 5 digits, ends 00
    assert sh._qualifies(2400601) is False      # long, doesn't end 00
    assert sh._qualifies(2400601.0) is False    # DOUBLE form
    assert sh._qualifies(None) is False         # NULL Center ID


def test_new_id():
    assert sh._new_id(2213400) == 22134
    assert sh._new_id(2213400.0) == 22134       # DOUBLE form
    assert sh._new_id(123400) == 1234           # result < 5 digits is fine
    assert sh._new_id(221340000) == 2213400     # caller must skip: still >5


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------

def test_parse_args_requires_db():
    with pytest.raises(SystemExit):
        sh._parse_args([])


def test_parse_args_defaults():
    args = sh._parse_args(["--db", "C:/x.accdb"])
    assert args.db == "C:/x.accdb"
    assert args.csv_out == "."
    assert args.dry_run is False
    assert args.quiet is False


def test_parse_args_all_flags():
    args = sh._parse_args([
        "--db", "C:/x.accdb",
        "--csv-out", "/tmp/out",
        "--dry-run",
        "--quiet",
    ])
    assert args.csv_out == "/tmp/out"
    assert args.dry_run is True
    assert args.quiet is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_shorten_double_zero_ids.py -v`
Expected: FAIL at import time — `ModuleNotFoundError: No module named 'scripts.shorten_double_zero_ids'` (collection error).

- [ ] **Step 3: Write the minimal implementation**

Create `scripts/shorten_double_zero_ids.py` with exactly:

```python
"""Shorten double-zero Center IDs across every [Center ID] table.

Center IDs longer than 5 digits that end in '00' are renamed with one
trailing '00' stripped (2213400 -> 22134) in all seven tables that
carry [Center ID]: Contacts, Enrollment, Authorization, Absences,
Availability, OneOffAvailability, EmergencyContact.

Members whose shortened ID already exists anywhere are skipped
entirely and reported to a CSV — no partial rename, never auto-merged.
end_date values (including the 2000-01-01 terminations set by
terminate_long_id_enrollments.py) are never touched.

Safe to run repeatedly: a fully renamed member no longer qualifies,
and skips are read-only.
"""
import argparse
import csv
import datetime
import os
import sys
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_TABLES = [
    "Contacts",
    "Enrollment",
    "Authorization",
    "Absences",
    "Availability",
    "OneOffAvailability",
    "EmergencyContact",
]

_SCAN_TEMPLATE = "SELECT [Center ID] FROM [{table}]"

_RENAME_TEMPLATE = (
    "UPDATE [{table}] SET [Center ID] = ? WHERE [Center ID] = ?"
)

_CSV_COLUMNS = ["old_id", "new_id", "reason"]


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _qualifies(center_id):
    """True if the Center ID, rendered as a base-10 integer string, is
    more than 5 characters long AND ends with '00'. Mirrors
    `_is_long_id` in terminate_long_id_enrollments.py for handling the
    DOUBLE-typed Center ID field without trailing '.0' confusion."""
    if center_id is None:
        return False
    s = str(int(center_id))
    return len(s) > 5 and s.endswith("00")


def _new_id(center_id):
    """The shortened ID: exactly one trailing '00' stripped. The
    caller is responsible for skipping results still >5 digits."""
    return int(center_id) // 100


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Rename Center IDs longer than 5 digits that end in '00' "
            "to their stripped form (2213400 -> 22134) across all "
            "[Center ID] tables. Collisions are skipped and reported."
        ),
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--csv-out", default=".",
                   help="Directory for the skipped CSV. Default: cwd.")
    p.add_argument("--dry-run", action="store_true",
                   help="Do everything, roll back instead of commit.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-member stdout; print only the summary.")
    return p.parse_args(argv)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_shorten_double_zero_ids.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/shorten_double_zero_ids.py tests/test_shorten_double_zero_ids.py
git commit -m "feat(scripts): scaffold shorten_double_zero_ids helpers"
```

---

## Task 2: Skipped-CSV writer

**Files:**
- Modify: `scripts/shorten_double_zero_ids.py` (append after `_parse_args`)
- Modify: `tests/test_shorten_double_zero_ids.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_shorten_double_zero_ids.py`:

```python
# ---------------------------------------------------------------------------
# _write_skipped_csv
# ---------------------------------------------------------------------------

def test_write_skipped_csv_empty_writes_header(tmp_path):
    """Even with no rows, the CSV is written with just the header —
    file presence signals 'a run happened on this date'."""
    today = datetime.date(2026, 7, 17)
    path = sh._write_skipped_csv([], str(tmp_path), today)
    assert path == str(tmp_path / "shorten_ids_skipped_2026-07-17.csv")
    body = Path(path).read_text(encoding="utf-8-sig")
    assert body.splitlines() == ["old_id,new_id,reason"]


def test_write_skipped_csv_rows(tmp_path):
    today = datetime.date(2026, 7, 17)
    rows = [
        {"old_id": 2213400, "new_id": 22134,
         "reason": "target ID already exists in: Contacts"},
        {"old_id": 221340000, "new_id": 2213400,
         "reason": "still longer than 5 digits after stripping 00"},
    ]
    path = sh._write_skipped_csv(rows, str(tmp_path), today)
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "old_id,new_id,reason"
    assert lines[1] == "2213400,22134,target ID already exists in: Contacts"
    assert lines[2].startswith("221340000,2213400,still longer")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_shorten_double_zero_ids.py -v -k write_skipped_csv`
Expected: FAIL with `AttributeError: ... has no attribute '_write_skipped_csv'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `scripts/shorten_double_zero_ids.py`:

```python
def _write_skipped_csv(rows, out_dir, today):
    """Write the skipped-members CSV to
    `<out_dir>/shorten_ids_skipped_<YYYY-MM-DD>.csv`. Returns the path
    written. Writes the header even if `rows` is empty so the file's
    presence signals 'a run happened on this date'."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir,
        f"shorten_ids_skipped_{today.isoformat()}.csv",
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_shorten_double_zero_ids.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/shorten_double_zero_ids.py tests/test_shorten_double_zero_ids.py
git commit -m "feat(scripts): skipped-CSV writer for shorten_double_zero_ids"
```

---

## Task 3: main() — scan, rename, skip, commit, summary

**Files:**
- Modify: `scripts/shorten_double_zero_ids.py` (append after `_write_skipped_csv`)
- Modify: `tests/test_shorten_double_zero_ids.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_shorten_double_zero_ids.py`:

```python
# ---------------------------------------------------------------------------
# FakeCursor / FakeConn (mirrors tests/test_terminate_long_id_enrollments.py)
# ---------------------------------------------------------------------------

class FakeCursor:
    """Records execute() calls; returns canned fetchall results. The
    `rowcount` attribute defaults to 1 (single affected row) so
    happy-path tests don't need to set it explicitly."""
    def __init__(self):
        self.executed = []        # list of (sql, params_tuple)
        self._fetchall_queue = []
        self.rowcount = 1

    def queue_fetchall(self, rows):
        self._fetchall_queue.append(rows)

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self

    def fetchall(self):
        return self._fetchall_queue.pop(0)


class FakeConn:
    def __init__(self, fake_cursor):
        self._cursor = fake_cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def _make_fake_conn(scan_by_table):
    """Build a FakeConn whose cursor answers the seven per-table scans
    in sh._TABLES order. `scan_by_table` maps table name -> list of
    Center ID values (missing tables scan as empty). Values are
    wrapped as 1-tuples, matching `SELECT [Center ID]` rows."""
    cur = FakeCursor()
    for table in sh._TABLES:
        rows = [(cid,) for cid in scan_by_table.get(table, [])]
        cur.queue_fetchall(rows)
    return FakeConn(cur), cur


def _updates(cur):
    """The recorded UPDATE executions as (table, params) pairs."""
    out = []
    for sql, params in cur.executed:
        if sql.startswith("UPDATE ["):
            table = sql.split("[")[1].split("]")[0]
            out.append((table, params))
    return out


def _run_main(tmp_path, monkeypatch, conn, extra_flags=("--quiet",)):
    """Patch pyodbc.connect, touch a fake .accdb, run main()."""
    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)
    db_path = tmp_path / "test.accdb"
    db_path.touch()
    return sh.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        *extra_flags,
    ])


def _skipped_csv_lines(tmp_path):
    csv_path = tmp_path / (
        f"shorten_ids_skipped_{datetime.date.today().isoformat()}.csv"
    )
    assert csv_path.exists()
    return csv_path.read_text(encoding="utf-8-sig").splitlines()


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_missing_db_returns_2(tmp_path, capsys):
    missing = tmp_path / "nope.accdb"
    rc = sh.main(["--db", str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "database not found" in err.lower()


def test_main_renames_across_all_tables(tmp_path, monkeypatch):
    """Happy path: one qualifying ID in several tables triggers ONE
    UPDATE per table (all seven, unconditionally) with params
    (new_id, old_id), and the run commits."""
    conn, cur = _make_fake_conn({
        "Contacts": [2213400],
        "Enrollment": [2213400],
        "Availability": [2213400],
    })
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0

    updates = _updates(cur)
    assert [t for t, _ in updates] == sh._TABLES
    for _, params in updates:
        assert params == (22134, 2213400)
    assert conn.committed is True

    # Nothing skipped: CSV is header-only.
    assert _skipped_csv_lines(tmp_path) == ["old_id,new_id,reason"]


def test_main_renames_orphaned_child_rows(tmp_path, monkeypatch):
    """A qualifying ID present only in a child table (no Contacts row)
    is still renamed — candidates come from the union of all tables."""
    conn, cur = _make_fake_conn({"Enrollment": [2213400]})
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0
    updates = _updates(cur)
    assert len(updates) == len(sh._TABLES)
    for _, params in updates:
        assert params == (22134, 2213400)


def test_main_skips_collision(tmp_path, monkeypatch):
    """If the shortened ID already exists anywhere, the member is
    fully skipped and the CSV names the colliding tables."""
    conn, cur = _make_fake_conn({
        "Contacts": [2213400, 22134],
        "Absences": [22134],
    })
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0
    assert _updates(cur) == []
    assert conn.committed is True

    lines = _skipped_csv_lines(tmp_path)
    assert len(lines) == 2
    # Exact-field prefix (avoids '2213400' matching '22134' substrings).
    assert lines[1].startswith("2213400,22134,")
    assert "target ID already exists in: Contacts, Absences" in lines[1]


def test_main_skips_still_too_long(tmp_path, monkeypatch):
    """221340000 strips to 2213400 — still 7 digits, so skip+report
    instead of a half-fix."""
    conn, cur = _make_fake_conn({"Contacts": [221340000]})
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0
    assert _updates(cur) == []

    lines = _skipped_csv_lines(tmp_path)
    assert len(lines) == 2
    assert lines[1].startswith("221340000,2213400,")
    assert "still longer than 5 digits" in lines[1]


def test_main_ignores_non_qualifying_ids(tmp_path, monkeypatch):
    """5-digit IDs, long IDs not ending 00, and NULLs never rename."""
    conn, cur = _make_fake_conn({
        "Contacts": [24010, 99900, 2400601, None],
        "Enrollment": [24010, 2400601],
    })
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0
    assert _updates(cur) == []
    assert _skipped_csv_lines(tmp_path) == ["old_id,new_id,reason"]


def test_dry_run_calls_rollback_not_commit(tmp_path, monkeypatch):
    conn, cur = _make_fake_conn({"Contacts": [2213400]})
    rc = _run_main(tmp_path, monkeypatch, conn,
                   extra_flags=("--quiet", "--dry-run"))
    assert rc == 0
    assert conn.rolled_back is True
    assert conn.committed is False
    # Dry-run still executes the UPDATEs (they roll back).
    assert len(_updates(cur)) == len(sh._TABLES)


def test_summary_counts(tmp_path, monkeypatch, capsys):
    """One renamed member, one collision skip: summary reflects both.
    FakeCursor.rowcount defaults to 1, so every table reports 1 row."""
    conn, cur = _make_fake_conn({
        "Contacts": [2213400, 2400600, 24006],
    })
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0

    out = capsys.readouterr().out
    assert "Shorten-double-zero-ID summary" in out
    # Whitespace-insensitive: the summary aligns numbers with space
    # runs; asserting exact spacing would couple the test to layout.
    assert re.search(r"Candidate IDs found \(>5 digits, ends 00\):\s+2\b", out)
    assert re.search(r"Members renamed:\s+1\b", out)
    assert re.search(r"Members skipped \(collision\):\s+1\b", out)
    assert re.search(r"Members skipped \(still too long\):\s+0\b", out)
    assert "Mode: APPLIED" in out


def test_quiet_suppresses_per_member_output(tmp_path, monkeypatch, capsys):
    conn, cur = _make_fake_conn({"Contacts": [2213400, 2400600, 24006]})
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Shorten-double-zero-ID summary" in out
    assert "renamed 2213400" not in out
    assert "skipped 2400600" not in out


def test_non_quiet_prints_per_member_lines(tmp_path, monkeypatch, capsys):
    conn, cur = _make_fake_conn({"Contacts": [2213400, 2400600, 24006]})
    rc = _run_main(tmp_path, monkeypatch, conn, extra_flags=())
    assert rc == 0
    out = capsys.readouterr().out
    assert "renamed 2213400 -> 22134" in out
    assert "skipped 2400600 -> 24006" in out
    assert "target ID already exists in: Contacts" in out
```

Note on `test_summary_counts` / quiet tests data: `2213400` renames to `22134` (absent → OK); `2400600` strips to `24006`, which IS present in Contacts → collision skip; `24006` itself is 5 digits → not a candidate.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_shorten_double_zero_ids.py -v -k "main or summary or quiet or dry_run"`
Expected: FAIL with `AttributeError: ... has no attribute 'main'` (except `test_main_missing_db_returns_2`-style failures also being AttributeError).

- [ ] **Step 3: Write the implementation**

Append to `scripts/shorten_double_zero_ids.py`:

```python
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

        # Per-table sets of distinct integer Center IDs (NULLs
        # skipped). Used for both candidate discovery and the
        # collision check.
        ids_by_table = {}
        for table in _TABLES:
            cur.execute(_SCAN_TEMPLATE.format(table=table))
            ids_by_table[table] = {
                int(row[0]) for row in cur.fetchall()
                if row[0] is not None
            }

        # Candidates come from the UNION of all tables so orphaned
        # child-table rows (qualifying ID, no Contacts row) rename too.
        all_ids = set().union(*ids_by_table.values())
        candidates = sorted(cid for cid in all_ids if _qualifies(cid))

        stats = {
            "renamed": 0,
            "skipped_collision": 0,
            "skipped_too_long": 0,
        }
        rows_updated = {table: 0 for table in _TABLES}
        skipped_rows = []

        for old_id in candidates:
            new_id = _new_id(old_id)

            if len(str(new_id)) > 5:
                reason = "still longer than 5 digits after stripping 00"
                skipped_rows.append(
                    {"old_id": old_id, "new_id": new_id, "reason": reason}
                )
                stats["skipped_too_long"] += 1
                if not args.quiet:
                    print(f"  skipped {old_id} -> {new_id} ({reason})")
                continue

            collisions = [
                t for t in _TABLES if new_id in ids_by_table[t]
            ]
            if collisions:
                reason = (
                    "target ID already exists in: " + ", ".join(collisions)
                )
                skipped_rows.append(
                    {"old_id": old_id, "new_id": new_id, "reason": reason}
                )
                stats["skipped_collision"] += 1
                if not args.quiet:
                    print(f"  skipped {old_id} -> {new_id} ({reason})")
                continue

            # No collision: rename in every table. Tables without the
            # old ID report rowcount 0 and don't pollute the counters.
            # The prefetched sets stay valid without re-scanning: the
            # mapping old->new is injective, and a qualifying old ID
            # (>5 digits) can never equal a rename target (<=5 digits).
            member_rows = 0
            tables_touched = 0
            for table in _TABLES:
                cur.execute(
                    _RENAME_TEMPLATE.format(table=table), new_id, old_id
                )
                if cur.rowcount > 0:
                    rows_updated[table] += cur.rowcount
                    member_rows += cur.rowcount
                    tables_touched += 1
            stats["renamed"] += 1
            if not args.quiet:
                print(
                    f"  renamed {old_id} -> {new_id} "
                    f"({member_rows} rows across {tables_touched} tables)"
                )

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        csv_path = _write_skipped_csv(skipped_rows, args.csv_out, today)

        print()
        print("Shorten-double-zero-ID summary")
        print(f"  Candidate IDs found (>5 digits, ends 00):  "
              f"{len(candidates)}")
        print(f"  Members renamed:                           "
              f"{stats['renamed']}")
        print("  Rows updated per table:")
        for table in _TABLES:
            print(f"    {table + ':':<21}{rows_updated[table]}")
        print(f"  Members skipped (collision):               "
              f"{stats['skipped_collision']}")
        print(f"  Members skipped (still too long):          "
              f"{stats['skipped_too_long']}")
        print(f"  Skipped CSV: {csv_path}")
        print(f"  Mode: {mode}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_shorten_double_zero_ids.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/shorten_double_zero_ids.py tests/test_shorten_double_zero_ids.py
git commit -m "feat(scripts): rename double-zero Center IDs across all tables"
```

---

## Task 4: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `python -m pytest`
Expected: everything passes; no existing test broken (this feature adds files only).

- [ ] **Step 2: Sanity-run the script's --help**

Run: `python scripts/shorten_double_zero_ids.py --help`
Expected: usage text showing `--db`, `--csv-out`, `--dry-run`, `--quiet`.

- [ ] **Step 3: Report done**

Manual operator steps (NOT part of this plan's execution — for the user, per the spec):

1. Copy `members.accdb` to a timestamped backup.
2. `python scripts/shorten_double_zero_ids.py --db <path> --dry-run` — review counts + skipped CSV.
3. Re-run without `--dry-run`; spot-check a renamed member in Access.
