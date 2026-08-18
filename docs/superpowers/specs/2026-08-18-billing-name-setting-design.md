# Billing File Name Setting

**Date:** 2026-08-18
**Status:** Approved

## Problem

The billing attendance workbook filename is hardcoded as
`<M>. <Month> <YYYY> Member Attendance-Bowery.xlsx`. The user wants to
control the trailing name from Settings, with the file named
`<M>. <Month> <YYYY> billing <name>.xlsx` (e.g.
`8. August 2026 billing Jane Doe.xlsx`).

## Design

### Settings dialog (`gui/settings_dialog.py`)

- New `QLineEdit` row "Billing file name" in the main form, below the
  geo-cache row. Present in both the normal Settings dialog and the
  first-run dialog.
- Stored in app settings under the key `billing_name` (string).
- Validation on Save (blocks the save with a warning `QMessageBox`):
  - Blank/whitespace-only name → required-name warning.
  - Name containing any Windows-forbidden filename character
    (`\ / : * ? " < > |`) → invalid-characters warning.
- The saved value is `.strip()`ed.

### Filename (`monthly_schedule/billing_workbook.py`)

- `billing_filename(year, month, name)` gains a required `name`
  parameter and returns
  `f"{month}. {calendar.month_name[month]} {year} billing {name}.xlsx"`.
- `save_billing_workbook(wb, out_dir, year, month, billing_name,
  on_fallback=None)` gains the `billing_name` parameter and passes it
  through. The existing locked-file fallback (`_1`..`_9` suffixes) is
  unchanged.

### Worker plumbing (`gui/worker.py`, `gui/main_window.py`)

- `ScheduleWorker.__init__` gains a `billing_name` argument, stored and
  passed to `save_billing_workbook` in the All-Members billing step.
- `MainWindow` passes `self._settings.get("billing_name", "")` when
  constructing the worker.

### Run guard (`gui/main_window.py`)

- Upgraded installs may have settings without `billing_name`. Before
  starting an **All Members** run, if the saved `billing_name` is
  blank, show the same style of blocking message as the missing
  Google-API-key check, telling the user to set the billing file name
  in Settings. Other run modes are unaffected (they don't produce the
  billing workbook).

### i18n (`gui/i18n.py`)

New keys, in both `en` and `zh`:

- `settings.billing_name_label` — form label.
- `settings.billing_name_missing.title` / `.body` — required warning.
- `settings.billing_name_invalid.title` / `.body` — forbidden-character
  warning.
- `run.billing_name_missing` (or matching existing missing-setting
  pattern) — run-guard message.

### Tests

- `tests/test_billing_workbook.py`: update `test_billing_filename` and
  the save/fallback tests for the new signature and
  `... billing <name>.xlsx` format.
- Settings-dialog validation: blank name blocks save; forbidden
  characters block save; valid name round-trips into the result dict.
- Worker test: billing workbook written with the configured name.
- i18n test: new keys exist in every language.

## Out of scope

- No change to timesheet/schedule filenames or output folders.
- No CLI flag — the CLI does not produce the billing workbook.
