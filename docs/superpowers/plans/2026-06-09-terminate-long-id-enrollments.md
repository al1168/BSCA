# Terminate Long-ID Enrollments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New CLI script `scripts/terminate_long_id_enrollments.py` that marks every Enrollment row whose member's `[Center ID]` is more than 5 digits long as terminated (`end_date = 2000-01-01`), processed member-centrically with a dry-run mode and skipped CSV.

**Architecture:** Mirror the structure of `scripts/backfill_enrollment_from_contacts.py` — same argparse layout (minus `--exclude-test-members`), same connection-string helper, same skipped-CSV pattern, same `main()` exit codes. Tests use the established `FakeCursor` / `FakeConn` mock pattern from `tests/test_backfill_enrollment.py`, extended to expose `rowcount`. Processing groups scan rows by Center ID so a member with both an open and a closed Enrollment is one decision, not two.

**Tech Stack:** Python 3.11, pyodbc, argparse, csv, datetime, unittest.mock (already in the project).

**Spec:** [docs/superpowers/specs/2026-06-09-terminate-long-id-enrollments-design.md](../specs/2026-06-09-terminate-long-id-enrollments-design.md)

---

## File Map

- `scripts/terminate_long_id_enrollments.py` — new CLI script (~150 lines). Constants, helpers, `main()`.
- `tests/test_terminate_long_id_enrollments.py` — new test file (~250 lines). Unit + integration tests using the `FakeCursor`/`FakeConn` pattern from `tests/test_backfill_enrollment.py`.

Two tasks; the script and its tests are committed together within each task per TDD. Task 3 is operator manual verification (no commit).

---

## Task 1: Constants, helpers, and parse_args (TDD)

**Files:**
- Create: `scripts/terminate_long_id_enrollments.py`
- Create: `tests/test_terminate_long_id_enrollments.py`

- [ ] **Step 1: Create the failing test file**

Create `tests/test_terminate_long_id_enrollments.py` with the unit-test block. The script doesn't exist yet, so the import will fail — that's expected.

```python
import datetime
import sys
from pathlib import Path

import pytest

# Ensure the script is importable as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import terminate_long_id_enrollments as term


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_termination_date_constant():
    assert term.TERMINATION_DATE == datetime.date(2000, 1, 1)


def test_csv_columns():
    assert term._CSV_COLUMNS == ["center_id", "existing_end_date", "reason"]


def test_enrollment_scan_query():
    q = term._ENROLLMENT_SCAN
    assert "SELECT" in q
    assert "[Center ID]" in q
    assert "[end_date]" in q
    assert "FROM [Enrollment]" in q
    assert "ORDER BY [Center ID]" in q


def test_enrollment_terminate_query():
    q = term._ENROLLMENT_TERMINATE
    assert "UPDATE [Enrollment]" in q
    assert "SET [end_date] = ?" in q
    assert "WHERE [Center ID] = ?" in q
    assert "[end_date] IS NULL" in q
    assert q.count("?") == 2


# ---------------------------------------------------------------------------
# _build_connection_string
# ---------------------------------------------------------------------------

def test_build_connection_string():
    cs = term._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


# ---------------------------------------------------------------------------
# _is_long_id
# ---------------------------------------------------------------------------

def test_is_long_id_true_cases():
    assert term._is_long_id(100000) is True       # 6 digits
    assert term._is_long_id(2400600) is True      # 7 digits
    assert term._is_long_id(2400600.0) is True    # DOUBLE form
    assert term._is_long_id(9999999999) is True   # 10 digits


def test_is_long_id_false_cases():
    assert term._is_long_id(1) is False           # 1 digit
    assert term._is_long_id(24010) is False       # 5 digits
    assert term._is_long_id(99999) is False       # 5 digits
    assert term._is_long_id(99999.0) is False     # DOUBLE form, 5 digits
    assert term._is_long_id(None) is False        # NULL Center ID


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------

def test_parse_args_requires_db():
    with pytest.raises(SystemExit):
        term._parse_args([])


def test_parse_args_defaults():
    args = term._parse_args(["--db", "C:/x.accdb"])
    assert args.db == "C:/x.accdb"
    assert args.csv_out == "."
    assert args.dry_run is False
    assert args.quiet is False


def test_parse_args_all_flags():
    args = term._parse_args([
        "--db", "C:/x.accdb",
        "--csv-out", "/tmp/out",
        "--dry-run",
        "--quiet",
    ])
    assert args.csv_out == "/tmp/out"
    assert args.dry_run is True
    assert args.quiet is True


def test_parse_args_no_exclude_test_members_flag():
    """Per the spec, --exclude-test-members does NOT exist on this
    script. Argparse should reject the unknown flag."""
    with pytest.raises(SystemExit):
        term._parse_args(["--db", "C:/x.accdb", "--exclude-test-members"])
```

- [ ] **Step 2: Run the tests — confirm they fail**

Run: `pytest tests/test_terminate_long_id_enrollments.py -v`
Expected: collection fails with `ModuleNotFoundError: No module named 'scripts.terminate_long_id_enrollments'`.

- [ ] **Step 3: Create the script skeleton**

Create `scripts/terminate_long_id_enrollments.py`:

```python
"""Mark long-ID Enrollment rows as terminated.

For every Enrollment row whose member's [Center ID] is more than 5
digits long AND whose end_date is currently NULL: set end_date to
2000-01-01. Rows that already have a non-null end_date are left
alone.

Processing is member-centric: a member with multiple Enrollment rows
(some open, some closed) gets ONE update and is reported ONCE.

Designed to be safe to run repeatedly. The eligibility logic in
monthly_schedule/per_day.py filters out members whose enrollment
ended before the target month, so terminated members silently drop
out of every future schedule run.
"""
import argparse
import csv
import datetime
import os
import sys
from collections import defaultdict
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


TERMINATION_DATE = datetime.date(2000, 1, 1)


_ENROLLMENT_SCAN = (
    "SELECT [Center ID], [end_date] FROM [Enrollment] "
    "ORDER BY [Center ID]"
)

_ENROLLMENT_TERMINATE = (
    "UPDATE [Enrollment] SET [end_date] = ? "
    "WHERE [Center ID] = ? AND [end_date] IS NULL"
)

_CSV_COLUMNS = ["center_id", "existing_end_date", "reason"]


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _is_long_id(center_id):
    """True if the Center ID, rendered as a base-10 integer string,
    is more than 5 characters long. Mirrors `_is_test_id` in
    backfill_enrollment_from_contacts.py for handling the DOUBLE-typed
    Center ID field without trailing '.0' confusion."""
    if center_id is None:
        return False
    return len(str(int(center_id))) > 5


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Terminate Enrollment rows for members whose Center ID "
            "is more than 5 digits long, by setting end_date = 2000-01-01."
        ),
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--csv-out", default=".",
                   help="Directory for the skipped CSV. Default: cwd.")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse + write CSV, do NOT commit DB changes.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-member stdout; print only the summary.")
    return p.parse_args(argv)


def _write_skipped_csv(rows, out_dir, today):
    """Write the skipped-members CSV. Returns the path written.
    Writes the header even if `rows` is empty so the file's presence
    signals 'a termination ran on this date'."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir,
        f"terminate_long_id_skipped_{today.isoformat()}.csv",
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def main(argv=None):
    # Implemented in Task 2.
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests — confirm they pass**

Run: `pytest tests/test_terminate_long_id_enrollments.py -v`
Expected: all 11 tests pass. `main()` is not tested yet (Task 2).

- [ ] **Step 5: Commit**

```bash
git add scripts/terminate_long_id_enrollments.py tests/test_terminate_long_id_enrollments.py
git commit -m "feat(scripts): terminate-long-id skeleton (constants + helpers + tests)"
```

---

## Task 2: main() integration with member-centric logic (TDD)

**Files:**
- Modify: `scripts/terminate_long_id_enrollments.py` (replace the `raise NotImplementedError` with a real `main()`)
- Modify: `tests/test_terminate_long_id_enrollments.py` (append the integration-test block)

- [ ] **Step 1: Append the integration-test block**

Append to `tests/test_terminate_long_id_enrollments.py`:

```python
# ---------------------------------------------------------------------------
# FakeCursor / FakeConn (mirrors tests/test_backfill_enrollment.py;
# adds `rowcount` because this script reads it).
# ---------------------------------------------------------------------------

class FakeCursor:
    """Records execute() calls; returns canned fetchall results. The
    `rowcount` attribute is settable per-test; defaults to 1 (single
    affected row) so happy-path tests don't need to set it explicitly."""
    def __init__(self):
        self.executed = []        # list of (sql, params_tuple)
        self._fetchall_queue = []
        self.rowcount = 1
        self._rowcount_queue = []

    def queue_fetchall(self, rows):
        self._fetchall_queue.append(rows)

    def queue_rowcount(self, n):
        """Queue a rowcount value to be returned by the NEXT execute()
        of the UPDATE query. Use when a test wants to verify the
        'Enrollment rows updated' summary counter."""
        self._rowcount_queue.append(n)

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        if self._rowcount_queue:
            self.rowcount = self._rowcount_queue.pop(0)
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


def _make_fake_conn(scan_rows):
    """Build a FakeConn whose cursor's fetchall (called by the scan)
    returns `scan_rows`."""
    cur = FakeCursor()
    cur.queue_fetchall(scan_rows)
    return FakeConn(cur), cur


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_missing_db_returns_2(tmp_path, capsys):
    missing = tmp_path / "nope.accdb"
    rc = term.main(["--db", str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "database not found" in err.lower()


def test_main_skips_short_ids(tmp_path, monkeypatch):
    """Short-ID rows must not trigger an UPDATE."""
    scan = [
        (24010, None),
        (25049, None),
    ]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    updates = [(s, p) for s, p in cur.executed
               if s == term._ENROLLMENT_TERMINATE]
    assert updates == []
    assert conn.committed is True


def test_main_terminates_long_id_with_null_end_date(tmp_path, monkeypatch):
    """Happy path: long-ID with NULL end_date triggers ONE UPDATE
    with parameters (datetime at 2000-01-01 00:00, cid)."""
    scan = [(2400600, None)]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    updates = [(s, p) for s, p in cur.executed
               if s == term._ENROLLMENT_TERMINATE]
    assert len(updates) == 1
    sql, params = updates[0]
    # main() converts TERMINATION_DATE (a date) to a datetime at
    # midnight before passing to pyodbc — matches the pattern used
    # by backfill_enrollment_from_contacts.py.
    assert params[0] == datetime.datetime(2000, 1, 1)
    assert params[1] == 2400600
    assert conn.committed is True


def test_main_skips_already_ended_long_id(tmp_path, monkeypatch):
    """Long-ID member whose only Enrollment row is already ended
    triggers no UPDATE and shows up in the skipped CSV."""
    scan = [(2400600, datetime.datetime(2025, 6, 30))]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    updates = [(s, p) for s, p in cur.executed
               if s == term._ENROLLMENT_TERMINATE]
    assert updates == []

    csv_path = tmp_path / f"terminate_long_id_skipped_{datetime.date.today().isoformat()}.csv"
    assert csv_path.exists()
    body = csv_path.read_text(encoding="utf-8-sig")
    assert "2400600" in body
    assert "2025-06-30" in body
    assert "end_date already set" in body


def test_main_mixed_null_and_ended_rows_for_same_member(
    tmp_path, monkeypatch,
):
    """Member-centric: a long-ID member with one NULL-end row and one
    already-ended row triggers ONE UPDATE for that member and does
    NOT appear in the skipped CSV."""
    scan = [
        (2400600, None),
        (2400600, datetime.datetime(2024, 1, 1)),
    ]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    updates = [(s, p) for s, p in cur.executed
               if s == term._ENROLLMENT_TERMINATE]
    assert len(updates) == 1, (
        "member-centric: exactly one UPDATE per member"
    )

    csv_path = tmp_path / f"terminate_long_id_skipped_{datetime.date.today().isoformat()}.csv"
    assert csv_path.exists()
    # The CSV body should contain only the header line, no data rows.
    body_lines = csv_path.read_text(encoding="utf-8-sig").splitlines()
    assert body_lines[0] == ",".join(term._CSV_COLUMNS)
    assert len(body_lines) == 1


def test_csv_skipped_row_uses_max_end_date(tmp_path, monkeypatch):
    """A member with multiple non-null end_dates lands in the CSV
    with the LATER (max) date."""
    scan = [
        (2400600, datetime.datetime(2024, 1, 1)),
        (2400600, datetime.datetime(2025, 6, 30)),
    ]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    csv_path = tmp_path / f"terminate_long_id_skipped_{datetime.date.today().isoformat()}.csv"
    body = csv_path.read_text(encoding="utf-8-sig")
    # Only the later date should appear; the earlier one should not be
    # a substring of any data row.
    assert "2025-06-30" in body
    # Confirm exactly one data row (header + 1 = 2 lines)
    assert len(body.splitlines()) == 2


def test_dry_run_calls_rollback_not_commit(tmp_path, monkeypatch):
    scan = [(2400600, None)]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--dry-run",
        "--quiet",
    ])
    assert rc == 0
    assert conn.rolled_back is True
    assert conn.committed is False


def test_quiet_suppresses_per_member_output(tmp_path, monkeypatch, capsys):
    """--quiet hides per-member lines but the summary still appears."""
    scan = [
        (2400600, None),
        (2401700, datetime.datetime(2024, 1, 1)),
    ]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    out = capsys.readouterr().out
    # Summary lines must appear
    assert "Terminate-long-ID summary" in out
    assert "Members terminated" in out
    # Per-member lines (terminated / skipped) must NOT appear
    assert "terminated cid=" not in out
    assert "skipped cid=" not in out


def test_non_quiet_prints_per_member_lines(tmp_path, monkeypatch, capsys):
    """Without --quiet, per-member lines do appear."""
    scan = [
        (2400600, None),
        (2401700, datetime.datetime(2024, 1, 1)),
    ]
    conn, cur = _make_fake_conn(scan)

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)

    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = term.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
    ])
    assert rc == 0

    out = capsys.readouterr().out
    assert "terminated cid=2400600" in out
    assert "skipped cid=2401700" in out
```

- [ ] **Step 2: Run the new tests — confirm they fail**

Run: `pytest tests/test_terminate_long_id_enrollments.py -v -k "main or csv_skipped or dry_run or quiet"`
Expected: every integration test fails with `NotImplementedError` (the placeholder `main()` from Task 1).

- [ ] **Step 3: Implement `main()`**

In `scripts/terminate_long_id_enrollments.py`, replace the placeholder `main()` and `if __name__ == ...` block at the bottom:

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

        # Scan + group by Center ID. Skip None and short-ID rows here
        # so they don't pollute the group map or the counts.
        cur.execute(_ENROLLMENT_SCAN)
        scan_rows = cur.fetchall()
        rows_by_cid = defaultdict(list)
        rows_scanned = len(scan_rows)
        for cid, end_date in scan_rows:
            if cid is None or not _is_long_id(cid):
                continue
            rows_by_cid[int(cid)].append(end_date)

        stats = {
            "rows_scanned": rows_scanned,
            "long_id_members": len(rows_by_cid),
            "members_terminated": 0,
            "rows_updated": 0,
            "members_skipped": 0,
        }
        skipped_rows = []

        # Convert TERMINATION_DATE to a datetime at midnight for
        # pyodbc — matches the pattern used by
        # backfill_enrollment_from_contacts.py for Access DATETIME
        # columns.
        term_dt = datetime.datetime(
            TERMINATION_DATE.year,
            TERMINATION_DATE.month,
            TERMINATION_DATE.day,
        )

        # Process each long-ID member exactly once.
        for cid in sorted(rows_by_cid):
            end_dates = rows_by_cid[cid]
            if any(ed is None for ed in end_dates):
                # At least one open Enrollment row — terminate this member.
                cur.execute(_ENROLLMENT_TERMINATE, term_dt, cid)
                stats["members_terminated"] += 1
                stats["rows_updated"] += cur.rowcount
                if not args.quiet:
                    print(
                        f"  terminated cid={cid} "
                        f"({cur.rowcount} rows)"
                    )
            else:
                # Every row already ended — record in the CSV.
                latest = max(end_dates)
                latest_iso = (
                    latest.date().isoformat()
                    if isinstance(latest, datetime.datetime)
                    else latest.isoformat()
                )
                skipped_rows.append({
                    "center_id": cid,
                    "existing_end_date": latest_iso,
                    "reason": "end_date already set",
                })
                stats["members_skipped"] += 1
                if not args.quiet:
                    print(
                        f"  skipped cid={cid} "
                        f"(existing end_date={latest_iso})"
                    )

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        csv_path = _write_skipped_csv(skipped_rows, args.csv_out, today)

        print()
        print("Terminate-long-ID summary")
        print(f"  Enrollment rows scanned:             "
              f"{stats['rows_scanned']}")
        print(f"  Long-ID members found (>5 digits):   "
              f"{stats['long_id_members']}")
        print(f"  Members terminated (end_date set):   "
              f"{stats['members_terminated']}")
        print(f"  Enrollment rows updated:             "
              f"{stats['rows_updated']}")
        print(f"  Members skipped (all already ended): "
              f"{stats['members_skipped']}")
        print(f"  Skipped CSV: {csv_path}")
        print(f"  Mode: {mode}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the full test file — confirm all pass**

Run: `pytest tests/test_terminate_long_id_enrollments.py -v`
Expected: all tests pass (11 from Task 1 + 9 integration tests = 20 tests).

- [ ] **Step 5: Run the full project test suite to confirm no regressions**

Run: `pytest -q`
Expected: prior test count + 20. No new failures. (Pre-existing failures from earlier branches are gone since `main` has the api-key + skipped-csv work; baseline should be all-pass at this point.)

- [ ] **Step 6: Commit**

```bash
git add scripts/terminate_long_id_enrollments.py tests/test_terminate_long_id_enrollments.py
git commit -m "feat(scripts): member-centric long-ID enrollment termination"
```

---

## Task 3: Manual verification

No code changes — operator sanity check before merging.

- [ ] **Step 1: Confirm clean tree on the feature branch**

Run: `git status --short`
Expected: only untracked artifact files (CSVs from prior runs, build/, .egg-info); no staged or unstaged changes related to this feature.

- [ ] **Step 2: Back up the .accdb (existing convention)**

Run:
```
cp "C:/Users/luald/OneDrive/Pictures/members.accdb" "C:/Users/luald/OneDrive/Pictures/members.backup_before_terminate_2026-06-09.accdb"
```

Expected: copy succeeds (~267 MB, takes seconds). The file lives outside the repo so it doesn't need to be gitignored.

- [ ] **Step 3: Dry-run against the real DB**

Run:
```
.venv/Scripts/python.exe scripts/terminate_long_id_enrollments.py --db "C:/Users/luald/OneDrive/Pictures/members.accdb" --dry-run
```

Expected summary (counts from the pre-implementation probe):
```
Terminate-long-ID summary
  Enrollment rows scanned:             <total Enrollment rows, ~453 or so>
  Long-ID members found (>5 digits):   159
  Members terminated (end_date set):   159
  Enrollment rows updated:             159
  Members skipped (all already ended): 0
  Skipped CSV: .\terminate_long_id_skipped_2026-06-09.csv
  Mode: DRY-RUN (no changes committed)
```

The exact "Enrollment rows scanned" depends on the full enrollment count; the 159 long-ID members number must match.

If the numbers don't match: stop and investigate. Don't commit, don't run for real.

- [ ] **Step 4: Apply for real**

Run:
```
.venv/Scripts/python.exe scripts/terminate_long_id_enrollments.py --db "C:/Users/luald/OneDrive/Pictures/members.accdb"
```

Expected: same summary as dry-run but with `Mode: APPLIED`.

- [ ] **Step 5: Verify post-state in the DB**

Run a quick check that the long-ID rows now have `end_date = 2000-01-01`:

```
.venv/Scripts/python.exe -c "
import pyodbc
conn = pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=C:/Users/luald/OneDrive/Pictures/members.accdb;')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM [Enrollment] WHERE Len(CStr([Center ID])) > 5 AND [end_date] = #2000-01-01#')
print(f'Long-ID rows with end_date=2000-01-01: {cur.fetchone()[0]}')
cur.execute('SELECT COUNT(*) FROM [Enrollment] WHERE Len(CStr([Center ID])) > 5 AND [end_date] IS NULL')
print(f'Long-ID rows still NULL-end:           {cur.fetchone()[0]}')
"
```

Expected:
- Long-ID rows with end_date=2000-01-01: 159
- Long-ID rows still NULL-end: 0

- [ ] **Step 6: End-to-end check via the GUI scheduler**

Launch `dist/MonthlyScheduleGenerator.exe` (or `python gui.py`). Run "All Members" for some future month against the same DB.

Expected: the run completes without listing any 6+ digit Center IDs in the skipped-members CSV under the `eligibility` stage as "not enrolled" — they're filtered out silently because their `end_date = 2000-01-01` is before any target month from 2000 forward. (They WILL appear in the skipped CSV's `eligibility — not enrolled during this month` rows when targeting months after 2000-01-01, but that's the expected eligibility-filter behavior.)

Actually, looking more carefully: per the spec, terminated members will appear in `skipped_members_<date>.csv` as eligibility skips. That's the intended observable signal — the schedule output workbook count for them stays at zero.

- [ ] **Step 7: No commit needed**

End of plan. The branch is ready to merge once Task 3 passes.

---

## Spec Coverage Verification

| Spec section | Task |
|---|---|
| New script `scripts/terminate_long_id_enrollments.py` | Task 1 (skeleton), Task 2 (main) |
| Mirror existing backfill script structure (argparse, helpers, summary) | Task 1 (Step 3), Task 2 (Step 3) |
| `_is_long_id` definition (`len(str(int(cid))) > 5`) | Task 1 (Step 3) |
| `TERMINATION_DATE = datetime.date(2000, 1, 1)` constant | Task 1 (Step 3) |
| Scan query + UPDATE query shapes | Task 1 (Step 3, Step 1 tests) |
| `--db`, `--csv-out`, `--dry-run`, `--quiet` flags; no `--exclude-test-members` | Task 1 (Step 3, Step 1 tests) |
| Skip None and short-ID rows silently | Task 2 (Step 3 main, `test_main_skips_short_ids`) |
| Member-centric: long-ID with NULL → UPDATE once; group by cid | Task 2 (Step 3, `test_main_mixed_null_and_ended_rows_for_same_member`) |
| Long-ID with non-null end_date → skip + write CSV with max date | Task 2 (Step 3, `test_csv_skipped_row_uses_max_end_date`) |
| CSV: `terminate_long_id_skipped_<YYYY-MM-DD>.csv` with `center_id, existing_end_date, reason` | Task 1 (Step 3 `_write_skipped_csv`), Task 1 (Step 1 `test_csv_columns`) |
| Dry-run: rollback, not commit; print `Mode: DRY-RUN` | Task 2 (`test_dry_run_calls_rollback_not_commit`) |
| Quiet flag suppresses per-member output | Task 2 (`test_quiet_suppresses_per_member_output`) |
| Summary stdout format | Task 2 (Step 3 main) |
| Manual verification on real DB (dry-run → real → post-state verify → GUI) | Task 3 |
