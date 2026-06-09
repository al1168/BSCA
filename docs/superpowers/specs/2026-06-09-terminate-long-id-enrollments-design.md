# Terminate Long-ID Enrollments

Status: Draft
Date: 2026-06-09

## Goal

Provide a CLI script that marks every Enrollment row whose member's `[Center ID]` is more than 5 digits long as terminated, by setting `end_date` to `2000-01-01`. Rows whose `end_date` is already set are left alone. Same dry-run / skipped-CSV / summary shape as the existing `backfill_*_from_*.py` scripts.

## Motivation

Center IDs in this database come in two formats:

- **5 digits** (e.g. `24010`, `25049`) — active members.
- **6+ digits** (e.g. `2400600`, `2530900`) — historical/transferred members where the old ID was extended with trailing digits. These should not appear on monthly schedules.

The eligibility logic in `monthly_schedule/per_day.py` already filters out members whose enrollment ended before the target month. By terminating long-ID enrollments to `2000-01-01`, they silently drop out of every future schedule run without any other code changes. Today, 159 long-ID enrollment rows exist in production, all with `end_date IS NULL`, so they still appear as candidates for scheduling.

## Scope

In scope:

- `scripts/terminate_long_id_enrollments.py` — new CLI script.
- `tests/test_terminate_long_id_enrollments.py` — unit tests mirroring the existing `tests/test_backfill_*.py` pattern (MagicMock cursor, no real Access connection).

Out of scope:

- Touching the `Authorization`, `Availability`, or `Absences` tables. If a long-ID member needs to be marked terminated in those too, that's a separate decision; this script's job is `Enrollment` only.
- Any change to `Contacts`.
- A reverse / undo script. Recovery path is the existing convention of copying the `.accdb` to a timestamped backup before running.
- GUI hookup. This script is operator-only, run from the CLI like the other backfills.

## Design

### CLI

```
python scripts/terminate_long_id_enrollments.py --db <path>
  [--csv-out DIR]     # default: cwd
  [--dry-run]         # parse + write CSV, no DB commit
  [--quiet]           # suppress per-row stdout
```

Same argparse layout as `scripts/backfill_enrollment_from_contacts.py` minus the `--exclude-test-members` flag — for this script, all long-ID rows ARE the termination target. A filter that excluded test members would defeat the purpose.

### Long-ID detection

```python
def _is_long_id(center_id):
    """True if the Center ID, rendered as a base-10 integer string,
    is more than 5 characters long. Mirrors `_is_test_id` in
    backfill_enrollment_from_contacts.py for handling the DOUBLE-typed
    Center ID field without trailing '.0' confusion."""
    if center_id is None:
        return False
    return len(str(int(center_id))) > 5
```

5 digits (`24010`, `99999`) → False. 6+ digits (`100000`, `2400600`, `2530900`) → True.

### Termination date

A module-level constant:

```python
TERMINATION_DATE = datetime.date(2000, 1, 1)
```

Used in the UPDATE statement as `end_date`. Not configurable via CLI — the user explicitly chose this as the canonical "terminated" marker.

### SQL

```python
_ENROLLMENT_SCAN = (
    "SELECT [Center ID], [end_date] FROM [Enrollment] ORDER BY [Center ID]"
)

_ENROLLMENT_TERMINATE = (
    "UPDATE [Enrollment] SET [end_date] = ? "
    "WHERE [Center ID] = ? AND [end_date] IS NULL"
)
```

Notes:

- The scan is a full table read; matches the read-then-write pattern of the existing backfill scripts.
- The UPDATE re-checks `end_date IS NULL` in its WHERE clause. Belt-and-suspenders against the (vanishingly unlikely) race where a row's end_date changes between scan and update; the script is single-threaded so this is purely defensive.
- The UPDATE targets `[Center ID] = ?`. A member can in principle have multiple Enrollment rows; this UPDATE terminates **every** row for that Center ID that still has `end_date IS NULL`. That matches the intent: "this member is no longer active; mark all their open enrollments as ended."

### Behavior

Processing is **member-centric** (one decision per Center ID), not row-centric. A member may have multiple Enrollment rows; we want one verdict per member, not one verdict per row, otherwise a member with one open enrollment and one closed enrollment would be both "terminated" and "skipped" — confusing accounting and a misleading CSV.

1. Open the Access DB; surface a clear `database not found` error and exit 2 if the file doesn't exist (same pattern as the existing scripts).
2. Run the scan. Build an in-memory map `{cid: [end_date, ...]}` keyed by Center ID, populated from the scan rows. Skip scan rows where `center_id` is None (existing scripts do the same) or where `not _is_long_id(center_id)` (out of scope).
3. For each `(cid, end_dates)` in the map:
   - If at least one `end_date` is `None` → execute the UPDATE once. Count the member as **terminated**; add `cursor.rowcount` to "Enrollment rows updated".
   - If every `end_date` is non-null → no UPDATE. Count the member as **already ended** and append one row to the skipped CSV with the most recent (max) `end_date`.
4. After the loop:
   - Write the skipped CSV (always, even if empty — file presence signals "a termination ran on this date").
   - If `--dry-run`: `conn.rollback()`; print `Mode: DRY-RUN`.
   - Otherwise: `conn.commit()`; print `Mode: APPLIED`.
5. Print the summary (see below).

### Output CSV

Path: `<csv-out>/terminate_long_id_skipped_<YYYY-MM-DD>.csv` (where `<YYYY-MM-DD>` is today's date).

Columns: `center_id`, `existing_end_date`, `reason`. One row per skipped **member** (not per Enrollment row).

`existing_end_date` is the most recent (max) existing `end_date` for that member, as ISO date string. `reason` is always `"end_date already set"` today — single value, but the column lets future skip reasons slot in without changing the CSV schema (mirrors the existing scripts' layouts).

### Summary stdout

```
Terminate-long-ID summary
  Enrollment rows scanned:             <N>
  Long-ID members found (>5 digits):   <N>
  Members terminated (end_date set):   <N>
  Enrollment rows updated:             <N>
  Members skipped (all already ended): <N>
  Skipped CSV: <path>
  Mode: APPLIED | DRY-RUN
```

Per-member stdout (suppressed by `--quiet`):

- `terminated cid=<id> (<N> rows)` for each UPDATE that ran.
- `skipped cid=<id> (existing end_date=<iso>)` for each member left alone.

## Migration / compatibility

None. This is a new script that operates against existing schema. No new tables, no new columns, no settings changes.

## Testing

`tests/test_terminate_long_id_enrollments.py` mirrors the `tests/test_backfill_enrollment_from_contacts.py` shape — unit tests with `MagicMock` for the pyodbc cursor; no real Access connection needed. Specifically:

- `test_build_connection_string` — verifies the ODBC connection string.
- `test_main_missing_db_returns_2` — non-existent `--db` path returns exit code 2 with `"database not found"` on stderr.
- `test_is_long_id_true_cases` — 6, 7, 10 digit IDs; including the `DOUBLE` form (`2400600.0`).
- `test_is_long_id_false_cases` — 1, 5 digit IDs; `None`; including `99999.0`.
- `test_enrollment_scan_query` — query shape assertions (SELECT, FROM, ORDER BY).
- `test_enrollment_terminate_query` — UPDATE shape: SET end_date, WHERE Center ID and end_date IS NULL, parameter count.
- `test_termination_date_constant` — confirms `TERMINATION_DATE == datetime.date(2000, 1, 1)`.
- `test_main_skips_short_ids` — scan yields a mix of short and long IDs; only long IDs trigger UPDATE.
- `test_main_skips_already_ended_long_id` — long ID with non-null end_date triggers no UPDATE and appears in the skipped CSV.
- `test_main_terminates_long_id_with_null_end_date` — happy path: UPDATE called with `(TERMINATION_DATE, cid)`.
- `test_main_mixed_null_and_ended_rows_for_same_member` — a long-ID member with one NULL-end and one already-ended Enrollment row triggers ONE UPDATE for that member and does NOT appear in the skipped CSV. Verifies the member-centric processing model.
- `test_csv_skipped_row_uses_max_end_date` — a long-ID member with two non-null end_dates lands in the skipped CSV with the later (max) date in `existing_end_date`.
- `test_dry_run_calls_rollback_not_commit` — calling `main(["--db", ..., "--dry-run"])` results in `conn.rollback()` not `conn.commit()`.
- `test_quiet_suppresses_per_member_output` — `--quiet` suppresses per-member prints; summary still appears.

Manual verification (operator):

1. Make a backup copy of `members.accdb` (existing convention).
2. Run `python scripts/terminate_long_id_enrollments.py --db <path> --dry-run` — confirms summary reports the expected count (159 today) with no DB changes.
3. Re-run without `--dry-run` — confirms the 159 rows now have `end_date = 2000-01-01`.
4. Open the GUI scheduler against the same DB and confirm those members no longer appear in any schedule run (the existing eligibility filter handles this automatically).
