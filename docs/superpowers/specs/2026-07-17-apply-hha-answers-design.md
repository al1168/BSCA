# Apply HHA Answers — Design

Status: Draft
Date: 2026-07-17

## 1. Goal

Take the human-reviewed HHA answers CSV (the `hhbackfill` file produced by
reviewing `hha_backfill_ambiguous_<date>.csv`) and narrow each listed member's
`Availability` windows so that no availability overlaps their home-care hours.
Delivered as a pure parsing/subtraction module, a CLI script, and a standalone
PyQt6 GUI (`dist/ApplyHHAAnswers.exe`) with a preview-then-apply flow.

## 2. Motivation

The first backfill (`backfill_availability_from_hha.py`) auto-applied only
unambiguous end-of-day constraints and emitted everything else to a CSV for
human review. That review is done: the CSV now has an `answer` column holding a
normalized schedule per member. This tool closes the loop by applying those
answers to the database. The operator is non-technical, hence the GUI.

## 3. Inputs

**Answers CSV** — columns `center_id, last_name, first_name, answer, raw_hha,
reason, attempted_parse` (UTF-8 with BOM). Only `center_id` and `answer` drive
writes; names are used in log/review output. Rows with a blank `answer` are
skipped and counted (currently 24109 and 2526600).

**Answer format** — pipe-separated groups of `days (start - end)`:

```
1.5 (8:30 AM - 5:30 PM) | 3.6 (12 PM - 5 PM) | 7 (12:30 PM - 2:30 PM)
```

- Days: dot-separated ints 1–7, ISO weekday (1=Mon … 7=Sun) — same convention
  as `Availability.[Day Of Week]`.
- Times: `H[:MM]` with AM/PM on each side. Whitespace is flexible; the ten
  hand-filled rows vary (`1 PM- 7 PM`, `8AM-12PM`, `(8 AM - 2 PM)| 6.7`).
- A group that does not match, a day outside 1–7, or a time block with
  start ≥ end makes the whole row a `parse_error` (review CSV, no writes for
  that member). No guessing.

**Database** — Access `.accdb` with `Availability` as used by
`monthly_schedule/db.py`. Only the currently-open row per (Center ID, Day Of
Week) — `effective_end_date IS NULL` — is read and written, matching the first
backfill.

## 4. Core rule — interval subtraction

For each (member, day): current open window `[a, b]`, care window `[s, e]`.
After the setup chain the typical open window is the seeded default
`08:00–13:00`.

| Overlap shape | Result | Review CSV? |
|---|---|---|
| None (`e ≤ a` or `s ≥ b`) | No change (counted `no_overlap`) | no |
| Covers the front (`s ≤ a < e < b`) | `avail_start = e` | no |
| Covers the back (`a < s < b ≤ e`) | `avail_end = s` | no |
| Strictly inside (`a < s`, `e < b`) | Two pieces remain; keep the **longer** (tie → morning piece) | yes, `split` |
| Covers everything (`s ≤ a`, `e ≥ b`) | **No write** — operator decides | yes, `blocked` |

Invariants:

- **Only narrow.** Every result is a subset of the existing window; the tool
  never widens and never deletes rows (a missing row means "no constraint" to
  the scheduler, so deletion would widen).
- Tiny leftover windows are written as-is; the scheduler already rejects days
  whose window is shorter than the session length.
- Multiple groups hitting the same day subtract sequentially against the
  running window.
- If no open row exists for a (member, day) named in an answer, subtraction
  runs against the default `08:00–13:00` and the result is INSERTed
  (`effective_start_date = today`, `effective_end_date = NULL`), mirroring the
  first backfill. Counted separately.
- A `center_id` absent from `Availability` **and** `Contacts` → review CSV
  `member_not_found`, no writes.
- Re-running is idempotent: subtracting the same window from an
  already-narrowed row is a no-op.

## 5. CLI script

```
python scripts/apply_hha_answers.py --csv <answers.csv> --db <path.accdb>
                                    [--csv-out DIR] [--dry-run] [--quiet]
```

- `main(argv) -> int` shape, same as sibling scripts (imported by the GUI, no
  subprocess).
- All DB writes in one transaction; `--dry-run` rolls back but still writes
  the review CSV and prints the summary.
- `--csv-out` defaults to the input CSV's directory.

**Review CSV** — `hha_answers_review_<YYYY-MM-DD>.csv`, one row per flagged
(member, day) or per flagged row:

| Column | Notes |
|---|---|
| `center_id`, `last_name`, `first_name` | from the answers CSV |
| `day` | 1–7, blank for row-level flags (`parse_error`, `member_not_found`) |
| `flag` | `split` \| `blocked` \| `parse_error` \| `member_not_found` |
| `hha_window` | e.g. `08:30-12:00` |
| `old_window` | e.g. `08:00-13:00` |
| `new_window` | e.g. `12:00-13:00`; blank when nothing was written |
| `note` | e.g. `kept longer piece; other piece was 08:00-08:30` |

**Stdout summary** (always printed): rows read / blank answers skipped /
rows applied / days updated / days inserted / days unchanged (no overlap) /
splits / blocked days / parse errors / members not found / review CSV path /
mode (APPLIED or DRY-RUN).

## 6. GUI — standalone `ApplyHHAAnswers.exe`

New top-level `apply_hha_gui/` mirroring `setup_gui/` in shape; entry point
`apply_hha.py`; PyInstaller spec `ApplyHHAAnswers.spec` (copy of
`BSCASetup.spec` with entry point and exe name changed). Three exes coexist in
`dist/`. English only, no persistent settings.

```
┌─────────────────────────────────────────────┐
│ Apply HHA Answers                           │
├─────────────────────────────────────────────┤
│ Answers CSV:  [path            ] [Browse…]  │
│ Database:     [path            ] [Browse…]  │
│                                             │
│ [ Preview (no changes) ]  [ Apply ]         │
│                                             │
│ ┌─────────────────────────────────────────┐ │
│ │ scrolling log (QPlainTextEdit)          │ │
│ └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

Widgets: two `QLineEdit` + Browse buttons (filters `*.csv` and
`*.accdb *.mdb`), `QPushButton` Preview, `QPushButton` Apply, log area.

**Flow:**

- Preview enabled only when both paths exist. Runs the script with
  `--dry-run` on a worker thread; log streams line-by-line.
- Apply enabled only after a successful preview **with the same two paths**;
  editing either path disables Apply until the next successful preview. What
  you apply is always what you just previewed.
- Apply first copies the DB to `<stem>.backup_<YYYY-MM-DD-HHMMSS><ext>` in the
  same folder (same convention as BSCASetup), then runs the script without
  `--dry-run`.

**Worker** — `apply_hha_gui/worker.py`, `ApplyHhaWorker(QThread)`:

```python
class ApplyHhaWorker(QThread):
    log_line = pyqtSignal(str)
    finished_run = pyqtSignal(bool, dict)   # (success, payload)

    def __init__(self, csv_path, db_path, mode, parent=None):
        # mode: "preview" | "apply"
```

- `preview`: `apply_hha_answers.main(["--csv", csv, "--db", db, "--dry-run"])`
  under `contextlib.redirect_stdout(LineBuffer(...))`.
- `apply`: backup first (failure → `finished_run(False, {"step": "backup"})`,
  script never runs), then same call without `--dry-run`; payload carries the
  backup path.
- `LineBuffer` is imported from `setup_gui/log_buffer.py` — reused, not
  duplicated. (Precedent kept `gui/` and `setup_gui/` fully separate, but a
  third copy of the same 30-line class tips the balance to importing;
  PyInstaller bundles it either way.)

**Error handling:** backup failure (e.g. DB open in Access) → warning dialog,
nothing ran; script non-zero return or exception → warning dialog naming the
backup file to restore; both buttons disabled while a worker is in flight.

## 7. File layout

```
monthly_schedule/
  hha_answer_parser.py        # pure: answer parsing + interval subtraction
scripts/
  apply_hha_answers.py        # CLI + DB writes + review CSV
apply_hha_gui/
  __init__.py
  main_window.py
  worker.py
apply_hha.py                  # entry point
ApplyHHAAnswers.spec
tests/
  test_hha_answer_parser.py
  test_apply_hha_answers.py   # script-level: CSV reading, review CSV, summary
  test_apply_hha_worker.py    # worker: argv shape, backup ordering, failures
```

## 8. Testing

- `test_hha_answer_parser.py` (TDD, cases from the real CSV):
  - Parsing: single group, multi-group, lenient spacing variants from the
    hand-filled rows, `12 PM` noon handling, blank answer, malformed group,
    day out of range, start ≥ end.
  - Subtraction: no overlap (after-close `5 PM - 9 PM` vs `08:00–13:00`),
    front overlap (`6 AM - 12 PM` → start pushed to 12:00), back overlap
    (`12 PM - 4 PM` → end pulled to 12:00), strict-inside split
    (`8:30 AM - 12 PM` → keeps `12:00–13:00`, flags), tie-break → morning,
    full cover (`6:30 AM - 1:30 PM` vs `08:00–13:00` → blocked, no write),
    sequential multi-group same-day, idempotency (subtract twice = once).
- `test_apply_hha_answers.py`: blank-answer skip, parse-error row isolation
  (bad row doesn't block others), review CSV contents, dry-run rollback
  (mocked cursor), summary counts, missing-member flag.
- `test_apply_hha_worker.py` (mirrors `test_setup_worker.py`, mocked script
  `main`): preview passes `--dry-run`, apply does not; backup happens before
  the script and only in apply mode; backup failure short-circuits; non-zero
  return and exception paths emit `finished_run(False, ...)`.
- Manual verification against the operator's test DB
  (`C:\Users\luald\Videos\members.accdb`): preview, eyeball log + review CSV,
  apply, spot-check `Availability` rows for a morning-care member (e.g.
  25255 `9 AM - 1 PM` on days 5.6.7 → end pulled to 09:00, window
  `08:00–09:00`) and an afternoon member (e.g. 25023 day 7 `12 PM - 4 PM`
  → end 12:00). Then build the exe and repeat once through the GUI.

## 9. Out of scope

- Editing answers in the GUI (the CSV is edited in Excel).
- Splitting a day into two Availability windows (schema holds one window per
  day; the longer-piece rule + review CSV covers it).
- Applying `blocked` days automatically (operator decides per member).
- Multi-language UI (operator tool).
- Undo beyond the automatic backup.
