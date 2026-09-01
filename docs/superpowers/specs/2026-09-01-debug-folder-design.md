# Debug Files in a Separate Folder

Date: 2026-09-01
Status: Approved

## Problem

Debug CSVs are written next to the timesheets (`member_out_dir`), so a
debug run mixes `Debug_*.csv` files in with the schedules. Activity
logs already have their own `Activity Logs <YYYY-MM>` folder in
All-Members runs; the user wants schedules, activity logs, and debug
files each in their own folder.

## Decision

Debug CSVs are written into a **flat `Debug <YYYY-MM>` subfolder**
(naming style matches "Activity Logs 2026-09"; no per-plan subfolders
— user's choice) of the run's output directory, in every mode:

- **GUI All-Members:** `<out_dir>/Debug <YYYY-MM>/Debug_<id>_....csv`,
  beside the timesheet folders and `Activity Logs <YYYY-MM>/`.
- **GUI single/list:** `<out_dir>/Debug <YYYY-MM>/`, beside the
  schedule files.
- **CLI:** `<resolved out_dir>/Debug <YYYY-MM>/` (in plan mode this
  nests inside the `<PLAN>_<YYYY-MM>` folder the CLI already uses).

A new helper `debug_subdir(year, month)` lives next to
`debug_filename` in `new_monthly_schedule.py`; both the GUI worker and
the CLI build the path from it. The folder is created with
`os.makedirs(..., exist_ok=True)` right before writing.

## Unchanged

- Debug file names, CSV columns and content.
- Timesheet, activity log, billing, and skipped-members locations.
- The `worker.wrote_debug_csv` log line (still shows the file name).

## Testing

- Unit test for `debug_subdir`.
- `test_cli`: `--debug` writes into `<out_dir>/Debug 2026-05/`.
- `test_schedule_worker`: worker debug files land in the Debug folder
  (update any location assertions).
