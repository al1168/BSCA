# Authorization backfill from Contacts — design

## Goal

A one-shot CLI that aligns the `Authorization` table with `Contacts`
along two narrow axes:

1. **Health Plan backfill.** For every Contact, write
   `Contacts.[Health Plan]` into every Authorization row that belongs
   to that member but currently has a blank `[Health Plan]`. Existing
   non-blank `[Health Plan]` values are left alone — Authorization is
   the going-forward source of truth, so manually-entered values win
   over a fresh copy from Contacts.

2. **Missing-Authorization backfill.** For every Contact with **zero**
   Authorization rows, insert one row using legacy Contacts columns:

   | Authorization column | Source |
   | --- | --- |
   | `[Center ID]` | `Contacts.[Center ID]` (bound as string) |
   | `auth_start`, `effective_start` | `Contacts.[Auth BGN]` |
   | `auth_end`, `effective_end` | `Contacts.[Auth EXP]` |
   | `auth_days` | `Contacts.[SADC]` parsed by [monthly_schedule/auth_days.py](../../../monthly_schedule/auth_days.py), reformatted as `"d,d,d"` |
   | `[Health Plan]` | `Contacts.[Health Plan]` |
   | `notes` | NULL |

## Out of scope

- Touching `Enrollment`, `Absences`, or `Availability` (covered by
  other scripts or done by hand).
- Reconciling members whose Authorization `[Health Plan]` already
  differs from Contacts — no overwrite, no warning, no log line.
- Reading `SADC_Latest`, `SADC Auth`, `TRANS Auth`, or any other
  legacy column beyond the four named above.

## Data flow

A single SELECT pulls every Contact with the five columns we care
about. For each contact:

```
read Contacts row -> (cid, last, first, health_plan, sadc, auth_bgn, auth_exp)
  |
  v
COUNT(*) FROM Authorization WHERE [Center ID] = str(cid)
  |
  +-- count > 0:                          (UPDATE branch)
  |     SELECT [ID], [Health Plan] FROM Authorization WHERE [Center ID] = str(cid)
  |     for each existing row with blank [Health Plan]:
  |         if health_plan is NULL/empty:
  |             -> skip this member, CSV row: action=no_health_plan_for_update
  |             stop iterating this member
  |         else:
  |             UPDATE Authorization SET [Health Plan] = ? WHERE [ID] = ?
  |             stats.updated += 1
  |
  +-- count == 0:                         (INSERT branch)
        parse_legacy_fields() -> (auth_days_str, bgn_date, exp_date, plan_or_None)
        missing = []
        if auth_days_str == "":   missing.append("SADC")
        if bgn_date is None:      missing.append("Auth BGN")
        if exp_date is None:      missing.append("Auth EXP")
        if not plan_or_None:      missing.append("Health Plan")
        if missing:
            -> skip, CSV row: action=missing_legacy_fields, missing=...
        else:
            INSERT INTO Authorization
              ([Center ID], [auth_start], [auth_end],
               [effective_start], [effective_end], [auth_days], [Health Plan])
            VALUES (str(cid), bgn_date, exp_date,
                    bgn_date, exp_date, auth_days_str, plan)
            stats.inserted += 1
```

### Decisions baked in

- **"Blank" means NULL or whitespace-only.** Throughout this spec,
  `[Health Plan]` is considered blank when it is `None` or
  `str(value).strip() == ""`. The same rule applies to
  `Contacts.[Health Plan]` (when deciding whether to skip the member)
  and to existing `Authorization.[Health Plan]` rows (when deciding
  whether to fill them).
- **`[Center ID]` bound as string.** Matches the existing convention
  in [scripts/make_test_db.py](../../../scripts/make_test_db.py) and
  [scripts/backfill_availability_from_hha.py](../../../scripts/backfill_availability_from_hha.py).
- **`auth_days` formatting.** Reuse
  [`get_authorized_weekdays`](../../../monthly_schedule/auth_days.py) to
  parse SADC into a set of ints, then `",".join(str(n) for n in
  sorted(s))`. Normalizes `"Mon Wed Fri"`, `"1.3.5"`, and `"1,3,5"` to
  the same canonical string.
- **Only-fill-blanks on UPDATE.** A row whose `[Health Plan]` is
  already non-empty is left untouched (no overwrite, no log entry, no
  CSV row). The script is safely idempotent — re-running never
  clobbers an Authorization-side value.
- **Same Health Plan across all of a member's existing rows.** If a
  member has three Authorization rows all with blank `[Health Plan]`,
  all three get the same Contacts value. We don't try to be clever
  per-row.
- **Date typing.** `Auth BGN` / `Auth EXP` come back from pyodbc as
  `datetime` (Access stores them as DATETIME). They pass straight
  through to the INSERT without normalizing the time-of-day component,
  matching how [scripts/make_test_db.py](../../../scripts/make_test_db.py)
  writes dates.
- **One transaction.** One connection, one transaction, committed at
  the end (rolled back on `--dry-run`). No incremental commits — a
  midway crash leaves the DB unchanged.

## CLI surface

```
python scripts\backfill_authorization_from_contacts.py --db <PATH> \
    [--dry-run] [--csv-out DIR] [--quiet]
```

| Flag | Meaning |
| --- | --- |
| `--db PATH` (required) | Path to the Access `.accdb`. Errors out if missing or if the ODBC driver can't open it. |
| `--dry-run` | Run the full pass, write the skipped CSV, then `conn.rollback()` instead of `commit()`. |
| `--csv-out DIR` (default `.`) | Directory for the skipped-members CSV. Created if missing. |
| `--quiet` | Suppress per-row stdout; the run summary still prints. |

**Exit codes:**

- `0` — clean run, even if some members were skipped (the CSV is the
  artifact for those).
- `2` — DB path doesn't exist, or the ODBC driver fails to open it.

## Per-row stdout (suppressed by `--quiet`)

```
  UPDATED   24010  filled 2 row(s) with 'HOF'
  INSERTED  24011  HOF, 1,3,5, 2026-01-01 -> 2026-12-31
  SKIPPED   24012  no Health Plan on Contacts (had 1 existing auth row)
  SKIPPED   24013  no existing auth + missing: SADC, Auth EXP
```

## Skipped CSV

Lands at `<csv-out>/auth_backfill_skipped_<YYYY-MM-DD>.csv`, written
in `utf-8-sig` (Excel-friendly for CJK names, same as the HHA CSV).
The header is written even on an empty run so the file's presence
signals "a backfill ran on this date."

Columns: `center_id, last_name, first_name, action, missing_fields`.

Two `action` values, nothing else:

- `no_health_plan_for_update` — member has at least one Authorization
  row with blank `[Health Plan]`, but `Contacts.[Health Plan]` is
  NULL/empty so we couldn't fill it. `missing_fields` is always just
  `Health Plan`.
- `missing_legacy_fields` — member has zero Authorization rows, and
  at least one of `SADC` / `Auth BGN` / `Auth EXP` / `Health Plan`
  on Contacts is missing. `missing_fields` lists the missing names,
  semicolon-separated.

## Run summary (always printed)

```
Authorization backfill summary
  Contacts scanned:                            287
  Existing-auth members: Health Plan filled:   142   (rows updated: 203)
  Existing-auth members: already populated:    101
  Existing-auth members: skipped (no plan):      4
  No-auth members: Authorization inserted:     119
  No-auth members: skipped (missing legacy):    22
  Skipped CSV: .\auth_backfill_skipped_2026-06-02.csv
  Mode: APPLIED         (or: DRY-RUN (no changes committed))
```

Counters are tallied during the pass and printed verbatim — same
shape as the HHA summary so the operator's eye knows where to look.

## Error handling

- **Missing DB file or ODBC failure.** Print a one-line error to
  stderr (same wording as
  [scripts/backfill_availability_from_hha.py](../../../scripts/backfill_availability_from_hha.py),
  which calls out driver bitness), exit `2`.
- **Other exceptions during the pass.** Not caught. The `try`/`finally`
  calls `conn.close()`; an uncaught exception means the transaction
  is never committed, so the DB is left as it was. Traceback goes to
  stderr and the operator can re-run.
- **No `--commit` flag inverse.** Default is APPLIED. `--dry-run` is
  the only opt-out. Matches the HHA script.

## Edge cases

| Case | Behavior |
| --- | --- |
| Contacts row with NULL `Center ID` | Skip silently. Not counted in "scanned." |
| Contacts row with no legacy data AND no Health Plan AND no existing auth row | One CSV row, `action=missing_legacy_fields`, missing list includes all four names. |
| Member has one Authorization row, `[Health Plan]` already `"HOF"`, Contacts says `"HOFV2"` | Leave it alone. No log line, no CSV entry, not counted as updated. |
| Member has two Authorization rows: one blank, one filled | UPDATE the blank one only. `stats.updated += 1`. Per-row stdout: `filled 1 row(s) with 'HOF'`. |
| `SADC` parses to empty (e.g. `"none"`, `"TBD"`) | Treated as missing. CSV `missing_fields` lists `SADC`. |
| `Auth BGN` present but `Auth EXP` NULL (or vice versa) | Treated as missing. Both must be present to write a date range. |
| Two Contacts rows share a `Center ID` (data error) | Process both independently. The second one's UPDATE branch sees whatever the first one wrote. No special detection. |

## Testing

Three new pytest tests in `tests/test_backfill_authorization.py`,
driving an in-memory SQLite stand-in through the same parametrized SQL:

1. **`test_update_branch_fills_blank_only`** — member has two
   Authorization rows (one blank Health Plan, one filled). Run the
   script. Assert the blank one was set to the Contacts value and the
   filled one was left untouched.
2. **`test_insert_branch_uses_legacy_columns`** — member has zero
   Authorization rows but all four legacy fields present. Run the
   script. Assert one new Authorization row exists with the expected
   `auth_days`, dates, and Health Plan.
3. **`test_skip_paths_emit_csv`** — three members covering both skip
   reasons (`no_health_plan_for_update` and `missing_legacy_fields`).
   Run with `--dry-run`. Assert the CSV exists with the expected rows
   and that no DB changes survived the rollback.

If implementation extracts a `format_auth_days(set) -> "1,3,5"`
helper, a pure unit test for it goes in
[tests/test_auth_days.py](../../../tests/test_auth_days.py).

### Not tested

- The ODBC layer or Access-specific quirks (matches the test posture
  of the HHA backfill, which also doesn't exercise the adapter).
- End-to-end against a real `.accdb`. The operator runs against a
  working copy with `--dry-run` first.

## README integration

After the script lands, add a section to the project README mirroring
the structure of the "Backfill Availability from HHA notes" block:

- Title: **Backfill Authorization from Contacts**.
- One-sentence summary of what it does and the two branches
  (UPDATE-Health-Plan vs INSERT-from-legacy).
- The full invocation.
- A paragraph explaining the only-fill-blanks rule and the
  skipped-CSV artifact.
- Link back to this design doc.

## See also

- [docs/database.md](../../database.md) — Authorization schema and
  the legacy-Contacts migration note.
- [docs/superpowers/specs/2026-06-01-hha-availability-backfill-design.md](2026-06-01-hha-availability-backfill-design.md)
  — sibling backfill script whose CLI shape this one follows.
- [docs/superpowers/specs/2026-05-26-schedule-data-model-design.md](2026-05-26-schedule-data-model-design.md)
  — the broader schema redesign this backfill serves.
