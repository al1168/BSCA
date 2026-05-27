# `populate_real_members` Scenario Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fifth scenario (`populate_real_members`) to [scripts/make_test_db.py](../../../scripts/make_test_db.py) that preserves the real Contacts table and seeds the four supporting tables against the real Center IDs, with a deterministic 10% failure sprinkle for run-summary testing.

**Architecture:** Two small changes. Task 1 refactors `_truncate_all(conn)` → `_truncate(conn, tables)` and introduces `SCENARIOS_KEEP_CONTACTS` so the scenario truncation can vary per-scenario; the new scenario is added as a stub. Task 2 implements the scenario body — reads sorted Center IDs from Contacts, iterates with a 30-cycle that produces 27 happy + 3 failures (one of each kind) per block, prints a one-line summary at the end.

**Tech Stack:** Python 3.13, pyodbc (existing), Access ODBC driver, argparse. No new dependencies.

**Spec:** [docs/superpowers/specs/2026-05-27-populate-real-members-design.md](../specs/2026-05-27-populate-real-members-design.md)

---

## Preconditions

- The source DB at `\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb` is reachable.
- The four new tables (`Enrollment`, `Authorization`, `Absences`, `Availability`) already exist on that DB with the columns the scheduler queries. (They do — verified by Task 1 of the test-db-script plan that already ran.)
- Tasks 1–5 of the test-db-script plan have already landed (the existing `scripts/make_test_db.py` is in place with four scenarios). This plan extends it.

---

## File Inventory

| File | Action | Responsibility |
| --- | --- | --- |
| `scripts/make_test_db.py` | Modify | Rename `_truncate_all` → `_truncate`; introduce `SUPPORTING_TABLES` and `SCENARIOS_KEEP_CONTACTS`; add `seed_populate_real_members` function and register it in `SCENARIOS`. |

No other files change. Per the parent spec, no tests are added — the seed function's end-of-run summary line IS the verification.

---

## Task 1: Refactor `_truncate_all` and add `seed_populate_real_members` stub

**Files:**
- Modify: `scripts/make_test_db.py`

This task is purely structural. After it, the existing four scenarios behave exactly as before, `--help` lists five scenarios, and running `--scenario populate_real_members` truncates only the four supporting tables (Contacts preserved) and does nothing else (the seed function is a stub).

- [ ] **Step 1: Split `DATA_TABLES` and add `SCENARIOS_KEEP_CONTACTS`**

In `scripts/make_test_db.py`, find:

```python
# Deletion order: children first, parents last. Access FK constraints
# may or may not enforce; deleting in this order is safe regardless.
DATA_TABLES = ("Availability", "Absences", "Authorization",
               "Enrollment", "Contacts")
```

Replace with:

```python
# Deletion order: children first, parents last. Access FK constraints
# may or may not enforce; deleting in this order is safe regardless.
SUPPORTING_TABLES = ("Availability", "Absences", "Authorization",
                     "Enrollment")
DATA_TABLES = SUPPORTING_TABLES + ("Contacts",)

# Scenarios that should preserve the real Contacts table and only
# truncate the four supporting tables. Used by main() to decide which
# list to hand _truncate().
SCENARIOS_KEEP_CONTACTS = {"populate_real_members"}
```

- [ ] **Step 2: Rename `_truncate_all` → `_truncate` with explicit `tables` parameter**

Find:

```python
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
```

Replace with:

```python
def _truncate(conn, tables) -> None:
    """`DELETE FROM` each table in `tables`. Caller supplies the order
    (children first, parents last)."""
    cur = conn.cursor()
    for table in tables:
        try:
            cur.execute(f"DELETE FROM [{table}]")
        except Exception as exc:
            raise RuntimeError(
                f"DELETE FROM [{table}] failed. The DB may be missing "
                f"this table — see docs/database.md for the expected "
                f"schema. Original error: {exc}"
            )
    conn.commit()
```

- [ ] **Step 3: Update `main()` to pick the truncate list and call the renamed helper**

Find this block in `main()` (around the `try:` / `_truncate_all(conn)` lines):

```python
    try:
        _truncate_all(conn)
        SCENARIOS[args.scenario](conn, date.today())
```

Replace with:

```python
    try:
        truncate_tables = (
            SUPPORTING_TABLES
            if args.scenario in SCENARIOS_KEEP_CONTACTS
            else DATA_TABLES
        )
        _truncate(conn, truncate_tables)
        SCENARIOS[args.scenario](conn, date.today())
```

- [ ] **Step 4: Add the new scenario stub and register it in `SCENARIOS`**

Find the existing scenario stubs section. After the last `seed_*` function and before the `SCENARIOS` dict, add:

```python
def seed_populate_real_members(conn, today: date) -> None:
    pass  # Implemented in Task 2.
```

Then find the `SCENARIOS` dict:

```python
SCENARIOS: dict[str, Callable] = {
    "happy_path": seed_happy_path,
    "missing_data": seed_missing_data,
    "mid_period_change": seed_mid_period_change,
    "plan_full": seed_plan_full,
}
```

Replace with:

```python
SCENARIOS: dict[str, Callable] = {
    "happy_path": seed_happy_path,
    "missing_data": seed_missing_data,
    "mid_period_change": seed_mid_period_change,
    "plan_full": seed_plan_full,
    "populate_real_members": seed_populate_real_members,
}
```

- [ ] **Step 5: Verify `--help` now lists five scenarios**

From PowerShell:

```powershell
.venv\Scripts\python.exe scripts\make_test_db.py --help
```

Expected: the `--scenario` line includes `{happy_path,mid_period_change,missing_data,plan_full,populate_real_members}` (alphabetical via `sorted(SCENARIOS)`).

- [ ] **Step 6: Verify the new scenario runs end-to-end as a no-op but truncates only the four supporting tables**

```powershell
.venv\Scripts\python.exe scripts\make_test_db.py --scenario populate_real_members
```

Expected output:
- `Copied \\BOWERY3\...\Access Member 5.5.26_copy.accdb -> ...\test_dbs\populate_real_members.accdb`
- `Seeded scenario 'populate_real_members' into ...\test_dbs\populate_real_members.accdb`

- [ ] **Step 7: Verify Contacts was preserved, supporting tables empty**

```powershell
.venv\Scripts\python.exe -c "import pyodbc; c=pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=test_dbs/populate_real_members.accdb;'); cur=c.cursor(); [print(t, cur.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]) for t in ['Contacts', 'Enrollment', 'Authorization', 'Absences', 'Availability']]"
```

Expected:
- `Contacts <N>` where N > 0 (real member count — confirms Contacts was preserved)
- `Enrollment 0`
- `Authorization 0`
- `Absences 0`
- `Availability 0`

- [ ] **Step 8: Verify the existing four scenarios still behave the same (they still truncate Contacts)**

```powershell
.venv\Scripts\python.exe scripts\make_test_db.py --scenario happy_path
.venv\Scripts\python.exe -c "import pyodbc; c=pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=test_dbs/happy_path.accdb;'); cur=c.cursor(); print('Contacts', cur.execute('SELECT COUNT(*) FROM [Contacts]').fetchone()[0])"
```

Expected: `Contacts 1` (just the synthetic 99001 member — confirms Contacts is still truncated and reseeded for the other scenarios).

- [ ] **Step 9: Commit**

```bash
git add scripts/make_test_db.py
git commit -m "refactor(scripts): _truncate_all -> _truncate(tables); add populate_real_members stub

Existing scenarios behave identically. populate_real_members truncates
only the four supporting tables (Contacts preserved). Scenario body
is a stub; Task 2 fills it in."
```

---

## Task 2: Implement `seed_populate_real_members`

**Files:**
- Modify: `scripts/make_test_db.py` (replace the stub body)

- [ ] **Step 1: Replace the stub body of `seed_populate_real_members`**

Find:

```python
def seed_populate_real_members(conn, today: date) -> None:
    pass  # Implemented in Task 2.
```

Replace with:

```python
def seed_populate_real_members(conn, today: date) -> None:
    """Seed the four supporting tables against the real Contacts IDs.

    Iterates every Contacts row (sorted by Center ID ascending) and
    inserts a happy-path setup. Every 30-cycle rotates through three
    deliberate failure shapes (positions 9, 19, 29 within each cycle)
    so the run-summary failures block is also exercised.
    """
    m1, m15, mlast, mnext_last = _month_bounds(today)
    enrolled_since = date(today.year - 1, today.month, 1)
    cur = conn.cursor()

    # Closures so each insert helper sees the date constants without
    # threading them through every call.

    def _enroll(cid: int) -> None:
        cur.execute(
            "INSERT INTO [Enrollment] ([Center ID], [start_date], "
            "[end_date]) VALUES (?, ?, NULL)",
            cid, _dt(enrolled_since),
        )

    def _authorize(cid: int) -> None:
        cur.execute(
            "INSERT INTO [Authorization] ([Center ID], [auth_start], "
            "[auth_end], [effective_start], [effective_end], [auth_days]) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            str(cid), _dt(m1), _dt(mnext_last),
            _dt(m1), _dt(mnext_last), "1,2,3,4,5",
        )

    def _make_available(cid: int) -> None:
        for day_of_week in range(1, 6):  # Mon … Fri
            cur.execute(
                "INSERT INTO [Availability] ([Center ID], "
                "[effective_start_date], [effective_end_date], "
                "[Day Of Week], [avail_start], [avail_end]) "
                "VALUES (?, ?, NULL, ?, ?, ?)",
                str(cid), _dt(enrolled_since), day_of_week,
                _hhmm(8, 0), _hhmm(16, 0),
            )

    def _mark_absent_month(cid: int) -> None:
        cur.execute(
            "INSERT INTO [Absences] ([Center ID], [Leave Type], "
            "[Start_Date], [End_Date]) VALUES (?, ?, ?, ?)",
            str(cid), "Vacation", _dt(m1), _dt(mlast),
        )

    cur.execute("SELECT [Center ID] FROM [Contacts] ORDER BY [Center ID]")
    raw_ids = [row[0] for row in cur.fetchall()]

    skipped_null = 0
    counts = {"happy": 0, "no_auth": 0, "absent": 0, "no_enrollment": 0}

    for idx, raw_id in enumerate(raw_ids):
        if raw_id is None:
            skipped_null += 1
            continue
        cid = int(raw_id)
        variant = idx % 30
        if variant == 9:
            # No Authorization
            _enroll(cid)
            _make_available(cid)
            counts["no_auth"] += 1
        elif variant == 19:
            # Absent entire month
            _enroll(cid)
            _authorize(cid)
            _make_available(cid)
            _mark_absent_month(cid)
            counts["absent"] += 1
        elif variant == 29:
            # No Enrollment
            _authorize(cid)
            _make_available(cid)
            counts["no_enrollment"] += 1
        else:
            # Happy path
            _enroll(cid)
            _authorize(cid)
            _make_available(cid)
            counts["happy"] += 1

    conn.commit()

    total = sum(counts.values())
    print(
        f"Seeded populate_real_members: {counts['happy']} happy / "
        f"{counts['no_auth']} no-auth / {counts['absent']} absent / "
        f"{counts['no_enrollment']} no-enrollment ({total} members total)"
    )
    if skipped_null:
        print(
            f"  (skipped {skipped_null} Contacts row(s) with NULL Center ID)"
        )
```

- [ ] **Step 2: Run the scenario**

```powershell
.venv\Scripts\python.exe scripts\make_test_db.py --scenario populate_real_members
```

Expected output (numbers depend on your real Contacts size; example for ~100 members):
- `Seeded populate_real_members: 90 happy / 3 no-auth / 3 absent / 3 no-enrollment (99 members total)`
- `Seeded scenario 'populate_real_members' into ...\test_dbs\populate_real_members.accdb`

Confirm: `happy + no_auth + absent + no_enrollment == total_members`, and the failure counts roughly equal `total // 30` each.

- [ ] **Step 3: Verify table row counts match expectations**

```powershell
.venv\Scripts\python.exe -c "import pyodbc; c=pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=test_dbs/populate_real_members.accdb;'); cur=c.cursor(); [print(t, cur.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]) for t in ['Contacts', 'Enrollment', 'Authorization', 'Absences', 'Availability']]"
```

Let `N` = `Contacts` count, `H` = happy count, `A` = no-auth, `B` = absent, `E` = no-enrollment (all from Step 2). Expected:
- `Contacts N` (unchanged from real DB)
- `Enrollment` = `H + A + B` (no-enrollment members skip this)
- `Authorization` = `H + B + E` (no-auth members skip this)
- `Absences` = `B` (only absent-entire-month members)
- `Availability` = `5 × (H + A + B + E)` = `5 × N_seeded`

If those four arithmetic identities hold, the seed correctly applied each variant.

- [ ] **Step 4: Spot-check the happy-path math**

Pick the first happy member (idx 0 — guaranteed to be happy since 0 % 30 != 9, 19, 29). Get its Center ID:

```powershell
.venv\Scripts\python.exe -c "import pyodbc; c=pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=test_dbs/populate_real_members.accdb;'); cur=c.cursor(); cur.execute('SELECT TOP 1 [Center ID] FROM [Contacts] ORDER BY [Center ID]'); print(int(cur.fetchone()[0]))"
```

Then verify the scheduler thinks they're eligible (no whole-member failure):

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python.exe -c "from datetime import date; from monthly_schedule.db import get_enrollments, get_authorizations, get_absences, get_availability; from monthly_schedule.eligibility_context import MemberContext; from monthly_schedule.per_day import compute_month_failure; import sys; cid=int(sys.argv[1]); db='test_dbs/populate_real_members.accdb'; ctx=MemberContext(enrollments=get_enrollments(cid, db), authorizations=get_authorizations(cid, db), absences=get_absences(cid, db), availabilities=get_availability(cid, db)); print(cid, compute_month_failure(date.today().year, date.today().month, ctx))" <FIRST_HAPPY_CID>
```

Replace `<FIRST_HAPPY_CID>` with the int from the previous command. Expected: `<CID> None`.

- [ ] **Step 5: Spot-check a failure-position member**

Get the 10th Center ID (idx 9, the no-auth variant):

```powershell
.venv\Scripts\python.exe -c "import pyodbc; c=pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=test_dbs/populate_real_members.accdb;'); cur=c.cursor(); cur.execute('SELECT [Center ID] FROM [Contacts] ORDER BY [Center ID]'); ids=[int(r[0]) for r in cur.fetchall()]; print(ids[9] if len(ids) > 9 else 'fewer than 10 members')"
```

If the result is an integer, run the same compute_month_failure check on it. Expected: the failure should be exactly `no active authorization for this month`. If the DB has fewer than 10 members, skip this step (the scenario still ran correctly; just no failure rows were produced).

- [ ] **Step 6: Commit**

```bash
git add scripts/make_test_db.py
git commit -m "feat(scripts): implement seed_populate_real_members

Iterates real Contacts IDs (sorted ascending) and seeds the four
supporting tables. Every 30-cycle rotates through three deliberate
failure shapes (positions 9 / 19 / 29) so the run-summary failures
block is also exercised. Prints a one-line tally + an optional
NULL-skip warning."
```

---

## Self-Review Checklist (for the implementer)

Before declaring complete:

- [ ] `--help` lists five scenarios (added `populate_real_members`).
- [ ] Running `--scenario populate_real_members` against a fresh target produces a non-empty Contacts count AND non-zero supporting-table counts.
- [ ] Arithmetic identity check from Task 2 Step 3 holds (Enrollment = H+A+B, etc.).
- [ ] Running any of the original four scenarios (e.g. `happy_path`) against a fresh target still produces `Contacts 1` — confirms the existing behavior wasn't broken.
- [ ] No code outside `scripts/make_test_db.py` was touched.
- [ ] `pytest -v` still green (158 tests).

## Manual sanity-check the GUI integration

After Task 2:

1. `python scripts\make_test_db.py --scenario populate_real_members --use`
2. Launch the GUI (`.venv\Scripts\python.exe gui.py`).
3. Select "Entire Plan: HOF", click Generate.
4. Expect: many workbooks written (most members), some failure rows in the summary across all three eligibility reasons. The exact count depends on how many HOF members are in real Contacts.
