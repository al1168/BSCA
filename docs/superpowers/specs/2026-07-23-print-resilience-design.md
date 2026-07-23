# Print Resilience (Continue, Resume, Friendly Errors) — Design

**Date:** 2026-07-23
**Status:** Approved (user-confirmed after the 2026-07 paper-out incident)

## Problem

"Print All Schedules" drives Excel COM over each generated `.xlsx`.
Today the first `PrintOut()` failure aborts the whole batch (observed:
RICOH out of paper mid-run → Excel's misleading "No printers are
installed" → dialog, ~21% printed). Re-clicking reprints ALL files, so
already-printed schedules come out twice, and the error text gives a
non-technical user no idea what to do.

## Decisions (user-approved)

1. **Continue past per-file failures** and report them at the end —
   but stop after **3 consecutive failures** (printer clearly down;
   don't grind Excel errors for a hundred files). Untried files are
   reported as "not attempted".
2. **Session resume**: remember which files printed successfully this
   app session. Re-clicking Print offers "print remaining N" vs
   "print all". The record clears when a new generation run finishes
   (files rewritten → everything is unprinted again). Not persisted
   across app restarts (YAGNI — the fix-printer-and-retry flow happens
   within a session).
3. **Friendly error surface**: per-file failures go to the log
   (filename + raw error); the dialog shows a plain-language summary —
   printed/failed counts plus "printer may be out of paper or offline;
   fix it and click Print again, already-printed schedules are
   skipped." English + Chinese.

## Components

- `gui/printing.py` — `print_workbooks` returns
  `{"printed": [paths], "failed": [(path, err)], "not_attempted": [paths]}`
  instead of an int; per-file try/except; consecutive-failure breaker
  (default 3); `on_progress(i, total, path)` fires after every attempt
  (success or failure) so the progress bar always advances. New pure
  helper `partition_printed(paths, printed_ok)` →
  `(remaining, already)` by abspath membership.
- `gui/print_worker.py` — emits `finished(success, result_dict)` where
  `success = no failures and nothing skipped`; whole-batch exceptions
  (Excel missing) still emit `{"error": str}`.
- `gui/main_window.py` — `self._printed_ok: set[str]` (abspaths);
  updated from every finished payload; cleared when a generation run
  completes. `_print_schedules` partitions and asks: nothing printed
  yet → existing confirm; some printed → 3-button box (remaining /
  all / cancel); all printed → "print all again?" confirm.
  `_on_print_finished` logs per-file failures + summary, dialog shows
  the friendly summary.
- `gui/i18n.py` — new keys (en+zh): `print.confirm.reprint_all`,
  `print.confirm.remaining`, `print.btn.remaining`, `print.btn.all`,
  `print.file_failed`, `print.stopped_early`, `print.partial`.

## Error handling

- Excel/pywin32 unavailable: unchanged (RuntimeError → error dialog).
- A failure on file N never prevents file N+1 from being attempted
  (until the breaker trips).
- Progress bar reaches N-attempted, not total, when the breaker trips
  (visible signal that it stopped early, plus the log line).

## Testing

- `tests/test_printing.py`: continue-on-error (fail, then success);
  result dict shape; breaker trips after 3 consecutive failures and
  fills `not_attempted`; a success resets the consecutive counter;
  progress fires per attempt; workbook closed even when PrintOut
  raises; injected Excel never quit; `partition_printed` pure tests.
- `tests/test_print_worker.py`: payload shape for full success,
  partial failure (success=False), and whole-batch exception.
- i18n key parity (existing test enforces en/zh).
