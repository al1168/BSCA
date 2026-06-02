# Authorization Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-shot CLI that aligns `Authorization.[Health Plan]` and `Authorization` row presence with `Contacts`, per [docs/superpowers/specs/2026-06-02-authorization-backfill-design.md](../specs/2026-06-02-authorization-backfill-design.md).

**Architecture:** A single Python script in `scripts/`, structured like the sibling [`scripts/backfill_availability_from_hha.py`](../../../scripts/backfill_availability_from_hha.py): module-level SQL query constants, small pure helpers, one `main()` that opens a pyodbc connection, iterates Contacts in one pass, routes each member to an UPDATE branch (fill blank `[Health Plan]` on existing rows) or an INSERT branch (create one row from legacy `SADC` / `Auth BGN` / `Auth EXP` / `Health Plan`), writes a skipped-members CSV, and commits or rolls back.

**Tech Stack:** Python 3.11, `pyodbc` (Access ODBC driver), `argparse`, `csv`. Tests via `pytest`.

**Spec deviation — testing posture.** The spec mentioned "SQLite stand-in" integration tests. This plan instead uses the project's existing idiom: pure-helper tests + SQL-shape tests + a fake-cursor approach for the per-contact processor. The sibling HHA backfill has no SQLite tests either; introducing one just for this script would be over-investment. The integration test is `--dry-run` against a working copy of the real `.accdb`, matching how the HHA backfill is exercised.

## File Structure

- **Create:** `scripts/backfill_authorization_from_contacts.py` — the script
- **Create:** `tests/test_backfill_authorization.py` — unit tests for script helpers, SQL constants, CSV writer, missing-DB exit, fake-cursor tests for the processors
- **Modify:** `monthly_schedule/auth_days.py` — add `format_auth_days(set[int]) -> str` helper (the inverse of `get_authorized_weekdays`)
- **Modify:** `tests/test_auth_days.py` — parametrized test for `format_auth_days`
- **Modify:** `README.md` — append a "Backfill Authorization from Contacts" section

---

### Task 1: `format_auth_days` helper in monthly_schedule/auth_days.py

**Why first.** Every other task depends on knowing how a parsed SADC turns back into a `"1,3,5"` string. Doing this first keeps Task 5 (INSERT branch) self-contained.

**Files:**
- Modify: `monthly_schedule/auth_days.py`
- Test: `tests/test_auth_days.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_auth_days.py`:

```python
from monthly_schedule.auth_days import format_auth_days


@pytest.mark.parametrize(
    "days,expected",
    [
        ({1, 3, 5}, "1,3,5"),
        ({5, 1, 3}, "1,3,5"),       # sorted
        (set(), ""),                # empty -> empty string
        ({1}, "1"),
        ({1, 2, 3, 4, 5, 6, 7}, "1,2,3,4,5,6,7"),
    ],
)
def test_format_auth_days(days, expected):
    assert format_auth_days(days) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests\test_auth_days.py::test_format_auth_days -v`
Expected: FAIL with `ImportError: cannot import name 'format_auth_days'`.

- [ ] **Step 3: Add the helper**

Append to `monthly_schedule/auth_days.py`:

```python
def format_auth_days(days):
    """Inverse of get_authorized_weekdays: render a set of weekday
    ints (1-7) as the canonical "d,d,d" form used by the Access
    `auth_days` column. Empty set -> empty string."""
    return ",".join(str(n) for n in sorted(days))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests\test_auth_days.py -v`
Expected: PASS (the new test plus all existing tests in the file).

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/auth_days.py tests/test_auth_days.py
git commit -m "feat(auth_days): add format_auth_days as inverse of get_authorized_weekdays"
```

---

### Task 2: Script skeleton — argparse, connection string, missing-DB exit 2

Get the CLI shell up with no real work. Subsequent tasks fill the inside.

**Files:**
- Create: `scripts/backfill_authorization_from_contacts.py`
- Create: `tests/test_backfill_authorization.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backfill_authorization.py`:

```python
import os
import sys
from pathlib import Path

import pytest


# Ensure the script is importable as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import backfill_authorization_from_contacts as backfill


def test_build_connection_string():
    cs = backfill._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


def test_main_missing_db_returns_2(tmp_path, capsys):
    missing = tmp_path / "nope.accdb"
    rc = backfill.main(["--db", str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "database not found" in err.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests\test_backfill_authorization.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.backfill_authorization_from_contacts'`.

- [ ] **Step 3: Create the script skeleton**

Create `scripts/backfill_authorization_from_contacts.py`:

```python
"""Backfill the Authorization table from Contacts.

For every Contact:
  - If at least one Authorization row exists, UPDATE [Health Plan] on
    each row whose [Health Plan] is blank.
  - If no Authorization row exists, INSERT one from the legacy
    Contacts columns SADC / Auth BGN / Auth EXP / Health Plan.

Members with missing source data are skipped and written to a CSV.

See docs/superpowers/specs/2026-06-02-authorization-backfill-design.md
"""
import argparse
import os
import sys
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Backfill Authorization from Contacts."
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--csv-out", default=".",
                   help="Directory for the skipped CSV. Default: cwd.")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse + write CSV, do NOT commit DB changes.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-row stdout; print only the summary.")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if not os.path.exists(args.db):
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)
        return 2
    return 0  # placeholder; real work lands in later tasks


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests\test_backfill_authorization.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_authorization_from_contacts.py tests/test_backfill_authorization.py
git commit -m "feat(auth-backfill): CLI skeleton + missing-DB exit 2"
```

---

### Task 3: SQL query constants

Lock in every SQL string the script uses. Test their column-name shape to catch typos before runtime.

**Files:**
- Modify: `scripts/backfill_authorization_from_contacts.py`
- Modify: `tests/test_backfill_authorization.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backfill_authorization.py`:

```python
def test_contacts_query_columns():
    q = backfill._CONTACTS_QUERY
    for col in ("[Center ID]", "[Last Name]", "[First Name]",
                "[Health Plan]", "[SADC]", "[Auth BGN]", "[Auth EXP]"):
        assert col in q
    assert "FROM [Contacts]" in q
    assert "WHERE" not in q  # full table scan
    assert "ORDER BY [Center ID]" in q


def test_auth_select_query_for_member():
    q = backfill._AUTH_SELECT_FOR_MEMBER
    assert "[ID]" in q
    assert "[Health Plan]" in q
    assert "FROM [Authorization]" in q
    assert "WHERE [Center ID] = ?" in q


def test_auth_update_health_plan_query():
    q = backfill._AUTH_UPDATE_HEALTH_PLAN
    assert "UPDATE [Authorization]" in q
    assert "SET [Health Plan] = ?" in q
    assert "WHERE [ID] = ?" in q


def test_auth_insert_query_columns():
    q = backfill._AUTH_INSERT
    assert "INSERT INTO [Authorization]" in q
    for col in ("[Center ID]", "[auth_start]", "[auth_end]",
                "[effective_start]", "[effective_end]", "[auth_days]",
                "[Health Plan]"):
        assert col in q
    # Seven values, no trailing commas, exactly seven `?` placeholders.
    assert q.count("?") == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests\test_backfill_authorization.py -v -k "query"`
Expected: FAIL — the constants don't exist yet.

- [ ] **Step 3: Add the constants**

Insert at the top of `scripts/backfill_authorization_from_contacts.py`, after the imports and `sys.path.insert(...)` line:

```python
_CONTACTS_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[SADC], [Auth BGN], [Auth EXP] "
    "FROM [Contacts] "
    "ORDER BY [Center ID]"
)

_AUTH_SELECT_FOR_MEMBER = (
    "SELECT [ID], [Health Plan] FROM [Authorization] "
    "WHERE [Center ID] = ?"
)

_AUTH_UPDATE_HEALTH_PLAN = (
    "UPDATE [Authorization] SET [Health Plan] = ? WHERE [ID] = ?"
)

_AUTH_INSERT = (
    "INSERT INTO [Authorization] "
    "([Center ID], [auth_start], [auth_end], "
    "[effective_start], [effective_end], [auth_days], [Health Plan]) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests\test_backfill_authorization.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_authorization_from_contacts.py tests/test_backfill_authorization.py
git commit -m "feat(auth-backfill): SQL query constants"
```

---

### Task 4: `_is_blank` helper + UPDATE-branch processor

Adds the only-fill-blanks rule. Uses a fake cursor in tests so the processor is exercised without ODBC.

**Files:**
- Modify: `scripts/backfill_authorization_from_contacts.py`
- Modify: `tests/test_backfill_authorization.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backfill_authorization.py`:

```python
class FakeCursor:
    """Records execute() calls and returns canned fetch results.

    Use queue_fetchall() before each execute that the code-under-test
    will follow with fetchall(). Use queue_fetchone() similarly.
    """
    def __init__(self):
        self.executed = []        # list of (sql, params_tuple)
        self._fetchall_queue = []
        self._fetchone_queue = []

    def queue_fetchall(self, rows):
        self._fetchall_queue.append(rows)

    def queue_fetchone(self, row):
        self._fetchone_queue.append(row)

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self

    def fetchall(self):
        return self._fetchall_queue.pop(0)

    def fetchone(self):
        return self._fetchone_queue.pop(0)


def test_is_blank():
    assert backfill._is_blank(None) is True
    assert backfill._is_blank("") is True
    assert backfill._is_blank("   ") is True
    assert backfill._is_blank("\t\n") is True
    assert backfill._is_blank("HOF") is False
    assert backfill._is_blank("  HOF  ") is False


def test_update_branch_fills_only_blank_rows():
    cur = FakeCursor()
    # Two existing rows: ID=10 blank, ID=11 already "HOFV2".
    cur.queue_fetchall([(10, None), (11, "HOFV2")])
    stats = {"updated_members": 0, "updated_rows": 0}
    result = backfill._process_update_branch(
        cur, center_id=24010, health_plan="HOF", stats=stats,
    )
    assert result == ("updated", 1)  # 1 row filled
    # Verify the SELECT then exactly one UPDATE on ID=10.
    selects = [(s, p) for s, p in cur.executed
               if s == backfill._AUTH_SELECT_FOR_MEMBER]
    updates = [(s, p) for s, p in cur.executed
               if s == backfill._AUTH_UPDATE_HEALTH_PLAN]
    assert selects == [(backfill._AUTH_SELECT_FOR_MEMBER, ("24010",))]
    assert updates == [(backfill._AUTH_UPDATE_HEALTH_PLAN, ("HOF", 10))]
    assert stats == {"updated_members": 1, "updated_rows": 1}


def test_update_branch_all_rows_already_filled():
    cur = FakeCursor()
    cur.queue_fetchall([(10, "HOF"), (11, "HOFV2")])
    stats = {"updated_members": 0, "updated_rows": 0}
    result = backfill._process_update_branch(
        cur, center_id=24010, health_plan="HOF", stats=stats,
    )
    assert result == ("noop", 0)
    # No UPDATE was issued.
    assert all(s != backfill._AUTH_UPDATE_HEALTH_PLAN
               for s, _ in cur.executed)
    assert stats == {"updated_members": 0, "updated_rows": 0}


def test_update_branch_skips_when_contacts_health_plan_blank():
    cur = FakeCursor()
    cur.queue_fetchall([(10, None)])
    stats = {"updated_members": 0, "updated_rows": 0}
    result = backfill._process_update_branch(
        cur, center_id=24010, health_plan="", stats=stats,
    )
    assert result == ("skipped_no_plan", 0)
    assert all(s != backfill._AUTH_UPDATE_HEALTH_PLAN
               for s, _ in cur.executed)
    assert stats == {"updated_members": 0, "updated_rows": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests\test_backfill_authorization.py -v -k "is_blank or update_branch"`
Expected: FAIL — helpers don't exist yet.

- [ ] **Step 3: Implement `_is_blank` and `_process_update_branch`**

Append to `scripts/backfill_authorization_from_contacts.py`:

```python
def _is_blank(value):
    """True for NULL or a string that is empty / whitespace-only."""
    if value is None:
        return True
    return not str(value).strip()


def _process_update_branch(cur, center_id, health_plan, stats):
    """Fill blank [Health Plan] on every Authorization row for this
    member. Returns one of:
      ("updated", N)            — N rows were filled
      ("noop", 0)               — every row was already populated
      ("skipped_no_plan", 0)    — at least one blank row but Contacts
                                  has no Health Plan to fill it with
    Stats counters bookkeep updated_members and updated_rows.
    Caller is responsible for confirming count(Authorization) > 0 before
    calling this; here we re-read the rows we'll touch.
    """
    cur.execute(_AUTH_SELECT_FOR_MEMBER, str(center_id))
    rows = cur.fetchall()
    blanks = [row_id for row_id, plan in rows if _is_blank(plan)]
    if not blanks:
        return ("noop", 0)
    if _is_blank(health_plan):
        return ("skipped_no_plan", 0)
    for row_id in blanks:
        cur.execute(_AUTH_UPDATE_HEALTH_PLAN,
                    str(health_plan).strip(), int(row_id))
    stats["updated_members"] += 1
    stats["updated_rows"] += len(blanks)
    return ("updated", len(blanks))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests\test_backfill_authorization.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_authorization_from_contacts.py tests/test_backfill_authorization.py
git commit -m "feat(auth-backfill): UPDATE branch fills blank [Health Plan]"
```

---

### Task 5: INSERT-branch processor

Handles members with zero Authorization rows. Validates all four legacy fields are present, then writes the row.

**Files:**
- Modify: `scripts/backfill_authorization_from_contacts.py`
- Modify: `tests/test_backfill_authorization.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backfill_authorization.py`:

```python
from datetime import datetime


def test_insert_branch_happy_path():
    cur = FakeCursor()
    stats = {"inserted_members": 0}
    bgn = datetime(2026, 1, 1)
    exp = datetime(2026, 12, 31)
    result = backfill._process_insert_branch(
        cur, center_id=24010, sadc="1.3.5",
        auth_bgn=bgn, auth_exp=exp, health_plan="HOF", stats=stats,
    )
    assert result == ("inserted", None)
    inserts = [(s, p) for s, p in cur.executed
               if s == backfill._AUTH_INSERT]
    assert len(inserts) == 1
    _, params = inserts[0]
    # ([Center ID], auth_start, auth_end, eff_start, eff_end,
    #  auth_days, [Health Plan])
    assert params == ("24010", bgn, exp, bgn, exp, "1,3,5", "HOF")
    assert stats["inserted_members"] == 1


def test_insert_branch_skip_missing_all():
    cur = FakeCursor()
    stats = {"inserted_members": 0}
    result = backfill._process_insert_branch(
        cur, center_id=24010, sadc=None,
        auth_bgn=None, auth_exp=None, health_plan="", stats=stats,
    )
    assert result == ("skipped_missing", ["SADC", "Auth BGN",
                                          "Auth EXP", "Health Plan"])
    # No INSERT was issued.
    assert all(s != backfill._AUTH_INSERT for s, _ in cur.executed)
    assert stats["inserted_members"] == 0


def test_insert_branch_skip_missing_subset():
    cur = FakeCursor()
    stats = {"inserted_members": 0}
    result = backfill._process_insert_branch(
        cur, center_id=24010, sadc="1,3,5",
        auth_bgn=datetime(2026, 1, 1), auth_exp=None,
        health_plan="HOF", stats=stats,
    )
    assert result == ("skipped_missing", ["Auth EXP"])
    assert stats["inserted_members"] == 0


def test_insert_branch_sadc_garbage_treated_as_missing():
    cur = FakeCursor()
    stats = {"inserted_members": 0}
    # "TBD" parses to an empty set of weekdays.
    result = backfill._process_insert_branch(
        cur, center_id=24010, sadc="TBD",
        auth_bgn=datetime(2026, 1, 1), auth_exp=datetime(2026, 12, 31),
        health_plan="HOF", stats=stats,
    )
    assert result == ("skipped_missing", ["SADC"])
    assert stats["inserted_members"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests\test_backfill_authorization.py -v -k "insert_branch"`
Expected: FAIL — `_process_insert_branch` doesn't exist.

- [ ] **Step 3: Implement `_process_insert_branch`**

Append to `scripts/backfill_authorization_from_contacts.py`:

```python
from monthly_schedule.auth_days import (
    get_authorized_weekdays, format_auth_days,
)


def _process_insert_branch(cur, center_id, sadc, auth_bgn, auth_exp,
                           health_plan, stats):
    """Insert one Authorization row from the legacy Contacts columns.

    Returns one of:
      ("inserted", None)                 — row was inserted
      ("skipped_missing", [field, ...])  — listed legacy fields were
                                           NULL/empty; nothing inserted
    """
    auth_days_str = format_auth_days(get_authorized_weekdays(sadc))
    missing = []
    if auth_days_str == "":
        missing.append("SADC")
    if auth_bgn is None:
        missing.append("Auth BGN")
    if auth_exp is None:
        missing.append("Auth EXP")
    if _is_blank(health_plan):
        missing.append("Health Plan")
    if missing:
        return ("skipped_missing", missing)
    cur.execute(
        _AUTH_INSERT,
        str(center_id),
        auth_bgn, auth_exp,
        auth_bgn, auth_exp,
        auth_days_str,
        str(health_plan).strip(),
    )
    stats["inserted_members"] += 1
    return ("inserted", None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests\test_backfill_authorization.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_authorization_from_contacts.py tests/test_backfill_authorization.py
git commit -m "feat(auth-backfill): INSERT branch from legacy Contacts columns"
```

---

### Task 6: Skipped-CSV writer

UTF-8-with-BOM CSV, header written even on empty input. Matches the HHA CSV's conventions.

**Files:**
- Modify: `scripts/backfill_authorization_from_contacts.py`
- Modify: `tests/test_backfill_authorization.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backfill_authorization.py`:

```python
import csv
import datetime


def test_write_skipped_csv_header_only(tmp_path):
    path = backfill._write_skipped_csv(
        [], str(tmp_path), datetime.date(2026, 6, 2),
    )
    assert path.endswith("auth_backfill_skipped_2026-06-02.csv")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows == [["center_id", "last_name", "first_name",
                     "action", "missing_fields"]]


def test_write_skipped_csv_with_rows(tmp_path):
    rows_in = [
        {"center_id": 24012, "last_name": "Wong", "first_name": "Mei",
         "action": "no_health_plan_for_update",
         "missing_fields": "Health Plan"},
        {"center_id": 24013, "last_name": "Chen", "first_name": "Li",
         "action": "missing_legacy_fields",
         "missing_fields": "SADC; Auth EXP"},
    ]
    path = backfill._write_skipped_csv(
        rows_in, str(tmp_path), datetime.date(2026, 6, 2),
    )
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows == [
        {"center_id": "24012", "last_name": "Wong", "first_name": "Mei",
         "action": "no_health_plan_for_update",
         "missing_fields": "Health Plan"},
        {"center_id": "24013", "last_name": "Chen", "first_name": "Li",
         "action": "missing_legacy_fields",
         "missing_fields": "SADC; Auth EXP"},
    ]


def test_write_skipped_csv_creates_output_dir(tmp_path):
    out = tmp_path / "nested" / "dir"
    path = backfill._write_skipped_csv(
        [], str(out), datetime.date(2026, 6, 2),
    )
    assert os.path.exists(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests\test_backfill_authorization.py -v -k "skipped_csv"`
Expected: FAIL — `_write_skipped_csv` doesn't exist.

- [ ] **Step 3: Implement the CSV writer**

Insert these additions to `scripts/backfill_authorization_from_contacts.py`. Add `csv` and `datetime` to the imports at the top:

```python
import csv
import datetime
```

Then append:

```python
_CSV_COLUMNS = [
    "center_id", "last_name", "first_name",
    "action", "missing_fields",
]


def _write_skipped_csv(rows, out_dir, today):
    """Write the skipped-members CSV to
    `<out_dir>/auth_backfill_skipped_<YYYY-MM-DD>.csv`. Returns the
    path written. Writes the header even if `rows` is empty so the
    file's presence signals 'a backfill ran on this date'.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir,
        f"auth_backfill_skipped_{today.isoformat()}.csv",
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests\test_backfill_authorization.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_authorization_from_contacts.py tests/test_backfill_authorization.py
git commit -m "feat(auth-backfill): skipped-members CSV writer"
```

---

### Task 7: Wire `main()` — iterate Contacts, route, summary, commit/rollback

The last piece: stitch the helpers into a single pass over Contacts, accumulate stats and skip rows, print the run summary, and respect `--dry-run`.

**Files:**
- Modify: `scripts/backfill_authorization_from_contacts.py`
- Modify: `tests/test_backfill_authorization.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backfill_authorization.py`:

```python
def test_read_contacts_skips_null_center_id():
    class StubConn:
        def cursor(self):
            return self

        def execute(self, sql):
            self.sql = sql
            return self

        def fetchall(self):
            return [
                (None, "Skip", "Me", "HOF", "1,3,5", None, None),
                (24010, "Real", "One", "HOF", "1,3,5", None, None),
            ]

    conn = StubConn()
    rows = list(backfill._read_contacts(conn))
    assert len(rows) == 1
    assert rows[0][0] == 24010  # int
    assert conn.sql == backfill._CONTACTS_QUERY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests\test_backfill_authorization.py::test_read_contacts_skips_null_center_id -v`
Expected: FAIL — `_read_contacts` doesn't exist.

- [ ] **Step 3: Implement `_read_contacts`**

Append to `scripts/backfill_authorization_from_contacts.py`:

```python
def _read_contacts(conn):
    """Yield (cid:int, last, first, health_plan, sadc, auth_bgn,
    auth_exp) tuples. Rows with NULL Center ID are skipped silently."""
    cur = conn.cursor()
    cur.execute(_CONTACTS_QUERY)
    for row in cur.fetchall():
        cid, last, first, plan, sadc, bgn, exp = row
        if cid is None:
            continue
        yield (int(cid), last, first, plan, sadc, bgn, exp)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests\test_backfill_authorization.py -v`
Expected: all PASS.

- [ ] **Step 5: Rewrite `main()` to use the helpers**

Replace the placeholder `main()` body with the full implementation. The final `scripts/backfill_authorization_from_contacts.py` should have `main()` looking like this:

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
        stats = {
            "scanned": 0,
            "updated_members": 0,
            "updated_rows": 0,
            "noop_members": 0,
            "skipped_no_plan_members": 0,
            "inserted_members": 0,
            "skipped_missing_members": 0,
        }
        skipped_rows = []

        for cid, last, first, plan, sadc, bgn, exp in _read_contacts(conn):
            stats["scanned"] += 1
            # Branch decision: any existing Authorization row for this
            # member?
            cur.execute(_AUTH_SELECT_FOR_MEMBER, str(cid))
            existing = cur.fetchall()
            if existing:
                # UPDATE branch. _process_update_branch re-issues the
                # SELECT internally; pass the already-fetched rows by
                # re-binding the cursor is unnecessary because Access
                # cursors don't allow result reuse cleanly. The second
                # SELECT is cheap.
                result, n = _process_update_branch(
                    cur, cid, plan, stats,
                )
                if result == "updated":
                    if not args.quiet:
                        print(f"  UPDATED   {cid}  filled {n} row(s) "
                              f"with {str(plan).strip()!r}")
                elif result == "noop":
                    stats["noop_members"] += 1
                else:  # "skipped_no_plan"
                    stats["skipped_no_plan_members"] += 1
                    skipped_rows.append({
                        "center_id": cid,
                        "last_name": last or "",
                        "first_name": first or "",
                        "action": "no_health_plan_for_update",
                        "missing_fields": "Health Plan",
                    })
                    if not args.quiet:
                        print(f"  SKIPPED   {cid}  no Health Plan on "
                              f"Contacts (had {len(existing)} existing "
                              f"auth row(s))")
            else:
                # INSERT branch.
                result, payload = _process_insert_branch(
                    cur, cid, sadc, bgn, exp, plan, stats,
                )
                if result == "inserted":
                    if not args.quiet:
                        from monthly_schedule.auth_days import (
                            format_auth_days, get_authorized_weekdays,
                        )
                        days = format_auth_days(
                            get_authorized_weekdays(sadc)
                        )
                        print(f"  INSERTED  {cid}  "
                              f"{str(plan).strip()}, {days}, "
                              f"{bgn.date()} -> {exp.date()}")
                else:  # "skipped_missing"
                    stats["skipped_missing_members"] += 1
                    skipped_rows.append({
                        "center_id": cid,
                        "last_name": last or "",
                        "first_name": first or "",
                        "action": "missing_legacy_fields",
                        "missing_fields": "; ".join(payload),
                    })
                    if not args.quiet:
                        print(f"  SKIPPED   {cid}  no existing auth + "
                              f"missing: {', '.join(payload)}")

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        csv_path = _write_skipped_csv(skipped_rows, args.csv_out, today)

        print()
        print("Authorization backfill summary")
        print(f"  Contacts scanned:                            "
              f"{stats['scanned']}")
        print(f"  Existing-auth members: Health Plan filled:   "
              f"{stats['updated_members']}   "
              f"(rows updated: {stats['updated_rows']})")
        print(f"  Existing-auth members: already populated:    "
              f"{stats['noop_members']}")
        print(f"  Existing-auth members: skipped (no plan):    "
              f"{stats['skipped_no_plan_members']}")
        print(f"  No-auth members: Authorization inserted:     "
              f"{stats['inserted_members']}")
        print(f"  No-auth members: skipped (missing legacy):   "
              f"{stats['skipped_missing_members']}")
        print(f"  Skipped CSV: {csv_path}")
        print(f"  Mode: {mode}")
    finally:
        conn.close()
    return 0
```

Note: the `_process_update_branch` re-issues the `SELECT` internally, so the `cur.execute(_AUTH_SELECT_FOR_MEMBER, str(cid))` in `main()` is only used to ask "any rows?" via `fetchall()`. Two reads per member, one write — acceptable for a one-shot script. If a future optimization matters, pass the already-fetched rows into the helper.

- [ ] **Step 6: Run all backfill tests to verify nothing regressed**

Run: `.venv\Scripts\pytest tests\test_backfill_authorization.py -v`
Expected: every test in the file PASSES. The fake-cursor tests still drive the helpers directly; the new `main()` is exercised indirectly by `test_main_missing_db_returns_2`.

- [ ] **Step 7: Commit**

```bash
git add scripts/backfill_authorization_from_contacts.py tests/test_backfill_authorization.py
git commit -m "feat(auth-backfill): wire main() + run summary + commit/rollback"
```

---

### Task 8: README section

Documents the script for the operator. Mirrors the structure of the existing "Backfill Availability from HHA notes" block.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append the new section**

Insert the new section into `README.md` directly after the existing "Backfill Availability from HHA notes" section (i.e., before "## Setup"). The exact block to append:

```markdown
## Backfill Authorization from Contacts

One-shot script that aligns the `Authorization` table with
`Contacts` in two ways:

1. For every Contact whose Authorization rows already exist, fills
   any blank `Health Plan` column with the value from
   `Contacts.[Health Plan]`. Non-blank values are left alone —
   Authorization is the going-forward source of truth.
2. For every Contact with no Authorization row, inserts one from
   the legacy Contacts columns `SADC` → `auth_days`,
   `Auth BGN`/`Auth EXP` → `auth_start`/`auth_end` (and the
   matching `effective_*` pair), and `Health Plan`.

Members with missing source data are emitted to a dated CSV for
human review.

```
python scripts\backfill_authorization_from_contacts.py --db <PATH> [--dry-run] [--csv-out DIR] [--quiet]
```

`--dry-run` runs the full pass, writes the CSV, then rolls back
the DB transaction so the operator can preview without
committing. The skipped CSV lands at
`<csv-out>/auth_backfill_skipped_<YYYY-MM-DD>.csv` (utf-8-sig so
Excel renders CJK correctly). Full design in
[`docs/superpowers/specs/2026-06-02-authorization-backfill-design.md`](docs/superpowers/specs/2026-06-02-authorization-backfill-design.md).
```

- [ ] **Step 2: Render-check the README locally**

Open `README.md` and scroll to the new section. Confirm:
- The block sits between "Backfill Availability from HHA notes" and "## Setup".
- The code fence around the invocation renders cleanly (no nested-fence breakage from the surrounding fence in this plan).
- The link target resolves to the design doc created in the brainstorming step.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README section for Authorization backfill script"
```

---

## Self-Review

**Spec coverage check (against [2026-06-02-authorization-backfill-design.md](../specs/2026-06-02-authorization-backfill-design.md)):**

- Goal §1 (Health Plan backfill on existing rows) → Task 4.
- Goal §2 (insert from legacy columns) → Task 5.
- Out of scope (no other tables, no overwrite, no other legacy cols) → enforced by branch design in Tasks 4–5; no task creates code that touches Enrollment/Absences/Availability.
- Data flow diagram → Task 7 wires the two branches around the COUNT/SELECT decision.
- `[Center ID]` bound as string → enforced in Tasks 4, 5, 7 (`str(cid)` and `str(center_id)`).
- `auth_days` formatting via `format_auth_days(get_authorized_weekdays(...))` → Task 1 helper, used in Task 5.
- Only-fill-blanks → Task 4 (`blanks` list).
- Same Health Plan across all blank rows → Task 4 loops over `blanks`.
- Date typing pass-through → Task 5 passes `bgn`/`exp` straight to INSERT.
- One transaction, commit at end or rollback on `--dry-run` → Task 7.
- "Blank" = NULL or whitespace → Task 4 `_is_blank`, tested.
- CLI flags (`--db`, `--dry-run`, `--csv-out`, `--quiet`) → Task 2.
- Exit codes (0 / 2) → Task 2 (missing DB) + Task 7 (ODBC failure path returns 2).
- Per-row stdout format → Task 7 print statements match spec wording.
- Skipped CSV columns and `action` values → Task 6 + Task 7.
- Run summary lines → Task 7 print statements match spec layout.
- Edge cases (NULL Center ID skip, SADC=`"TBD"`, partial Auth BGN/EXP, member-with-mix-of-blank-and-filled rows) → Tasks 4 + 5 + 7 tests.
- README section → Task 8.

**Placeholder scan:** none.

**Type consistency:** Helper names match across tasks (`_is_blank`, `_process_update_branch`, `_process_insert_branch`, `_write_skipped_csv`, `_read_contacts`, `_CONTACTS_QUERY`, `_AUTH_SELECT_FOR_MEMBER`, `_AUTH_UPDATE_HEALTH_PLAN`, `_AUTH_INSERT`, `_CSV_COLUMNS`). The `stats` dict keys are introduced incrementally — Task 4 adds `updated_members` / `updated_rows`, Task 5 adds `inserted_members`, Task 7 introduces the rest (`scanned`, `noop_members`, `skipped_no_plan_members`, `skipped_missing_members`) and initializes the whole dict in one place.

No gaps found.
