# Batch Member Selection — Design

**Date:** 2026-05-15
**Status:** Approved (design); pending implementation plan
**Builds on:** `docs/superpowers/specs/2026-05-15-monthly-schedule-design.md`

## 1. Purpose & Scope

Extend `new_monthly_schedule.py` so members can be selected three
mutually-exclusive ways and processed in one batch invocation:

1. a single Center ID (existing behavior),
2. an explicit list of Center IDs,
3. all members on a given MLTC plan code (e.g. `HOF`).

Only `new_monthly_schedule.py` (CLI/orchestration) and
`monthly_schedule/db.py` (one new query) change. `month_dates`,
`auth_days`, `eligibility`, `rules`, `daily_schedule`, `rows`,
`workbook`, and `health_plan` are unchanged.

## 2. CLI

The standalone required `--center-id` is replaced by a **required,
mutually-exclusive argument group** — exactly one of:

| Argument        | Meaning                                                            |
|-----------------|--------------------------------------------------------------------|
| `--center-id N` | Single member (int).                                               |
| `--center-ids S`| Comma-separated Center IDs. Deduped, blanks/whitespace ignored, processed left-to-right in the given order. |
| `--plan CODE`   | All members whose `Health Plan` equals `CODE` (case-insensitive exact match; e.g. `HOF`, `hof`). |

argparse: a `required=True` mutually-exclusive group containing the
three. Supplying zero or more than one selector exits non-zero with
the argparse usage error (`SystemExit`).

Unchanged arguments: `--year` (req), `--month` (req, 1–12),
`--db-path` (default the BOWERY3 share), `--preview-data`.

**`--output-path` changes meaning** from a single `.xlsx` file path to
a **base output directory** (default `.`). This is an intentional
breaking change to the prior single-file semantics, accepted during
brainstorming.

## 3. Output Layout

Every produced file is named `Schedule_<id>_<YYYY-MM>.xlsx` where
`<id>` is the member's Center ID and `<YYYY-MM>` is the zero-padded
year/month.

| Mode            | Destination                                                |
|-----------------|------------------------------------------------------------|
| `--center-id`   | `<output-path>/Schedule_<id>_<YYYY-MM>.xlsx`               |
| `--center-ids`  | Same, one file per id, all directly in `<output-path>/`    |
| `--plan`        | `<output-path>/<CODE>_<YYYY-MM>/Schedule_<id>_<YYYY-MM>.xlsx` |

`<CODE>` in the plan subdirectory is upper-cased (e.g. `HOF_2026-05`).
Target directories are created with `os.makedirs(dir, exist_ok=True)`
before writing.

## 4. Data Flow

`main()`:

1. Parse args; determine the selection mode from which group member is
   set.
2. Resolve to an ordered `list[member]`:
   - single → `[get_member(id, db_path)]` (None ⇒ recorded as a
     not-found failure for that id),
   - list → `get_member(id, db_path)` for each parsed id (per-id
     None ⇒ not-found failure, continue),
   - plan → new `get_members_by_plan(code, db_path)` — one DB
     connection, `MEMBERS_BY_PLAN_QUERY`
     (`SELECT [Center ID], [Last Name], [First Name], [Health Plan],
     [SADC] FROM [Contacts] WHERE [Health Plan] = ?`), each row mapped
     by the existing `map_member_row`, returned ordered by Center ID.
3. Compute the output directory (base, plus `<CODE>_<YYYY-MM>` subdir
   for plan mode) and `os.makedirs` it (unless `--preview-data`).
4. For each resolved member, invoke a single extracted helper that
   performs the existing per-member pipeline: parse authorized
   weekdays, warn to stderr if empty, resolve plan rules, build rows,
   then either print preview rows or write the workbook.
5. Collect per-member success/failure; print an end-of-run summary;
   return the exit code.

The per-member pipeline currently inline in `main()` is extracted into
a helper (e.g. `process_member(member, year, month, out_dir,
preview)`) so single and batch share one code path. `get_members_by_plan`
keeps the same `(…, db_path)` signature as `get_member` for db-layer
symmetry and offline testability (a test injects a fake path to hit the
missing-DB branch).

`--preview-data`: prints each member's rows preceded by a header line
`=== ID <id> (<Last, First>) ===`, writes no files, creates no
directories.

## 5. Error Handling

**Per-member (batch continues):** an id not found, or any exception
raised while processing one member, is caught, recorded with a reason,
and processing continues with the next member.

**Not a failure:** an empty/unparseable `SADC` value still produces a
blank-times workbook and emits the existing stderr warning; it counts
as a success.

**Global (abort immediately, as today):** missing DB path or ODBC
driver/bitness error from the first DB call propagates to the existing
clean handler (stderr message, exit 1).

**Empty plan:** `--plan CODE` matching zero members is an error —
stderr message, non-zero exit, no directory created.

**Summary (stderr):** e.g.
`Wrote 18 file(s); skipped 2: 24099 (not found), 24100 (not found)`.
For preview mode the summary counts members previewed.

**Exit code:** `main()` returns `0` if every selected member
succeeded and at least one member was selected; returns `2` if any
member failed or the plan matched nobody (mirrors the existing
no-member exit `2`). A global DB/driver error still returns `1` via
the existing handler. Invalid argument selection is argparse's own
`SystemExit` (exit `2`).

## 6. Testing (pytest)

`tests/test_db.py` (additions, mirroring existing `get_member` tests):

- `MEMBERS_BY_PLAN_QUERY` contains `[Center ID]`, `[Last Name]`,
  `[First Name]`, `[Health Plan]`, `[SADC]`, and
  `WHERE [Health Plan] = ?`.
- `get_members_by_plan("HOF", <missing tmp path>)` raises
  `FileNotFoundError` (lazy `pyodbc` import, like `get_member`).

`tests/test_cli.py` (additions; `get_member` /
`get_members_by_plan` monkeypatched — no real DB, no real Excel except
via `tmp_path`):

- `--center-ids "24010, 24011 ,,24010"` parses to `[24010, 24011]`
  (trim, drop blanks, dedupe, order preserved).
- The mutually-exclusive group: zero selectors and two selectors each
  raise `SystemExit`.
- Plan mode writes into `<output-path>/<CODE>_<YYYY-MM>/` with the
  correct per-member filenames (assert files exist under the subdir).
- Batch with one not-found id among valid ones: valid files written,
  exit code non-zero, summary names the skipped id.
- `--plan` with zero matched members: non-zero exit, message, no dir
  created.
- `--preview-data` batch: prints a `=== ID <id> …===` header per
  member and writes no files/dirs.
- Existing single-mode tests updated for the `--output-path`-as-
  directory change (a single `--center-id` run writes
  `<dir>/Schedule_<id>_<YYYY-MM>.xlsx`).

Manual: `--plan HOF --year 2026 --month 5` against the live DB
produces `./HOF_2026-05/Schedule_<id>_2026-05.xlsx` for each HOF
member.

## 7. Out of Scope (YAGNI)

- Combining selectors (union/intersection of list + plan).
- A single combined multi-member workbook.
- Reading IDs from a file.
- Parallel processing of members.
- Plan matching by friendly MLTC name (code only).
