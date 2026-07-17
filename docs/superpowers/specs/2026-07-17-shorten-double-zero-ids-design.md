# Shorten Double-Zero Center IDs

Status: Draft
Date: 2026-07-17

## Goal

Provide a CLI script that renames every Center ID that is longer than 5
digits AND ends with `00` to its shortened form with the trailing `00`
stripped (`2213400` → `22134`), across **every** table that carries a
`[Center ID]` column. Same dry-run / skipped-CSV / summary shape as the
existing maintenance scripts.

## Motivation

Center IDs in this database come in two formats:

- **5 digits** (e.g. `24010`, `25049`) — the canonical form.
- **6+ digits ending in `00`** (e.g. `2213400`) — the same member's ID
  extended with trailing zeros. These should be collapsed back to the
  canonical 5-digit form so the member's rows are keyed consistently.

`scripts/terminate_long_id_enrollments.py` (2026-06-09) previously set
`end_date = 2000-01-01` on all long-ID members' open Enrollment rows.
This script does NOT undo that: it renames `[Center ID]` values only and
leaves every `end_date` untouched (user decision, 2026-07-17).

## Scope

In scope:

- `scripts/shorten_double_zero_ids.py` — new CLI script.
- `tests/test_shorten_double_zero_ids.py` — unit tests mirroring the
  existing `tests/test_terminate_long_id_enrollments.py` pattern
  (MagicMock cursor, no real Access connection).
- All seven tables that carry `[Center ID]`: `Contacts`, `Enrollment`,
  `Authorization`, `Absences`, `Availability`, `OneOffAvailability`,
  `EmergencyContact`.

Out of scope:

- `Authorization.[Member ID]` and `Contacts.[Member ID]` — those hold
  the member's external Medicaid-style TEXT identifier, not the Center
  ID, and are unaffected by this rename.
- Merging collided members (see Collisions below) — collisions are
  reported for manual resolution, never auto-merged (user decision,
  2026-07-17).
- Clearing `end_date = 2000-01-01` terminations for renamed members.
- A reverse / undo script. Recovery path is the existing convention of
  copying the `.accdb` to a timestamped backup before running.
- GUI hookup. Operator-only CLI script, like the other maintenance
  scripts.

## Design

### CLI

```
python scripts/shorten_double_zero_ids.py --db <path>
  [--csv-out DIR]     # default: cwd
  [--dry-run]         # do everything, roll back instead of commit
  [--quiet]           # suppress per-member stdout
```

Same argparse layout as `scripts/terminate_long_id_enrollments.py`.

### Qualification rule

```python
def _qualifies(center_id):
    """True if the Center ID, rendered as a base-10 integer string,
    is more than 5 characters long AND ends with '00'. Mirrors
    `_is_long_id` in terminate_long_id_enrollments.py for handling the
    DOUBLE-typed Center ID field without trailing '.0' confusion."""
    if center_id is None:
        return False
    s = str(int(center_id))
    return len(s) > 5 and s.endswith("00")
```

- `2213400` → qualifies (7 digits, ends `00`).
- `2400601` → does NOT qualify (long but doesn't end in `00`).
- `24010`, `99900` → do NOT qualify (5 digits or fewer).
- `None` → does not qualify.

### Target ID

`new_id = int(center_id) // 100` — strips exactly one trailing `00`.
The mapping is injective (no two distinct old IDs produce the same new
ID), so renames can never collide with each other, only with
pre-existing IDs.

If `new_id` is still longer than 5 digits (e.g. `221340000` →
`2213400`), the member is **skipped and reported** rather than
half-fixed: the goal is 5-digit canonical IDs, and anything that
doesn't get there in one strip deserves a human look. Results shorter
than 5 digits (e.g. `123400` → `1234`) are renamed as-is — the rule is
"strip one trailing 00", not "pad to 5".

### Collisions

Before renaming a member, the script checks whether `new_id` already
exists in **any** of the seven tables. If it does, the member is
skipped entirely — no partial rename — and written to the CSV report
with the list of tables where the collision was found.

Implementation: prefetch the distinct `[Center ID]` values of each
table into seven Python sets (one scan per table, up-front). Collision
check = set membership. Because the rename mapping is injective and a
qualifying old ID can never equal another member's `new_id` (a
qualifying ID is >5 digits; a valid `new_id` is ≤5 digits), the
prefetched sets stay valid for the whole run without re-scanning.

### SQL

```python
_TABLES = ["Contacts", "Enrollment", "Authorization", "Absences",
           "Availability", "OneOffAvailability", "EmergencyContact"]

# Per table:
_SCAN = "SELECT [Center ID] FROM [{table}]"
_RENAME = "UPDATE [{table}] SET [Center ID] = ? WHERE [Center ID] = ?"
```

Notes:

- All rows for a given old ID in a given table are renamed by one
  UPDATE; `cursor.rowcount` feeds the per-table counters.
- No `end_date` filtering anywhere — this script renames rows
  regardless of enrollment status.

### Behavior

Processing is **member-centric** (one decision per old Center ID).

1. Open the Access DB; surface a clear `database not found` error and
   exit 2 if the file doesn't exist (same pattern as existing scripts).
2. Scan all seven tables, building per-table sets of distinct integer
   Center IDs (NULLs skipped).
3. Build the candidate list: every qualifying ID that appears in ANY
   table (union of the seven sets, filtered by `_qualifies`). Driving
   from the union rather than Contacts alone means orphaned child-table
   rows (qualifying ID with no Contacts row) are renamed too — nothing
   referencing an old ID is left behind.
4. For each candidate `old_id` (sorted ascending):
   - If `new_id` is still >5 digits → skip; CSV reason
     `"still longer than 5 digits after stripping 00"`.
   - Else if `new_id` exists in any table's ID set → skip; CSV reason
     `"target ID already exists in: <table, table, ...>"`.
   - Else → run the UPDATE against each of the seven tables; add each
     `cursor.rowcount` to that table's counter. Count the member as
     renamed.
5. After the loop:
   - Write the skipped CSV (always, even if empty — file presence
     signals "a run happened on this date").
   - If `--dry-run`: `conn.rollback()`; print `Mode: DRY-RUN`.
   - Otherwise: `conn.commit()`; print `Mode: APPLIED`.
6. Print the summary (see below).

A single commit at the end; any unexpected exception propagates without
committing, so a crashed run leaves the database unchanged.

### Output CSV

Path: `<csv-out>/shorten_ids_skipped_<YYYY-MM-DD>.csv`.

Columns: `old_id`, `new_id`, `reason`. One row per skipped member.
Collision reasons embed the table list in the reason text.

### Summary stdout

```
Shorten-double-zero-ID summary
  Candidate IDs found (>5 digits, ends 00):  <N>
  Members renamed:                           <N>
  Rows updated per table:
    Contacts:            <N>
    Enrollment:          <N>
    Authorization:       <N>
    Absences:            <N>
    Availability:        <N>
    OneOffAvailability:  <N>
    EmergencyContact:    <N>
  Members skipped (collision):               <N>
  Members skipped (still too long):          <N>
  Skipped CSV: <path>
  Mode: APPLIED | DRY-RUN
```

Per-member stdout (suppressed by `--quiet`):

- `renamed <old_id> -> <new_id> (<N> rows across <M> tables)`
- `skipped <old_id> -> <new_id> (<reason>)`

## Migration / compatibility

No schema changes. After an APPLIED run, previously long-keyed rows are
keyed by the 5-digit ID, so the scheduler's per-member fetches and
batch `{center_id: rows}` maps pick them up under the short ID
automatically. Members whose enrollments were terminated by the
2026-06-09 script remain terminated (now under the short ID) and stay
off schedules until `end_date` is fixed separately.

## Testing

`tests/test_shorten_double_zero_ids.py` mirrors
`tests/test_terminate_long_id_enrollments.py` — MagicMock pyodbc
cursor, no real Access connection:

- `test_build_connection_string` — ODBC connection string shape.
- `test_main_missing_db_returns_2` — non-existent `--db` returns 2 with
  `"database not found"` on stderr.
- `test_qualifies_true_cases` — `2213400`, `100000`, `2213400.0`
  (DOUBLE form), 8+ digit IDs ending `00`.
- `test_qualifies_false_cases` — 5-digit IDs (`24010`, `99900`), long
  IDs not ending `00` (`2400601`), `None`.
- `test_new_id` — `2213400` → `22134`; `123400` → `1234`.
- `test_tables_list` — the seven expected table names, Contacts first.
- `test_scan_and_rename_query_shapes` — SELECT/UPDATE contain the
  bracketed table and column names; UPDATE has 2 params.
- `test_main_renames_across_all_tables` — happy path: one qualifying ID
  present in several tables triggers one UPDATE per table with
  `(new_id, old_id)` params.
- `test_main_skips_collision` — target ID present in one table → no
  UPDATE for that member; CSV row names the colliding table.
- `test_main_skips_still_too_long` — `221340000` → no UPDATE; CSV
  reason "still longer than 5 digits".
- `test_main_renames_orphaned_child_rows` — qualifying ID present only
  in Enrollment (no Contacts row) still gets renamed there.
- `test_main_ignores_non_qualifying_ids` — short IDs, long-non-00 IDs,
  and NULLs trigger no UPDATE.
- `test_dry_run_calls_rollback_not_commit`.
- `test_quiet_suppresses_per_member_output` — summary still appears.

Manual verification (operator):

1. Copy `members.accdb` to a timestamped backup (existing convention).
2. Run with `--dry-run`; confirm the candidate/renamed/skipped counts
   and skim the skipped CSV.
3. Re-run without `--dry-run`; spot-check a renamed member in Access
   (all their rows now keyed by the 5-digit ID, `end_date` untouched).
4. Run the GUI scheduler against the DB and confirm behavior is
   unchanged for active members.
