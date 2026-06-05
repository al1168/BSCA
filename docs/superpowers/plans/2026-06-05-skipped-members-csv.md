# Skipped-Members CSV Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing `one_off_conflicts_<date>.csv` (which captures one failure stage) with a broader `skipped_members_<date>.csv` that records every skipped member per run — in both the GUI and the CLI.

**Architecture:** One small refactor in `new_monthly_schedule.py` (rename `write_one_off_conflict_csv` → `write_skipped_members_csv`, drop the stage filter, change the filename). All call sites and i18n strings follow. The Failure data model, the on-screen failure list, the preview-mode guards, and the GUI multi-plan roll-up location stay exactly as today.

**Tech Stack:** Python 3.11, PyQt6, pytest. Existing patterns: `csv.writer` to UTF-8 file, `Failure = namedtuple("Failure", "center_id name stage reason day")`, `_date.today()` defaulting via a `today=None` parameter for test-injectable date.

**Spec:** [docs/superpowers/specs/2026-06-05-skipped-members-csv-design.md](../specs/2026-06-05-skipped-members-csv-design.md)

---

## File Map

- `new_monthly_schedule.py` — Rename + repurpose the CSV writer. Update `main()`'s call site and stderr message.
- `gui/worker.py` — Update import + call site; update the multi-line comment and emitted log-line key.
- `gui/i18n.py` — Drop `worker.wrote_conflict_csv`, add `worker.wrote_skipped_csv` in both `en` and `zh`.
- `tests/test_cli.py` — Replace the three `test_write_one_off_conflict_csv_*` tests with four updated tests against the new function.
- `tests/test_smoke.py` — Update the end-to-end test to look for the new CSV name.

Task ordering: rename + new tests first (Task 1), then propagate through GUI + i18n (Tasks 2-3), then the smoke test update (Task 4). Each task is one logical commit; the repo runs at every commit because each call-site update closes its own loop within the task.

**Wait — Task 2 (gui/worker.py) must come immediately after Task 1, because Task 1 renames the function and removes the old name. Between Task 1's commit and Task 2's commit, the GUI would fail to import (`gui/worker.py` imports `write_one_off_conflict_csv`). Combine into a single task — Task 1 covers prod-code rename + tests; Task 2 covers GUI worker + i18n in one shot.** Task ordering below reflects this.

---

## Task 1: Rename the writer in `new_monthly_schedule.py` and update tests

**Files:**
- Modify: `new_monthly_schedule.py:86-106, 266-268`
- Modify: `tests/test_cli.py:417-475` (the existing `test_write_one_off_conflict_csv_*` block)

- [ ] **Step 1: Replace the writer function**

In [new_monthly_schedule.py](../../../new_monthly_schedule.py), find:

```python
def write_one_off_conflict_csv(failures, out_dir, today=None):
    """If any failures carry stage='one_off_conflict', write
    `one_off_conflicts_<YYYY-MM-DD>.csv` into `out_dir` with one row
    per conflict. Return the path written, or None when there are no
    conflict failures (the file is not created in that case)."""
    conflict_failures = [f for f in failures if f.stage == "one_off_conflict"]
    if not conflict_failures:
        return None
    today = today or _date.today()
    path = os.path.join(out_dir, f"one_off_conflicts_{today.isoformat()}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["center_id", "name", "date", "reason"])
        for f in conflict_failures:
            writer.writerow([
                f.center_id,
                f.name,
                f.day.isoformat() if f.day else "",
                f.reason,
            ])
    return path
```

Replace with:

```python
def write_skipped_members_csv(failures, out_dir, today=None):
    """If `failures` is non-empty, write `skipped_members_<YYYY-MM-DD>.csv`
    into `out_dir` with one row per skipped member. Return the path
    written, or None when `failures` is empty (file not created)."""
    if not failures:
        return None
    today = today or _date.today()
    path = os.path.join(out_dir, f"skipped_members_{today.isoformat()}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["center_id", "name", "stage", "reason", "day"])
        for f in failures:
            writer.writerow([
                f.center_id,
                f.name,
                f.stage,
                f.reason,
                f.day.isoformat() if f.day else "",
            ])
    return path
```

Note three changes from the original: function/filename rename, drop the conflict-only filter, and the header is `["center_id", "name", "stage", "reason", "day"]` (added `stage` column and renamed `date` → `day` to match the `Failure` field name).

- [ ] **Step 2: Update `main()`'s call site and stderr message**

In `new_monthly_schedule.py`, find:

```python
    save_cache(args.geo_cache, cache)
    if not args.preview_data:
        conflict_csv = write_one_off_conflict_csv(failures, out_dir)
        if conflict_csv is not None:
            print(f"Wrote conflict report: {conflict_csv}", file=sys.stderr)
```

Replace with:

```python
    save_cache(args.geo_cache, cache)
    if not args.preview_data:
        skipped_csv = write_skipped_members_csv(failures, out_dir)
        if skipped_csv is not None:
            print(f"Wrote skipped members report: {skipped_csv}", file=sys.stderr)
```

- [ ] **Step 3: Replace the three existing CLI tests**

In [tests/test_cli.py](../../../tests/test_cli.py), find the block starting at line 416 (the comment header `# write_one_off_conflict_csv`) and ending after `test_write_one_off_conflict_csv_multiple_conflicts_preserves_order`. Replace the entire block with:

```python
# ---------------------------------------------------------------------------
# write_skipped_members_csv
# ---------------------------------------------------------------------------

from new_monthly_schedule import write_skipped_members_csv, Failure


def test_write_skipped_members_csv_empty_returns_none(tmp_path):
    """Empty failures list returns None and writes nothing."""
    result = write_skipped_members_csv(
        [], str(tmp_path), today=date(2026, 6, 4)
    )
    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_write_skipped_members_csv_filename_uses_today(tmp_path):
    """The returned path is `skipped_members_<today>.csv` in out_dir."""
    failures = [
        Failure(24010, "Cheng, Lizhu", "lookup", "not found", None),
    ]
    result = write_skipped_members_csv(
        failures, str(tmp_path), today=date(2026, 6, 4)
    )
    expected_path = tmp_path / "skipped_members_2026-06-04.csv"
    assert result == str(expected_path)
    assert expected_path.exists()


def test_write_skipped_members_csv_includes_all_stages(tmp_path):
    """All failure stages appear in the CSV. The `day` column is the ISO
    date only for one_off_conflict rows and empty for everything else."""
    failures = [
        Failure(24010, "Cheng, Lizhu", "lookup", "not found in database", None),
        Failure(24011, "Smith, John", "eligibility", "not enrolled", None),
        Failure(24012, "Jones, Mary", "geocode", "ZERO_RESULTS for 'x'", None),
        Failure(24013, "Park, Eun", "one_off_conflict",
                "one-off on auth day", date(2026, 6, 5)),
    ]
    result = write_skipped_members_csv(
        failures, str(tmp_path), today=date(2026, 6, 4)
    )
    expected_path = tmp_path / "skipped_members_2026-06-04.csv"
    assert result == str(expected_path)
    content = expected_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[0] == "center_id,name,stage,reason,day"
    assert len(lines) == 5  # header + 4 failures
    assert lines[1] == '24010,"Cheng, Lizhu",lookup,not found in database,'
    assert lines[2] == '24011,"Smith, John",eligibility,not enrolled,'
    assert lines[3] == '24012,"Jones, Mary",geocode,ZERO_RESULTS for \'x\','
    assert lines[4] == (
        '24013,"Park, Eun",one_off_conflict,one-off on auth day,2026-06-05'
    )


def test_write_skipped_members_csv_preserves_input_order(tmp_path):
    """Multiple failures appear in input order."""
    failures = [
        Failure(24010, "Cheng, Lizhu", "eligibility", "A", None),
        Failure(24011, "Smith, John", "lookup", "B", None),
        Failure(24012, "Jones, Mary", "geocode", "C", None),
    ]
    result = write_skipped_members_csv(
        failures, str(tmp_path), today=date(2026, 6, 4)
    )
    content = result and open(result, encoding="utf-8").read()
    lines = content.splitlines()
    assert [l.split(",", 1)[0] for l in lines[1:]] == ["24010", "24011", "24012"]
```

Notes for the engineer:

- `from datetime import date` is already imported at the top of `tests/test_cli.py` (line 3) — don't duplicate.
- `cli.Failure` and `Failure` (imported above) are the same namedtuple. The existing tests use both forms inconsistently; the new tests use the `from new_monthly_schedule import Failure` form for clarity.
- The fourth test uses `open(...)` rather than `read_text()` to keep the line short and demonstrate both patterns coexist; either is fine if you prefer to harmonize.

- [ ] **Step 4: Run the new tests — confirm they pass**

Run: `pytest tests/test_cli.py -v -k "skipped_members"`
Expected: 4 passing tests.

- [ ] **Step 5: Run the full CLI test suite to confirm no regressions**

Run: `pytest tests/test_cli.py -q`
Expected: passing count goes up by **+1** compared to before this task (3 old `test_write_one_off_conflict_csv_*` tests removed, 4 new `test_write_skipped_members_csv_*` tests added). No failures.

If you want a concrete number to compare against, run `git stash && pytest tests/test_cli.py -q` first to capture the baseline, then `git stash pop` and re-run after the edits.

If the run reports a CLI test failure that isn't one of the new ones, investigate before continuing — Task 1 only touched the conflict-CSV writer and its tests.

- [ ] **Step 6: Sanity grep**

Run: `grep -rn "write_one_off_conflict_csv\|one_off_conflicts_" --include="*.py" .`

Expected: zero matches in `*.py` files. (Docs may still reference the old name — that's historical and fine. The `gui/worker.py` reference is still present at this point but Task 2 fixes it next.)

**Important: do NOT commit Task 1 alone.** `gui/worker.py` still imports `write_one_off_conflict_csv`. Committing now leaves the GUI module unimportable. The grep above will still find the worker reference. Task 2 (next) is paired with Task 1 — both go into the same commit. Skip the commit at this step.

---

## Task 2: Update `gui/worker.py` and `gui/i18n.py`; commit Tasks 1+2 together

**Files:**
- Modify: `gui/worker.py:15, 222-231`
- Modify: `gui/i18n.py:109, 251`

- [ ] **Step 1: Update the worker import**

In [gui/worker.py](../../../gui/worker.py), find:

```python
from new_monthly_schedule import (
    Failure,
    REASON_NOT_FOUND,
    parse_center_ids,
    process_member,
    resolve_output_dir,
    schedule_filename,
    write_one_off_conflict_csv,
)
```

Replace `write_one_off_conflict_csv` with `write_skipped_members_csv`:

```python
from new_monthly_schedule import (
    Failure,
    REASON_NOT_FOUND,
    parse_center_ids,
    process_member,
    resolve_output_dir,
    schedule_filename,
    write_skipped_members_csv,
)
```

- [ ] **Step 2: Update the call site and emitted log key**

In `gui/worker.py`, find the block at the end of `_run_inner`:

```python
        if not self.preview:
            # Conflict CSV lives at the base output dir even in "all" mode —
            # conflicts can span multiple plans, so a single roll-up file
            # is more useful than per-plan duplicates.
            csv_path = write_one_off_conflict_csv(failures, self.out_dir)
            if csv_path is not None:
                self.log_line.emit(
                    "worker.wrote_conflict_csv",
                    {"filename": os.path.basename(csv_path)},
                )
```

Replace with:

```python
        if not self.preview:
            # Skipped-members CSV lives at the base output dir even in "all"
            # mode — skips can span multiple plans, so a single roll-up file
            # is more useful than per-plan duplicates.
            csv_path = write_skipped_members_csv(failures, self.out_dir)
            if csv_path is not None:
                self.log_line.emit(
                    "worker.wrote_skipped_csv",
                    {"filename": os.path.basename(csv_path)},
                )
```

- [ ] **Step 3: Update the English i18n string**

In [gui/i18n.py](../../../gui/i18n.py), in the `"en"` block, find:

```python
        "worker.wrote_conflict_csv": "Wrote conflict report: {filename}",
```

Replace with:

```python
        "worker.wrote_skipped_csv": "Wrote skipped members report: {filename}",
```

- [ ] **Step 4: Update the Chinese i18n string**

In `gui/i18n.py`, in the `"zh"` block, find:

```python
        "worker.wrote_conflict_csv": "已写入冲突报告: {filename}",
```

Replace with:

```python
        "worker.wrote_skipped_csv": "已写入跳过成员报告：{filename}",
```

Note: the new Chinese string uses a full-width colon `：` (consistent with sibling `settings.test.*` strings); the old one used an ASCII `:`. Both render in Chinese contexts, but full-width is the project convention.

- [ ] **Step 5: Run the i18n parity test**

Run: `pytest tests/test_i18n.py -v`
Expected: all pass. Critically `test_key_parity` must pass — both `en` and `zh` should have exactly one `worker.wrote_skipped_csv` key each and zero `worker.wrote_conflict_csv` keys.

- [ ] **Step 6: Sanity check — no orphan references**

Run: `grep -rn "write_one_off_conflict_csv\|wrote_conflict_csv\|one_off_conflicts_" --include="*.py" .`

Expected: only matches in `tests/test_smoke.py` (which Task 3 updates) plus no other `.py` files. If anything else turns up, fix it before committing.

- [ ] **Step 7: Import smoke test**

Run: `python -c "from gui.worker import ScheduleWorker; from new_monthly_schedule import write_skipped_members_csv; print('ok')"`
Expected: `ok` — confirms both modules import cleanly.

- [ ] **Step 8: Run the full test suite**

Run: `pytest -q`
Expected: same baseline as before (11 pre-existing pyodbc-related failures from backfill tests). Total passing test count is +1 from before Task 1 (3 old conflict-CSV tests removed, 4 new skipped-members tests added). No new failures.

If the smoke test (`tests/test_smoke.py::test_one_off_conflict_writes_conflict_csv`) is being run in your environment (i.e. the Access ODBC driver is present), it WILL fail because it still globs `one_off_conflicts_*.csv` and that file no longer exists. Task 3 fixes the smoke test. In the typical dev env (no Access driver), pytest skips it and you won't see this failure.

- [ ] **Step 9: Commit Tasks 1+2 together**

```bash
git add new_monthly_schedule.py gui/worker.py gui/i18n.py tests/test_cli.py
git commit -m "feat(csv): replace one_off_conflicts CSV with skipped_members CSV"
```

---

## Task 3: Update the smoke test

**Files:**
- Modify: `tests/test_smoke.py:33-100` (the `test_one_off_conflict_writes_conflict_csv` function)

- [ ] **Step 1: Read the current smoke test**

Open [tests/test_smoke.py](../../../tests/test_smoke.py) and locate `test_one_off_conflict_writes_conflict_csv`. The relevant lines are the function name (line 33), the docstring (lines 34-36), and the glob/assertions that reference `one_off_conflicts_*.csv` (around line 94).

- [ ] **Step 2: Rename the test function**

Rename `test_one_off_conflict_writes_conflict_csv` to `test_one_off_conflict_writes_skipped_csv`.

- [ ] **Step 3: Update the docstring**

Find:

```python
    """End-to-end: seed the one_off_conflict scenario, run the CLI,
    confirm `one_off_conflicts_<DATE>.csv` lands in the output dir
    with the expected single row."""
```

Replace with:

```python
    """End-to-end: seed the one_off_conflict scenario, run the CLI,
    confirm `skipped_members_<DATE>.csv` lands in the output dir
    with the conflict row recorded."""
```

- [ ] **Step 4: Update the CSV glob and surrounding messages**

In the same function, find:

```python
    csv_files = list(out_dir.glob("one_off_conflicts_*.csv"))
    assert len(csv_files) == 1, (
        f"Expected exactly one conflict CSV, got: {csv_files}\n"
        f"stderr: {result.stderr}"
    )
```

Replace with:

```python
    csv_files = list(out_dir.glob("skipped_members_*.csv"))
    assert len(csv_files) == 1, (
        f"Expected exactly one skipped-members CSV, got: {csv_files}\n"
        f"stderr: {result.stderr}"
    )
```

- [ ] **Step 5: Check the row-content assertions**

Read the rest of the test function (the assertions after the glob — typically checking the row count and content). The header is now `center_id,name,stage,reason,day` (5 columns) instead of the old `center_id,name,date,reason` (4 columns), and the conflict row now has `stage = "one_off_conflict"` in column 3 and the date in column 5 (instead of column 3 under the old layout).

If the test asserts row contents column-by-column or by splitting on commas, update the indices and expected values accordingly. If it asserts only "exactly one data row exists" without parsing columns, no further change is needed.

Either way, after editing, the test should still verify: (a) exactly one data row, (b) it corresponds to the seeded one_off_conflict member.

- [ ] **Step 6: Run the smoke test**

If you have the Access ODBC driver installed:

Run: `pytest tests/test_smoke.py -v`
Expected: `test_one_off_conflict_writes_skipped_csv` passes; `test_package_imports` passes.

If you don't have the Access driver, pytest will skip the end-to-end test — that's expected. Run anyway to confirm `test_package_imports` still passes and nothing else broke.

- [ ] **Step 7: Sanity grep**

Run: `grep -rn "one_off_conflicts_\|write_one_off_conflict_csv\|wrote_conflict_csv\|one_off_conflict_writes_conflict_csv" --include="*.py" .`

Expected: zero matches in `*.py` files.

- [ ] **Step 8: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test(smoke): expect skipped_members CSV instead of one_off_conflicts"
```

---

## Task 4: Manual verification

This task has no code changes — it's a manual sanity check that the user-visible behavior actually works.

- [ ] **Step 1: Confirm a clean tree on the feature branch**

Run: `git status --short`
Expected: only untracked files (backfill CSVs, build artifacts) — no staged or unstaged changes related to this feature.

- [ ] **Step 2: Rebuild the exe** (only if testing via the packaged build)

If verifying via the `.exe`:
```
rm -rf build/ && rm -f dist/MonthlyScheduleGenerator.exe
.venv/Scripts/pyinstaller.exe --noconfirm MonthlyScheduleGenerator.spec
```
Expected: `dist/MonthlyScheduleGenerator.exe` regenerated. Takes ~50 seconds.

If verifying via `python gui.py`, skip this step.

- [ ] **Step 3: Trigger a run that includes at least one skip**

Pick a member ID that's known to fail (e.g. one not enrolled in the target month), or run the "All Members" mode against a database that has at least one ineligible member. Hit Generate Schedule.

Expected:
- Run completes.
- GUI log includes a `Failures:` block with the skipped member(s).
- GUI log includes the line `Wrote skipped members report: skipped_members_<today>.csv` (or the Chinese equivalent if `language` is `zh`).

- [ ] **Step 4: Open the output folder and verify the CSV**

Click "Open Output Folder" in the GUI. Confirm `skipped_members_<today>.csv` is present alongside whatever schedule workbooks were produced (or alone, if no member succeeded). Open it in Excel.

Expected:
- 5 columns: `center_id`, `name`, `stage`, `reason`, `day`.
- One row per skipped member.
- `day` column is empty for non-conflict rows, ISO date (e.g. `2026-06-05`) for any `one_off_conflict` row.

- [ ] **Step 5: Run again with all members succeeding (no skips)**

Pick a member ID that's known to succeed. Hit Generate Schedule.

Expected:
- Schedule workbook produced.
- No `skipped_members_*.csv` is created (the existing CSV from Step 4 is left alone — it's from a previous run on the same day).
- GUI log does NOT contain the "Wrote skipped members report" line.

- [ ] **Step 6: Run with Preview Only checked**

Re-run with the Preview Only checkbox on, against a member set that includes a skip.

Expected:
- Preview output appears in the log.
- No files written to the output folder (preview mode skips both schedule writes AND the CSV write).

- [ ] **Step 7: No commit needed**

This task only confirms behavior. End of plan.

---

## Spec Coverage Verification

| Spec section | Task |
|---|---|
| Rename `write_one_off_conflict_csv` → `write_skipped_members_csv` | Task 1 (Step 1) |
| Drop the `stage == "one_off_conflict"` filter; write all failures | Task 1 (Step 1) |
| Filename `skipped_members_<YYYY-MM-DD>.csv`; today's date | Task 1 (Step 1) |
| Columns: `center_id, name, stage, reason, day` | Task 1 (Step 1) |
| `day` is ISO date for conflict rows, empty otherwise | Task 1 (Step 1, Step 3 test) |
| Empty failures → `None`, no file | Task 1 (Step 1, Step 3 test) |
| CLI `main()` call site + stderr message | Task 1 (Step 2) |
| `gui/worker.py` import + call site + comment | Task 2 (Steps 1-2) |
| `gui/worker.py` emits `worker.wrote_skipped_csv` log key | Task 2 (Step 2) |
| Drop `worker.wrote_conflict_csv` in en + zh | Task 2 (Steps 3-4) |
| Add `worker.wrote_skipped_csv` in en + zh | Task 2 (Steps 3-4) |
| Replace 3 CLI tests with 4 new tests | Task 1 (Step 3) |
| Update smoke test glob to `skipped_members_*.csv` | Task 3 (Step 4) |
| Preview-mode and "no skips" behaviors unchanged | Task 1 (Step 1 — `if not failures: return None`); Task 2 keeps `if not self.preview:` guard intact; Task 4 (Steps 5-6) verifies |
| Multi-plan roll-up location preserved | Task 2 (Step 2 — comment + same `out_dir` arg) |
