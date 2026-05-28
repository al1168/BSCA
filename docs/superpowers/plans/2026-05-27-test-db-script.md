# Test-DB Setup Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A developer CLI (`scripts/make_test_db.py`) that creates or resets a throwaway Access database seeded with one of four named scenarios, optionally flipping `bsca_settings.json` so the GUI immediately uses it.

**Architecture:** A single argparse-based script. Copies the production `.accdb` to a target path (if missing), opens it via `pyodbc`, truncates the five data tables, and runs the chosen seed function. Date math is computed once from `date.today()` and threaded into each seed function so the seeded data always covers "the current schedule month." All four seeds live inline as module-level functions.

**Tech Stack:** Python 3.13, pyodbc (existing dependency, Access ODBC driver), argparse, datetime/calendar, shutil. No new dependencies.

**Spec:** [docs/superpowers/specs/2026-05-27-test-db-script-design.md](../specs/2026-05-27-test-db-script-design.md)

---

## Preconditions

- The production `.accdb` referenced by `--source` (default `\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb`) must be reachable when first creating a test DB.
- The five tables (`Contacts`, `Enrollment`, `Authorization`, `Absences`, `Availability`) must exist in the source DB. The schedule-data-model branch (`feat/schedule-data-model`) added queries that depend on this layout — this plan assumes the same branch is the parent.

---

## File Inventory

| File | Action | Responsibility |
| --- | --- | --- |
| `scripts/__init__.py` | Create | Empty; makes `scripts/` a package. |
| `scripts/make_test_db.py` | Create | The CLI + helpers + four seed functions. |
| `.gitignore` | Modify | Add `test_dbs/` line. |

No tests. Per the spec, the script IS the test — verification is by running it and counting rows in the resulting DB.

---

## Task 1: Scaffolding + CLI + helpers (no scenario logic yet)

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/make_test_db.py`
- Modify: `.gitignore`

This task lands the full machinery — argparse, copy/truncate logic, settings flip, helper functions — with stub seed functions that do nothing. After this task `--help` lists all four scenarios; running any of them creates an empty (truncated) test DB.

- [ ] **Step 1: Add `test_dbs/` to `.gitignore`**

Open `.gitignore` and append a new line:

```
test_dbs/
```

- [ ] **Step 2: Create `scripts/__init__.py`**

Create `scripts/__init__.py` with no content (zero bytes; an empty file).

- [ ] **Step 3: Create `scripts/make_test_db.py`**

Create `scripts/make_test_db.py` with this exact content:

```python
"""scripts/make_test_db.py

Create/reset an Access .accdb seeded with one of the named test
scenarios. Designed to spare the production DB from manual edits when
exercising the GUI.

Usage:
    python scripts/make_test_db.py --scenario <name> [--output PATH] [--source PATH] [--use]
"""

import argparse
import os
import shutil
import sys
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Callable


# Default reference DB (matches new_monthly_schedule.DEFAULT_DB).
DEFAULT_SOURCE = r"\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb"

# Deletion order: children first, parents last. Access FK constraints
# may or may not enforce; deleting in this order is safe regardless.
DATA_TABLES = ("Availability", "Absences", "Authorization",
               "Enrollment", "Contacts")


# ── Date math ─────────────────────────────────────────────────────────

def _month_bounds(today: date):
    """Return (M1, M15, MLAST, MNEXT_LAST) anchored to `today`."""
    m1 = today.replace(day=1)
    m15 = today.replace(day=15)
    mlast_day = monthrange(today.year, today.month)[1]
    mlast = today.replace(day=mlast_day)
    if today.month == 12:
        next_m1 = date(today.year + 1, 1, 1)
    else:
        next_m1 = date(today.year, today.month + 1, 1)
    next_last_day = monthrange(next_m1.year, next_m1.month)[1]
    mnext_last = date(next_m1.year, next_m1.month, next_last_day)
    return m1, m15, mlast, mnext_last


def _dt(d: date) -> datetime:
    """`date` -> midnight `datetime`, for Access DATETIME columns."""
    return datetime(d.year, d.month, d.day)


def _hhmm(h: int, m: int) -> datetime:
    """Build the 1899-12-30 placeholder DATETIME Access uses for
    time-only fields (matches what avail_start / avail_end store)."""
    return datetime(1899, 12, 30, h, m)


# ── DB helpers ────────────────────────────────────────────────────────

def _build_connection_string(path: str) -> str:
    return f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={path};"


def _truncate_all(conn) -> None:
    """`DELETE FROM` each data table. Children first, then parents."""
    cur = conn.cursor()
    for table in DATA_TABLES:
        try:
            cur.execute(f"DELETE FROM [{table}]")
        except Exception as exc:
            raise RuntimeError(
                f"DELETE FROM [{table}] failed. The DB may be missing "
                f"this table — see docs/database.md for the expected "
                f"schema. Original error: {exc}"
            )
    conn.commit()


def _seed_member(conn, center_id: int, last: str, first: str,
                 plan: str = "HOF",
                 address: str = "123 Test St, New York, NY 10001") -> None:
    """Insert one Contacts row with only the columns the scheduler reads.
    Contacts.[Center ID] is DOUBLE in Access; pyodbc widens int → float."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO [Contacts] ([Center ID], [Last Name], [First Name], "
        "[Health Plan], [Address]) VALUES (?, ?, ?, ?, ?)",
        center_id, last, first, plan, address,
    )


# ── Scenarios ─────────────────────────────────────────────────────────
# Each function takes (conn, today) and inserts rows. Truncation
# happens once before the chosen seed runs; functions assume the
# tables are empty.

def seed_happy_path(conn, today: date) -> None:
    pass  # Implemented in Task 2.


def seed_missing_data(conn, today: date) -> None:
    pass  # Implemented in Task 3.


def seed_mid_period_change(conn, today: date) -> None:
    pass  # Implemented in Task 4.


def seed_plan_full(conn, today: date) -> None:
    pass  # Implemented in Task 5.


SCENARIOS: dict[str, Callable] = {
    "happy_path": seed_happy_path,
    "missing_data": seed_missing_data,
    "mid_period_change": seed_mid_period_change,
    "plan_full": seed_plan_full,
}


# ── Settings flip ─────────────────────────────────────────────────────

def _update_settings_db_path(target: str) -> None:
    """Flip bsca_settings.json's db_path to `target`, preserving every
    other key. Uses gui.app_settings so language and other prefs stay."""
    from gui import app_settings
    settings = app_settings.load()
    settings["db_path"] = os.path.abspath(target)
    app_settings.save(settings)


# ── CLI ────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create or reset an Access test DB seeded with one of the "
            "named scenarios."
        ),
    )
    parser.add_argument(
        "--scenario", required=True, choices=sorted(SCENARIOS),
        help="Which seed scenario to apply to the target DB.",
    )
    parser.add_argument(
        "--output",
        help="Target .accdb path (default: test_dbs/<scenario>.accdb).",
    )
    parser.add_argument(
        "--source", default=DEFAULT_SOURCE,
        help=(
            "Reference Access DB to copy from when creating a new target. "
            "Only used when the target file does not already exist."
        ),
    )
    parser.add_argument(
        "--use", action="store_true",
        help="Update bsca_settings.json to point the GUI at the new DB.",
    )
    args = parser.parse_args(argv)

    target = args.output or os.path.join("test_dbs", f"{args.scenario}.accdb")
    target = os.path.abspath(target)

    if not os.path.exists(target):
        if not os.path.exists(args.source):
            print(
                f"Source DB not found: {args.source}\n"
                "Pass --source to point at a different reference DB.",
                file=sys.stderr,
            )
            return 2
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(args.source, target)
        print(f"Copied {args.source} -> {target}")

    import pyodbc
    try:
        conn = pyodbc.connect(_build_connection_string(target))
    except pyodbc.Error as exc:
        print(
            f"Could not open the test DB at {target}.\n"
            f"If Access has this file open, close it first.\n"
            f"Original error: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        _truncate_all(conn)
        SCENARIOS[args.scenario](conn, date.today())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"Seeded scenario '{args.scenario}' into {target}")

    if args.use:
        _update_settings_db_path(target)
        print(f"Updated bsca_settings.json db_path -> {target}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Verify `--help` lists all four scenarios**

Run from PowerShell:

```powershell
.venv\Scripts\python.exe scripts\make_test_db.py --help
```

Expected: the `--scenario` line includes `{happy_path,missing_data,mid_period_change,plan_full}` (alphabetical thanks to `sorted(SCENARIOS)`).

- [ ] **Step 5: Verify the scaffold runs end-to-end against the live source**

Run:

```powershell
.venv\Scripts\python.exe scripts\make_test_db.py --scenario happy_path
```

Expected output:
- `Copied \\BOWERY3\...\Access Member 5.5.26_copy.accdb -> ...\test_dbs\happy_path.accdb`
- `Seeded scenario 'happy_path' into ...\test_dbs\happy_path.accdb`
- File exists at `test_dbs\happy_path.accdb`.

- [ ] **Step 6: Verify all five tables are empty in the new file**

```powershell
.venv\Scripts\python.exe -c "import pyodbc; c=pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=test_dbs/happy_path.accdb;'); cur=c.cursor(); [print(t, cur.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]) for t in ['Contacts', 'Enrollment', 'Authorization', 'Absences', 'Availability']]"
```

Expected: each prints `0`.

- [ ] **Step 7: Commit**

```bash
git add scripts/__init__.py scripts/make_test_db.py .gitignore
git commit -m "feat(scripts): scaffold make_test_db.py with CLI + truncate/copy/use logic

Empty scenario stubs land in this commit; each subsequent task fills
one in."
```

---

## Task 2: Implement `seed_happy_path`

**Files:**
- Modify: `scripts/make_test_db.py` (replace the body of `seed_happy_path`)

One member, fully set up: HOF, NYC, enrolled, authorized M/T/W/Th/F for the current and next month, available 08:00–16:00 every weekday.

- [ ] **Step 1: Replace the stub body of `seed_happy_path`**

Find this in `scripts/make_test_db.py`:

```python
def seed_happy_path(conn, today: date) -> None:
    pass  # Implemented in Task 2.
```

Replace with:

```python
def seed_happy_path(conn, today: date) -> None:
    """Center 99001 'Test, Happy' — full happy-path setup."""
    m1, m15, mlast, mnext_last = _month_bounds(today)
    enrolled_since = date(today.year - 1, today.month, 1)
    cur = conn.cursor()

    _seed_member(conn, 99001, "Test", "Happy")
    cur.execute(
        "INSERT INTO [Enrollment] ([Center ID], [start_date], [end_date]) "
        "VALUES (?, ?, NULL)",
        99001, _dt(enrolled_since),
    )
    cur.execute(
        "INSERT INTO [Authorization] ([Center ID], [auth_start], "
        "[auth_end], [effective_start], [effective_end], [auth_days]) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        "99001", _dt(m1), _dt(mnext_last),
        _dt(m1), _dt(mnext_last), "1,2,3,4,5",
    )
    for day_of_week in range(1, 6):  # Mon (1) … Fri (5)
        cur.execute(
            "INSERT INTO [Availability] ([Center ID], "
            "[effective_start_date], [effective_end_date], "
            "[Day Of Week], [avail_start], [avail_end]) "
            "VALUES (?, ?, NULL, ?, ?, ?)",
            "99001", _dt(enrolled_since), day_of_week,
            _hhmm(8, 0), _hhmm(16, 0),
        )
    conn.commit()
```

- [ ] **Step 2: Run the scenario**

```powershell
.venv\Scripts\python.exe scripts\make_test_db.py --scenario happy_path
```

Expected: `Seeded scenario 'happy_path' into ...test_dbs\happy_path.accdb`.

- [ ] **Step 3: Verify row counts**

```powershell
.venv\Scripts\python.exe -c "import pyodbc; c=pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=test_dbs/happy_path.accdb;'); cur=c.cursor(); [print(t, cur.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]) for t in ['Contacts', 'Enrollment', 'Authorization', 'Absences', 'Availability']]"
```

Expected:
- `Contacts 1`
- `Enrollment 1`
- `Authorization 1`
- `Absences 0`
- `Availability 5`

- [ ] **Step 4: Verify the scheduler accepts member 99001**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python.exe -c "from datetime import date; from monthly_schedule.db import get_enrollments, get_authorizations, get_absences, get_availability; from monthly_schedule.eligibility_context import MemberContext; from monthly_schedule.per_day import compute_month_failure; db='test_dbs/happy_path.accdb'; ctx=MemberContext(enrollments=get_enrollments(99001, db), authorizations=get_authorizations(99001, db), absences=get_absences(99001, db), availabilities=get_availability(99001, db)); print('failure:', compute_month_failure(date.today().year, date.today().month, ctx))"
```

Expected: `failure: None` (member has at least one eligible day in the current month).

- [ ] **Step 5: Commit**

```bash
git add scripts/make_test_db.py
git commit -m "feat(scripts): implement seed_happy_path scenario"
```

---

## Task 3: Implement `seed_missing_data`

**Files:**
- Modify: `scripts/make_test_db.py` (replace the body of `seed_missing_data`)

Three members each missing one piece of required data — exercises all three eligibility-stage failure reasons in one run.

- [ ] **Step 1: Replace the stub body of `seed_missing_data`**

Find this in `scripts/make_test_db.py`:

```python
def seed_missing_data(conn, today: date) -> None:
    pass  # Implemented in Task 3.
```

Replace with:

```python
def seed_missing_data(conn, today: date) -> None:
    """Three members each missing one prerequisite, to exercise the
    three eligibility-stage failure reasons."""
    m1, m15, mlast, mnext_last = _month_bounds(today)
    enrolled_since = date(today.year - 1, today.month, 1)
    cur = conn.cursor()

    # 99002 NoEnroll, Bob — Contacts + Auth + Availability, no Enrollment.
    _seed_member(conn, 99002, "NoEnroll", "Bob")
    cur.execute(
        "INSERT INTO [Authorization] ([Center ID], [auth_start], "
        "[auth_end], [effective_start], [effective_end], [auth_days]) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        "99002", _dt(m1), _dt(mnext_last),
        _dt(m1), _dt(mnext_last), "1,2,3,4,5",
    )
    for day_of_week in range(1, 6):
        cur.execute(
            "INSERT INTO [Availability] ([Center ID], "
            "[effective_start_date], [effective_end_date], "
            "[Day Of Week], [avail_start], [avail_end]) "
            "VALUES (?, ?, NULL, ?, ?, ?)",
            "99002", _dt(enrolled_since), day_of_week,
            _hhmm(8, 0), _hhmm(16, 0),
        )

    # 99003 NoAuth, Carol — Contacts + Enrollment + Availability, no Auth.
    _seed_member(conn, 99003, "NoAuth", "Carol")
    cur.execute(
        "INSERT INTO [Enrollment] ([Center ID], [start_date], [end_date]) "
        "VALUES (?, ?, NULL)",
        99003, _dt(enrolled_since),
    )
    for day_of_week in range(1, 6):
        cur.execute(
            "INSERT INTO [Availability] ([Center ID], "
            "[effective_start_date], [effective_end_date], "
            "[Day Of Week], [avail_start], [avail_end]) "
            "VALUES (?, ?, NULL, ?, ?, ?)",
            "99003", _dt(enrolled_since), day_of_week,
            _hhmm(8, 0), _hhmm(16, 0),
        )

    # 99004 Absent, Dave — full setup PLUS one Absence covering the whole month.
    _seed_member(conn, 99004, "Absent", "Dave")
    cur.execute(
        "INSERT INTO [Enrollment] ([Center ID], [start_date], [end_date]) "
        "VALUES (?, ?, NULL)",
        99004, _dt(enrolled_since),
    )
    cur.execute(
        "INSERT INTO [Authorization] ([Center ID], [auth_start], "
        "[auth_end], [effective_start], [effective_end], [auth_days]) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        "99004", _dt(m1), _dt(mnext_last),
        _dt(m1), _dt(mnext_last), "1,2,3,4,5",
    )
    cur.execute(
        "INSERT INTO [Absences] ([Center ID], [Leave Type], "
        "[Start_Date], [End_Date]) VALUES (?, ?, ?, ?)",
        "99004", "Vacation", _dt(m1), _dt(mlast),
    )
    conn.commit()
```

- [ ] **Step 2: Run the scenario**

```powershell
.venv\Scripts\python.exe scripts\make_test_db.py --scenario missing_data
```

Expected: `Seeded scenario 'missing_data' into ...test_dbs\missing_data.accdb`.

- [ ] **Step 3: Verify row counts**

```powershell
.venv\Scripts\python.exe -c "import pyodbc; c=pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=test_dbs/missing_data.accdb;'); cur=c.cursor(); [print(t, cur.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]) for t in ['Contacts', 'Enrollment', 'Authorization', 'Absences', 'Availability']]"
```

Expected:
- `Contacts 3`
- `Enrollment 2` (Carol + Dave)
- `Authorization 2` (Bob + Dave)
- `Absences 1` (Dave)
- `Availability 10` (5 for Bob + 5 for Carol)

- [ ] **Step 4: Verify each member produces the expected failure reason**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python.exe -c "from datetime import date; from monthly_schedule.db import get_enrollments, get_authorizations, get_absences, get_availability; from monthly_schedule.eligibility_context import MemberContext; from monthly_schedule.per_day import compute_month_failure; db='test_dbs/missing_data.accdb'; today=date.today(); [print(cid, compute_month_failure(today.year, today.month, MemberContext(enrollments=get_enrollments(cid, db), authorizations=get_authorizations(cid, db), absences=get_absences(cid, db), availabilities=get_availability(cid, db)))) for cid in [99002, 99003, 99004]]"
```

Expected:
- `99002 not enrolled during this month`
- `99003 no active authorization for this month`
- `99004 absent for the entire month`

- [ ] **Step 5: Commit**

```bash
git add scripts/make_test_db.py
git commit -m "feat(scripts): implement seed_missing_data scenario"
```

---

## Task 4: Implement `seed_mid_period_change`

**Files:**
- Modify: `scripts/make_test_db.py` (replace the body of `seed_mid_period_change`)

One member with two Authorization rows sharing the same `auth_start`/`auth_end` but different `effective_*` windows and different `auth_days`. Tests the most-recent-wins picker.

- [ ] **Step 1: Replace the stub body of `seed_mid_period_change`**

Find this in `scripts/make_test_db.py`:

```python
def seed_mid_period_change(conn, today: date) -> None:
    pass  # Implemented in Task 4.
```

Replace with:

```python
def seed_mid_period_change(conn, today: date) -> None:
    """Center 99005 'Switch, Eve' — two Auth rows carving up the month."""
    m1, m15, mlast, mnext_last = _month_bounds(today)
    m15_plus_1 = m15 + timedelta(days=1)
    enrolled_since = date(today.year - 1, today.month, 1)
    cur = conn.cursor()

    _seed_member(conn, 99005, "Switch", "Eve")
    cur.execute(
        "INSERT INTO [Enrollment] ([Center ID], [start_date], [end_date]) "
        "VALUES (?, ?, NULL)",
        99005, _dt(enrolled_since),
    )
    # Row 1: effective M1 → M15, M/W/F
    cur.execute(
        "INSERT INTO [Authorization] ([Center ID], [auth_start], "
        "[auth_end], [effective_start], [effective_end], [auth_days]) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        "99005", _dt(m1), _dt(mlast),
        _dt(m1), _dt(m15), "1,3,5",
    )
    # Row 2: effective M15+1 → MLAST, T/Th
    cur.execute(
        "INSERT INTO [Authorization] ([Center ID], [auth_start], "
        "[auth_end], [effective_start], [effective_end], [auth_days]) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        "99005", _dt(m1), _dt(mlast),
        _dt(m15_plus_1), _dt(mlast), "2,4",
    )
    conn.commit()
```

- [ ] **Step 2: Run the scenario**

```powershell
.venv\Scripts\python.exe scripts\make_test_db.py --scenario mid_period_change
```

Expected: `Seeded scenario 'mid_period_change' into ...test_dbs\mid_period_change.accdb`.

- [ ] **Step 3: Verify row counts**

```powershell
.venv\Scripts\python.exe -c "import pyodbc; c=pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=test_dbs/mid_period_change.accdb;'); cur=c.cursor(); [print(t, cur.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]) for t in ['Contacts', 'Enrollment', 'Authorization', 'Absences', 'Availability']]"
```

Expected:
- `Contacts 1`, `Enrollment 1`, `Authorization 2`, `Absences 0`, `Availability 0`.

- [ ] **Step 4: Verify the per-day picker chooses the right row before/after the boundary**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python.exe -c "from datetime import date; from monthly_schedule.db import get_enrollments, get_authorizations, get_absences, get_availability; from monthly_schedule.eligibility_context import MemberContext; db='test_dbs/mid_period_change.accdb'; today=date.today(); ctx=MemberContext(enrollments=get_enrollments(99005, db), authorizations=get_authorizations(99005, db), absences=get_absences(99005, db), availabilities=get_availability(99005, db)); first_half=date(today.year, today.month, 10); second_half=date(today.year, today.month, 20); print('first half auth_days:', ctx.active_authorization(first_half)['auth_days']); print('second half auth_days:', ctx.active_authorization(second_half)['auth_days'])"
```

Expected:
- `first half auth_days: 1,3,5`
- `second half auth_days: 2,4`

- [ ] **Step 5: Commit**

```bash
git add scripts/make_test_db.py
git commit -m "feat(scripts): implement seed_mid_period_change scenario"
```

---

## Task 5: Implement `seed_plan_full`

**Files:**
- Modify: `scripts/make_test_db.py` (replace the body of `seed_plan_full`)

Five HOF members for exercising plan-mode batch generation: three happy, one with no Auth, one with a tight Tuesday availability rule.

- [ ] **Step 1: Replace the stub body of `seed_plan_full`**

Find this in `scripts/make_test_db.py`:

```python
def seed_plan_full(conn, today: date) -> None:
    pass  # Implemented in Task 5.
```

Replace with:

```python
def seed_plan_full(conn, today: date) -> None:
    """Five HOF members: three happy, one missing auth, one with a
    tight Tuesday window that should leave Tuesdays blank."""
    m1, m15, mlast, mnext_last = _month_bounds(today)
    enrolled_since = date(today.year - 1, today.month, 1)
    cur = conn.cursor()

    def _happy(center_id: int, last: str, first: str) -> None:
        _seed_member(conn, center_id, last, first)
        cur.execute(
            "INSERT INTO [Enrollment] ([Center ID], [start_date], "
            "[end_date]) VALUES (?, ?, NULL)",
            center_id, _dt(enrolled_since),
        )
        cur.execute(
            "INSERT INTO [Authorization] ([Center ID], [auth_start], "
            "[auth_end], [effective_start], [effective_end], [auth_days]) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            str(center_id), _dt(m1), _dt(mnext_last),
            _dt(m1), _dt(mnext_last), "1,2,3,4,5",
        )

    _happy(99010, "Plan", "Alice")
    _happy(99011, "Plan", "Bob")
    _happy(99012, "Plan", "Carol")

    # 99013 — Contacts + Enrollment, no Authorization.
    _seed_member(conn, 99013, "Plan", "Dave")
    cur.execute(
        "INSERT INTO [Enrollment] ([Center ID], [start_date], [end_date]) "
        "VALUES (?, ?, NULL)",
        99013, _dt(enrolled_since),
    )

    # 99014 — happy + a Tuesday availability rule too tight for the
    # plan's 3.5-hour session minimum, so Tuesdays come back blank.
    _happy(99014, "Plan", "Eve")
    cur.execute(
        "INSERT INTO [Availability] ([Center ID], "
        "[effective_start_date], [effective_end_date], "
        "[Day Of Week], [avail_start], [avail_end]) "
        "VALUES (?, ?, NULL, ?, ?, ?)",
        "99014", _dt(enrolled_since), 2, _hhmm(12, 0), _hhmm(14, 0),
    )
    conn.commit()
```

- [ ] **Step 2: Run the scenario**

```powershell
.venv\Scripts\python.exe scripts\make_test_db.py --scenario plan_full
```

Expected: `Seeded scenario 'plan_full' into ...test_dbs\plan_full.accdb`.

- [ ] **Step 3: Verify row counts**

```powershell
.venv\Scripts\python.exe -c "import pyodbc; c=pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=test_dbs/plan_full.accdb;'); cur=c.cursor(); [print(t, cur.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]) for t in ['Contacts', 'Enrollment', 'Authorization', 'Absences', 'Availability']]"
```

Expected:
- `Contacts 5`, `Enrollment 5`, `Authorization 4` (Alice/Bob/Carol/Eve), `Absences 0`, `Availability 1` (Eve's Tuesday rule).

- [ ] **Step 4: Verify each of the 5 IDs lands the expected state**

Run these one-liners (each is a single PowerShell line):

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python.exe -c "from datetime import date; from monthly_schedule.db import get_members_by_plan; print(sorted(m['center_id'] for m in get_members_by_plan('HOF', 'test_dbs/plan_full.accdb')))"
```

Expected: `[99010, 99011, 99012, 99013, 99014]`.

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python.exe -c "from datetime import date; from monthly_schedule.db import get_enrollments, get_authorizations, get_absences, get_availability; from monthly_schedule.eligibility_context import MemberContext; from monthly_schedule.per_day import compute_month_failure; db='test_dbs/plan_full.accdb'; t=date.today(); print({cid: compute_month_failure(t.year, t.month, MemberContext(enrollments=get_enrollments(cid, db), authorizations=get_authorizations(cid, db), absences=get_absences(cid, db), availabilities=get_availability(cid, db))) for cid in [99010, 99011, 99012, 99013, 99014]})"
```

Expected (Python dict, abbreviated):
- `99010: None`, `99011: None`, `99012: None`
- `99013: 'no active authorization for this month'`
- `99014: None` (Eve has eligible days other than Tuesday)

The Tuesday-blank behavior is best confirmed via the GUI sanity-check at the end of the plan.

- [ ] **Step 5: Commit**

```bash
git add scripts/make_test_db.py
git commit -m "feat(scripts): implement seed_plan_full scenario"
```

---

## Self-Review Checklist (for the implementer)

Before declaring complete:

- [ ] Each `scripts/make_test_db.py --scenario X` command exits 0.
- [ ] Each scenario's row counts match the per-task verification expectation.
- [ ] `python scripts/make_test_db.py --scenario happy_path --use` flips `bsca_settings.json` to point at `test_dbs/happy_path.accdb` and the GUI picks it up on next launch.
- [ ] `git diff main..HEAD -- scripts/ .gitignore` shows the four expected files (`scripts/__init__.py`, `scripts/make_test_db.py`, plus the `.gitignore` line).
- [ ] No code outside `scripts/` and `.gitignore` was modified.

## Manual sanity-check the GUI integration

After Task 5:

1. `python scripts/make_test_db.py --scenario plan_full --use`
2. Launch the GUI (`.venv\Scripts\python.exe gui.py`).
3. Select "Entire Plan: HOF", click Generate.
4. Expect: 4 workbooks written (`Schedule_99010_...`, `99011_`, `99012_`, `99014_`), one failure row in the summary for 99013, and 99014's workbook has blank Tuesdays.
