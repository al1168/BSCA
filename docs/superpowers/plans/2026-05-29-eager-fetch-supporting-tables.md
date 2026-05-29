# Eager-Fetch Supporting Tables — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut All-Members and Entire-Plan wall-clock by ~95% by replacing 1,808 per-member ODBC connections with 4 unfiltered queries that build in-memory `{center_id: [rows]}` indexes the worker reads from.

**Architecture:** Add four new `get_all_<table>` functions in `monthly_schedule/db.py` that each open one connection, run one unfiltered SELECT, group rows by `Center ID` into a dict, and return it. The worker calls all four once before the per-member loop, then builds `MemberContext` from dict lookups instead of fresh ODBC round-trips. Single-member fetchers stay in place untouched (the CLI and the single/multiple GUI modes keep using them).

**Tech Stack:** Python 3.13, pyodbc, Microsoft Access ODBC, pytest.

**Spec:** [docs/performance/2026-05-29-all-members-baseline.md](../../performance/2026-05-29-all-members-baseline.md) (the performance report is the spec for this change — the "Recommended optimizations" section maps directly to the tasks below).

---

## File Inventory

| File | Action | Responsibility |
| --- | --- | --- |
| `monthly_schedule/db.py` | Modify | Add 4 `ALL_*_QUERY` constants, a `_fetch_all_unfiltered` helper, and 4 new `get_all_<table>(db_path)` functions that return `{center_id: [rows]}` dicts. |
| `tests/test_db.py` | Modify | Add tests for the 4 new queries (column assertions, no WHERE clause) and the 4 missing-DB FileNotFoundError contracts. |
| `gui/worker.py` | Modify | Import the 4 new fetchers. Eager-fetch once after the member dispatch and before the per-member loop. Inside the loop, build `MemberContext` from the dicts (dict-lookup) instead of from per-member ODBC calls. |

No new files. No deletions. Single-member fetchers (`get_enrollments`, `get_authorizations`, `get_absences`, `get_availability`) stay in place — the CLI and the single/multiple GUI modes still use them.

---

## Task 1: Add the four `get_all_<table>` functions + tests

**Files:**
- Modify: `monthly_schedule/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_all_enrollments_query_columns_and_no_filter():
    from monthly_schedule.db import ALL_ENROLLMENTS_QUERY
    for col in ("[ID]", "[Center ID]", "[start_date]", "[end_date]"):
        assert col in ALL_ENROLLMENTS_QUERY
    assert "FROM [Enrollment]" in ALL_ENROLLMENTS_QUERY
    assert "WHERE" not in ALL_ENROLLMENTS_QUERY


def test_all_authorizations_query_columns_and_no_filter():
    from monthly_schedule.db import ALL_AUTHORIZATIONS_QUERY
    for col in ("[ID]", "[Center ID]", "[auth_start]", "[auth_end]",
                "[effective_start]", "[effective_end]", "[auth_days]"):
        assert col in ALL_AUTHORIZATIONS_QUERY
    assert "FROM [Authorization]" in ALL_AUTHORIZATIONS_QUERY
    assert "WHERE" not in ALL_AUTHORIZATIONS_QUERY


def test_all_absences_query_columns_and_no_filter():
    from monthly_schedule.db import ALL_ABSENCES_QUERY
    for col in ("[ID]", "[Center ID]", "[Leave Type]",
                "[Start_Date]", "[End_Date]"):
        assert col in ALL_ABSENCES_QUERY
    assert "FROM [Absences]" in ALL_ABSENCES_QUERY
    assert "WHERE" not in ALL_ABSENCES_QUERY


def test_all_availability_query_columns_and_no_filter():
    from monthly_schedule.db import ALL_AVAILABILITY_QUERY
    for col in ("[ID]", "[Center ID]", "[effective_start_date]",
                "[effective_end_date]", "[Day Of Week]",
                "[avail_start]", "[avail_end]"):
        assert col in ALL_AVAILABILITY_QUERY
    assert "FROM [Availability]" in ALL_AVAILABILITY_QUERY
    assert "WHERE" not in ALL_AVAILABILITY_QUERY


def test_get_all_enrollments_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_all_enrollments
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_all_enrollments(str(missing))


def test_get_all_authorizations_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_all_authorizations
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_all_authorizations(str(missing))


def test_get_all_absences_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_all_absences
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_all_absences(str(missing))


def test_get_all_availability_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_all_availability
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_all_availability(str(missing))
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
.venv\Scripts\pytest tests/test_db.py -v -k "all_enrollments or all_authorizations or all_absences or all_availability or get_all_enrollments or get_all_authorizations or get_all_absences or get_all_availability"
```

Expected: 8 failures, all importing names that don't exist yet.

- [ ] **Step 3: Add a shared `_fetch_all_unfiltered` helper**

Find `_fetch_all` in `monthly_schedule/db.py`. Add this new helper directly above it (or below — doesn't matter, just in the same module):

```python
def _fetch_all_unfiltered(query: str, db_path: str, mapper):
    """Open one connection, run an unfiltered SELECT, map each row.
    Used by the four `get_all_<table>` batch fetchers so a whole-table
    load is one ODBC round-trip instead of N."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    import pyodbc

    try:
        conn = pyodbc.connect(build_connection_string(db_path))
    except pyodbc.Error as exc:
        raise RuntimeError(
            "Could not open the Access database. Verify the Microsoft "
            "Access ODBC driver is installed and its bitness matches "
            "this Python interpreter (spec section 8). "
            f"Original error: {exc}"
        )
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        return [mapper(row) for row in cursor.fetchall() if row[1] is not None]
    finally:
        conn.close()
```

Note: `row[1]` is the `Center ID` column in every supporting-table SELECT (after `[ID]` at position 0). NULL Center IDs are skipped — they can't be joined back to a Contacts row anyway.

- [ ] **Step 4: Add the four query constants + four fetcher functions**

Append to `monthly_schedule/db.py` (after the existing supporting-table single-member fetchers):

```python
ALL_ENROLLMENTS_QUERY = (
    "SELECT [ID], [Center ID], [start_date], [end_date] "
    "FROM [Enrollment]"
)


def get_all_enrollments(db_path: str) -> dict:
    """Return {center_id: [enrollment dicts]} for every Enrollment row.
    One ODBC round-trip vs N when used by the batch worker modes."""
    rows = _fetch_all_unfiltered(ALL_ENROLLMENTS_QUERY, db_path, map_enrollment_row)
    return _index_by_center_id(rows)


ALL_AUTHORIZATIONS_QUERY = (
    "SELECT [ID], [Center ID], [auth_start], [auth_end], "
    "[effective_start], [effective_end], [auth_days] "
    "FROM [Authorization]"
)


def get_all_authorizations(db_path: str) -> dict:
    """Return {center_id: [authorization dicts]} for every Authorization row."""
    rows = _fetch_all_unfiltered(ALL_AUTHORIZATIONS_QUERY, db_path,
                                  map_authorization_row)
    return _index_by_center_id(rows)


ALL_ABSENCES_QUERY = (
    "SELECT [ID], [Center ID], [Leave Type], [Start_Date], [End_Date] "
    "FROM [Absences]"
)


def get_all_absences(db_path: str) -> dict:
    """Return {center_id: [absence dicts]} for every Absences row."""
    rows = _fetch_all_unfiltered(ALL_ABSENCES_QUERY, db_path, map_absence_row)
    return _index_by_center_id(rows)


ALL_AVAILABILITY_QUERY = (
    "SELECT [ID], [Center ID], [effective_start_date], "
    "[effective_end_date], [Day Of Week], [avail_start], [avail_end] "
    "FROM [Availability]"
)


def get_all_availability(db_path: str) -> dict:
    """Return {center_id: [availability dicts]} for every Availability row."""
    rows = _fetch_all_unfiltered(ALL_AVAILABILITY_QUERY, db_path,
                                  map_availability_row)
    return _index_by_center_id(rows)


def _index_by_center_id(rows):
    """Group a flat list of row-dicts into {center_id: [rows]}."""
    out: dict[int, list] = {}
    for row in rows:
        out.setdefault(row["center_id"], []).append(row)
    return out
```

- [ ] **Step 5: Run the targeted tests to verify they pass**

```powershell
.venv\Scripts\pytest tests/test_db.py -v -k "all_enrollments or all_authorizations or all_absences or all_availability or get_all_enrollments or get_all_authorizations or get_all_absences or get_all_availability"
```

Expected: 8 passes.

- [ ] **Step 6: Run the full suite as a regression check**

```powershell
.venv\Scripts\pytest -v
```

Expected: all tests pass (≥ 168 with the 8 new ones).

- [ ] **Step 7: Verify against the live test DB**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python.exe -c "from monthly_schedule.db import get_all_enrollments, get_all_authorizations, get_all_absences, get_all_availability; import time; db=r'test_dbs\populate_real_members.accdb'; t0=time.perf_counter(); e=get_all_enrollments(db); a=get_all_authorizations(db); ab=get_all_absences(db); av=get_all_availability(db); dt=time.perf_counter()-t0; print(f'fetched 4 indexes in {dt:.2f}s — keys: enrollments={len(e)} authorizations={len(a)} absences={len(ab)} availability={len(av)}')"
```

Expected: prints something like `fetched 4 indexes in 1.8s — keys: enrollments=437 authorizations=437 absences=15 availability=2260`. Specifically:
- Total wall-clock: ~1.5–2.5 s (was ~480 s per pass under the old per-member pattern).
- Key counts reflect distinct Center IDs that appear in each table.

- [ ] **Step 8: Commit**

```bash
git add monthly_schedule/db.py tests/test_db.py
git commit -m "feat(db): add eager get_all_<table> fetchers indexed by Center ID

Four new functions load each supporting table in one ODBC round-trip
and return a {center_id: [rows]} dict. Used by the worker's batch
modes (next task) to replace 1,808 per-member connections with 4.
Single-member fetchers stay in place for the CLI and the single/
multiple GUI modes."
```

---

## Task 2: Refactor the worker to eager-fetch before the loop

**Files:**
- Modify: `gui/worker.py`

After this task, the All Members run that took ~8 minutes drops to ~30 seconds.

- [ ] **Step 1: Update the imports**

Find the existing `from monthly_schedule.db import (...)` block in `gui/worker.py` and add the four new functions. The block becomes:

```python
from monthly_schedule.db import (
    get_member, get_members_by_plan,
    get_enrollments, get_authorizations, get_absences, get_availability,
    get_all_members,
    get_all_enrollments, get_all_authorizations,
    get_all_absences, get_all_availability,
)
```

- [ ] **Step 2: Eager-fetch the four indexes once, before the per-member loop**

Find this block in `gui/worker.py` (in `_run_inner`, right before `for i, member in enumerate(members):`):

```python
        total = len(members) + len(failures)
        success = 0

        for i, member in enumerate(members):
```

Replace with:

```python
        total = len(members) + len(failures)
        success = 0

        # Eager-fetch all four supporting tables once and index by
        # center_id. Replaces 4×N ODBC connections (the per-member
        # pattern) with 4 — see docs/performance/2026-05-29-all-members-
        # baseline.md for why this matters.
        enroll_idx = get_all_enrollments(self.db_path)
        auth_idx = get_all_authorizations(self.db_path)
        absence_idx = get_all_absences(self.db_path)
        avail_idx = get_all_availability(self.db_path)

        for i, member in enumerate(members):
```

- [ ] **Step 3: Build `MemberContext` from the indexes instead of from per-member ODBC calls**

Find this block (the start of the loop body):

```python
        for i, member in enumerate(members):
            try:
                ctx = MemberContext(
                    enrollments=get_enrollments(member["center_id"], self.db_path),
                    authorizations=get_authorizations(member["center_id"], self.db_path),
                    absences=get_absences(member["center_id"], self.db_path),
                    availabilities=get_availability(member["center_id"], self.db_path),
                )
```

Replace with:

```python
        for i, member in enumerate(members):
            try:
                cid = member["center_id"]
                ctx = MemberContext(
                    enrollments=enroll_idx.get(cid, []),
                    authorizations=auth_idx.get(cid, []),
                    absences=absence_idx.get(cid, []),
                    availabilities=avail_idx.get(cid, []),
                )
```

- [ ] **Step 4: Run the full suite as a regression check**

```powershell
.venv\Scripts\pytest -v
```

Expected: all tests pass. The existing tests don't exercise the worker loop directly (they mock at the `new_monthly_schedule.cli` import boundary), so this refactor doesn't break anything.

- [ ] **Step 5: Verify the worker imports cleanly**

```powershell
.venv\Scripts\python.exe -c "from PyQt6.QtWidgets import QApplication; import sys; app = QApplication(sys.argv); from gui.worker import ScheduleWorker; print('OK')"
```

Expected: `OK`.

- [ ] **Step 6: Smoke-test the new path end-to-end against populate_real_members**

This step uses the existing `_diag_gui_all.py` from earlier (it programmatically drives the All-mode worker without needing a human to click). Run it and time the result:

```powershell
$env:PYTHONIOENCODING="utf-8"; Measure-Command { .venv\Scripts\python.exe _diag_gui_all.py 2>&1 | Out-Null }
```

Expected:
- `TotalSeconds` ≈ **30 s or less** for the full 452-member run (was ~500 s before this change).
- Reading the `success: True/False` payload from the diag output should show ~407 successes and ~45 eligibility failures, same as the prior baseline.

If the wall-clock is still > 60 s, something is wrong — re-check that the eager-fetch block actually replaced the per-member calls (Step 2 + Step 3 both needed).

- [ ] **Step 7: Commit**

```bash
git add gui/worker.py
git commit -m "perf(worker): eager-fetch supporting tables to cut wall-clock ~95%

Replace 1,808 per-member ODBC round-trips (4 supporting-table queries
× 452 members) with 4 whole-table fetches that build {center_id:
[rows]} dicts. The per-member loop now reads MemberContext from
memory instead of opening a fresh Access connection 4 times per
member.

Measured impact at 452 members on the populate_real_members test DB:
~500 s → ~25 s. Background in docs/performance/2026-05-29-all-
members-baseline.md."
```

---

## Self-Review Checklist (for the implementer)

Before declaring complete:

- [ ] `.venv\Scripts\pytest -v` is green (168+ tests).
- [ ] `_diag_gui_all.py` finishes in under 60 s for the full 452-member run.
- [ ] The final payload shows 407 successes / 45 eligibility failures (same shape as before the optimization).
- [ ] The worker loop no longer calls `get_enrollments`/`get_authorizations`/`get_absences`/`get_availability` (the single-member fetchers) — grep `gui/worker.py` to confirm.
- [ ] Single-member and multiple-member GUI modes still work: launch the GUI, pick "Single Member", enter a valid Center ID, generate. (No change expected — just a sanity check that the eager pre-fetch doesn't break those modes.)
- [ ] No code outside `monthly_schedule/db.py`, `tests/test_db.py`, and `gui/worker.py` was modified.

## Out of scope (deliberately deferred)

- **CLI (`new_monthly_schedule.py`)** — `main()` still uses the per-member fetchers. Cleanest follow-up if plan-mode CLI runs become a pain point.
- **Workbook write optimization** — once this lands, `workbook.write` becomes the dominant cost (~10 s for 407 workbooks). See the performance report's "Recommended optimizations" section for the next two steps (write-only openpyxl, or switching to XlsxWriter).
- **Single-member fetcher cleanup** — the `_fetch_all` helper and per-member fetchers stay around because the CLI still uses them. They can be retired in a follow-up if/when the CLI also migrates.
