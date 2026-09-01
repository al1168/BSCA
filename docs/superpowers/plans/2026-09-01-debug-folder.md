# Debug Folder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Debug CSVs are written into a flat `Debug <YYYY-MM>` subfolder of the run's output directory in every mode (GUI all/single/list and CLI).

**Architecture:** One new helper `debug_subdir(year, month)` beside `debug_filename` in `new_monthly_schedule.py`; the CLI `--debug` branch and the GUI worker's debug branch both join it onto their output dir and `makedirs` it before writing. Nothing else moves.

**Tech Stack:** Python 3.11, pytest. Spec: `docs/superpowers/specs/2026-09-01-debug-folder-design.md`.

---

### Task 1: `debug_subdir` helper + CLI + worker

**Files:**
- Modify: `new_monthly_schedule.py` (helper near line 71, `--debug` branch near line 477)
- Modify: `gui/worker.py` (debug branch near line 362)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

1a. In `tests/test_cli.py`, next to `test_debug_filename_without_range` (~line 571) add:

```python
def test_debug_subdir():
    assert cli.debug_subdir(2026, 5) == "Debug 2026-05"
```

1b. In `test_debug_flag_writes_per_member_debug_csvs` (~line 718), the
debug files now live in a `Debug 2026-05` folder beside the plan
folder's schedules; replace the body after `sub = tmp_path / "HOF_2026-05"` with:

```python
    # No combined file.
    assert not (sub / "Debug_2026-05.csv").exists()
    # Debug CSVs live in their own flat folder inside the run's
    # output dir, not next to the timesheets.
    debug_dir = sub / "Debug 2026-05"
    assert not list(sub.glob("Debug_*.csv"))
    for cid in ("24010", "24011"):
        path = debug_dir / f"Debug_{cid}_2026-05.csv"
        assert path.exists()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == (
            "center_id,name,date,day,scheduled,reason,reason_detail,"
            "availability,availability_source,absent,auth_days,"
            "placement_window,max_length,band"
        )
        # Every calendar day of May 2026 gets a row.
        assert len(lines) - 1 == 31
        ids = {line.split(",", 1)[0] for line in lines[1:]}
        assert ids == {cid}
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_cli.py -k "debug_subdir or debug_flag_writes" -v`
Expected: FAIL — `debug_subdir` doesn't exist; files are still next to the timesheets.

- [ ] **Step 3: Implement**

3a. In `new_monthly_schedule.py`, after `debug_filename` (~line 76) add:

```python
def debug_subdir(year, month):
    """Subfolder (under the run's output dir) holding every debug CSV,
    so schedules, activity logs, and debug files each get their own
    folder. Naming matches the activity logs' 'Activity Logs YYYY-MM'
    style."""
    return f"Debug {year:04d}-{month:02d}"
```

3b. In the CLI `--debug` branch (~line 477) replace the path join:

```python
            debug_dir = os.path.join(
                out_dir, debug_subdir(args.year, args.month)
            )
            os.makedirs(debug_dir, exist_ok=True)
            debug_path = os.path.join(
                debug_dir,
                debug_filename(
                    member["center_id"], args.year, args.month,
                    args.start_day, args.end_day,
                ),
            )
```

3c. In `gui/worker.py`: add `debug_subdir` to the existing
`new_monthly_schedule` import block (~line 40), and in the debug
branch (~line 369) replace the path join:

```python
                    debug_dir = os.path.join(
                        self.out_dir,
                        debug_subdir(self.year, self.month),
                    )
                    os.makedirs(debug_dir, exist_ok=True)
                    debug_path = os.path.join(
                        debug_dir,
                        debug_filename(
                            member["center_id"], self.year, self.month,
                            self.start_day, self.end_day,
                        ),
                    )
```

(Note: the GUI uses `self.out_dir`, not `member_out_dir`, so in
All-Members mode the Debug folder sits beside the plan folders and
`Activity Logs <YYYY-MM>`, exactly like the spec's tree.)

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest`
Expected: PASS (except the pre-existing unrelated `test_smoke.py::test_one_off_conflict_writes_skipped_csv` Access-DB failure).

- [ ] **Step 5: Commit**

```bash
git add new_monthly_schedule.py gui/worker.py tests/test_cli.py
git commit -m "feat(debug): write debug CSVs into their own Debug folder"
```
