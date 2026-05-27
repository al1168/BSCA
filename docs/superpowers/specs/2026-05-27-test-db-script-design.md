# Test-DB Setup Script

**Date:** 2026-05-27
**Status:** Approved (pending spec review)
**Scope:** A developer-facing CLI script that creates and seeds a
throwaway Access database, so the GUI can be exercised without
touching the production data.

## Goal

Give the developer a one-command way to spin up a fresh `.accdb` file
with synthetic data covering the scheduler's main flows, point the
GUI at it, and reset it back to a known state on demand.

## Design Decisions (Recap From Brainstorming)

| Decision | Choice |
| --- | --- |
| Testing flow scope | Named test DBs + scenario picker + reset \(all of the above\) |
| `.accdb` creation method | Copy prod DB → target, truncate the five data tables, seed scenario data |
| Default location | `test_dbs/` (gitignored) next to the project root |
| GUI integration | `--use` flag flips `bsca_settings.json` to point at the target |
| Seed scenarios | `happy_path`, `missing_data`, `mid_period_change`, `plan_full` |

## File Inventory

| Path | Action | Responsibility |
| --- | --- | --- |
| `scripts/__init__.py` | Create | Empty; makes `scripts/` a package. |
| `scripts/make_test_db.py` | Create | The script itself. Argparse CLI, copy/truncate/seed logic, scenario seed functions. |
| `test_dbs/` | Create at runtime | Output directory. Auto-created when needed. |
| `.gitignore` | Modify | Add `test_dbs/`. |

The script imports `pyodbc` directly (mirrors
[monthly_schedule/db.py](../../../monthly_schedule/db.py)) and uses
`gui.app_settings` only to read/write `bsca_settings.json` when
`--use` is passed. It does NOT import from `monthly_schedule.db` — a
testing utility shouldn't depend on the production DAL.

## CLI

```
python scripts/make_test_db.py --scenario <name> [--output PATH] [--source PATH] [--use]
```

| Flag | Default | Behavior |
| --- | --- | --- |
| `--scenario` | required | One of: `happy_path`, `missing_data`, `mid_period_change`, `plan_full`. Validated against the `SCENARIOS` dict; unknown values exit with a clear error. |
| `--output` | `test_dbs/<scenario>.accdb` | Target path. If the file doesn't exist, the script copies `--source` to it first. If it does exist, the script just truncates + reseeds (effectively a reset). |
| `--source` | `\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb` (the `DEFAULT_DB` constant already used in [new_monthly_schedule.py](../../../new_monthly_schedule.py)) | The reference DB used when the target needs to be created. Only consulted when the target file doesn't exist. |
| `--use` | off | After seeding, update `bsca_settings.json`'s `db_path` to point at the target. Lets the GUI immediately pick it up on next launch. |

### Example Flows

```powershell
# First-time create + point GUI at it
python scripts/make_test_db.py --scenario happy_path --use

# Reset the same DB to a clean happy_path state
python scripts/make_test_db.py --scenario happy_path

# Spin up a second test DB with a different scenario
python scripts/make_test_db.py --scenario mid_period_change --output test_dbs/edge_cases.accdb --use

# Switch back to prod
# (manually, via Settings dialog, or by editing bsca_settings.json)
```

## Internal Structure

```python
SCENARIOS: dict[str, Callable[[pyodbc.Connection, date], None]] = {
    "happy_path": seed_happy_path,
    "missing_data": seed_missing_data,
    "mid_period_change": seed_mid_period_change,
    "plan_full": seed_plan_full,
}

# Tables truncated before every seed:
DATA_TABLES = ("Availability", "Absences", "Authorization",
               "Enrollment", "Contacts")
# (Order matters: child tables first to satisfy any FK constraints.)
```

Each `seed_*` function takes `(conn, today)` and inserts rows.
`today` is `date.today()` captured once at script start; passing it in
keeps the seed functions pure and testable in isolation.

A `_seed_member(conn, center_id, last, first, plan="HOF",
address="123 Test St, New York, NY 10001")` helper inserts the
Contacts row with only the columns the scheduler reads (everything
else NULL). Keeps each scenario function short.

A `_truncate_all(conn)` helper runs `DELETE FROM` against each name in
`DATA_TABLES`.

### Type quirks to honor at INSERT time

The four tables have inconsistent `Center ID` column types (a wart of
the real schema we work around — not something to "fix" here):

| Table | `Center ID` type | INSERT value |
| --- | --- | --- |
| Contacts | DOUBLE | Python `int` (Access widens silently) |
| Enrollment | INTEGER | Python `int` |
| Authorization | VARCHAR | Python `str(center_id)` |
| Absences | VARCHAR | Python `str(center_id)` |
| Availability | VARCHAR | Python `str(center_id)` |

`avail_start` and `avail_end` are stored as DATETIME with a fixed
1899-12-30 placeholder date. Insert as
`datetime(1899, 12, 30, hour, minute)`. The mapper in
[monthly_schedule/db.py](../../../monthly_schedule/db.py) already
unwraps this back to `"HH:MM"` strings.

Pure date fields (`start_date`, `end_date`, `auth_start`, `auth_end`,
`effective_*`, `Start_Date`, `End_Date`, `effective_start_date`,
`effective_end_date`) accept Python `datetime.date` or
`datetime.datetime`; either is fine because pyodbc/Access widens.

## Scenarios

All scenarios use synthetic Center IDs starting at **99001** to avoid
colliding with real IDs (which are ≤ 7 digits in practice). Dates are
computed relative to `date.today()` so the data stays relevant to the
current schedule month no matter when the script runs.

Helpful shorthand below:
- `M1` = first day of the current month
- `M15` = 15th of the current month
- `MLAST` = last day of the current month
- `MNEXT_LAST` = last day of next month

Every scenario starts by `DELETE FROM`-ing the five data tables.
Scheduler-untouched Contacts columns (SADC, Photo, SSN, Medicaid,
etc.) are left NULL.

### `happy_path`

**Center 99001 "Test, Happy"** — HOF, NYC address.

| Table | Rows |
| --- | --- |
| Contacts | 1 row (the member) |
| Enrollment | started 1 year before today, `end_date=NULL` |
| Authorization | `auth_start=M1`, `auth_end=MNEXT_LAST`, `effective_*` identical to `auth_*`, `auth_days="1,2,3,4,5"` |
| Availability | 5 rows (Mon–Fri, `avail_start="08:00"`, `avail_end="16:00"`), `effective_start_date` = enrollment start, `effective_end_date=NULL` |
| Absences | none |

**Expected GUI behavior:** schedule generates for every weekday in
the current month. Bread-and-butter sandbox.

### `missing_data`

Three members, each missing one piece of required data:

| ID | Name | What's missing | Expected failure reason |
| --- | --- | --- | --- |
| 99002 | "NoEnroll, Bob" | Enrollment row | `not enrolled during {YYYY-MM}` |
| 99003 | "NoAuth, Carol" | Authorization row | `no active authorization for {YYYY-MM}` |
| 99004 | "Absent, Dave" | Full setup PLUS one Absence covering `M1`–`MLAST` | `absent for the entire month` |

**Expected GUI behavior:** all three appear under the "eligibility"
stage in the run-summary failures block. Tests every eligibility
failure path in one run.

### `mid_period_change`

**Center 99005 "Switch, Eve"** — HOF, NYC.

- Enrollment: started 1 year ago, open-ended.
- TWO Authorization rows sharing `auth_start=M1`, `auth_end=MLAST`:
  - Row 1: `effective_start=M1`, `effective_end=M15`, `auth_days="1,3,5"` (M/W/F)
  - Row 2: `effective_start=M15+1`, `effective_end=MLAST`, `auth_days="2,4"` (T/Th)
- No availability rules, no absences.

**Expected GUI behavior:** first half of month — M/W/F have times,
T/Th blank. Second half — T/Th have times, M/W/F blank. Tests the
per-day picker honoring `effective_start`/`effective_end` and the
most-recent-wins logic.

### `plan_full`

Five HOF members for testing plan-mode batch generation:

| ID | Name | Setup | Outcome |
| --- | --- | --- | --- |
| 99010 | "Plan, Alice" | Happy path | Workbook written |
| 99011 | "Plan, Bob" | Happy path | Workbook written |
| 99012 | "Plan, Carol" | Happy path | Workbook written |
| 99013 | "Plan, Dave" | Happy path EXCEPT no Authorization row | Failure: `no active authorization for {YYYY-MM}` |
| 99014 | "Plan, Eve" | Happy path PLUS Tuesday availability narrowed to `12:00`–`14:00` (narrower than the 3.5-hour session minimum) | Workbook written; every Tuesday is blank |

**Expected GUI behavior:** Run with "Entire Plan: HOF" — produces 4
successful workbooks, one failure row in the summary, and one
workbook with all Tuesdays blank. Exercises plan-mode and the most
common partial-failure paths.

## Address Choice

All scenarios use one NYC address (`"123 Test St, New York, NY 10001"`)
so the Google Routes call still resolves. If the developer's
`geo_cache.json` already contains a geocode for that address, no API
hits at all during testing. The address is intentionally a real,
geocodable street name in Manhattan to keep travel-time math sane.

## Edge Cases & Error Handling

| Situation | Behavior |
| --- | --- |
| `--source` file doesn't exist (e.g., not on VPN) | Print a clear "source not found" message naming the missing path. Exit 2. Don't create a half-empty target. |
| Target directory (`test_dbs/`) doesn't exist | `os.makedirs(..., exist_ok=True)` before the copy. Created automatically. |
| Target file exists and is locked (Access GUI has it open) | `pyodbc.connect` raises; print "Close Access if you have the test DB open" and exit 1. No copy attempt. |
| Target file exists and is NOT locked | Skip the copy. Open via pyodbc, run `DELETE FROM` on each of the five data tables, run the seed. This is the reset path. |
| Target file does NOT exist | `shutil.copy2(source, target)` first, then open + truncate + seed. |
| `DELETE FROM` fails for a table that doesn't exist | Print a message naming the missing table and pointing at [docs/database.md](../../database.md). Exit 1. The new code can't run against a too-old DB anyway. |
| `--use` writes to `bsca_settings.json` | Use the existing `gui.app_settings.load()` / `save()` round-trip so every other key is preserved. Only mutates `db_path`. |
| Synthetic IDs (99001–99099) collide with real IDs | Real IDs are ≤ 7 digits; collision is implausible. The truncate step removes anything stale anyway. No special handling. |
| Date math depends on `date.today()` at script time | The seed dates are baked in at create-time. If the developer creates the test DB on May 31 and runs the GUI on June 1, the seeded data may still target May. They'd re-run the script to retarget. Acceptable for a sandbox. |

## Out of Scope (YAGNI)

- Unit tests for the script. Running it IS the test; the GUI run is
  the verification. Adding pytest coverage would be circular.
- A `--list-scenarios` flag. The `--help` output lists them via
  argparse's `choices=` mechanism.
- Programmatic schema verification before truncating. If the schema
  is wrong, `DELETE FROM` will fail with a clear pyodbc error.
- A "use prod" command. Pointing back at prod is a manual
  Settings-dialog edit (or a one-line JSON change). Avoiding
  introducing a separate "production mode" semantic.
- Cross-platform support. Access ODBC is Windows-only and so is the
  rest of the app. The script makes no attempt to run elsewhere.

## What Changes In Code

New:
- `scripts/__init__.py`
- `scripts/make_test_db.py`

Modified:
- `.gitignore` (add `test_dbs/`)

No changes to:
- `monthly_schedule/*`
- `gui/*` (the GUI uses the existing settings file mechanism unchanged)
- `new_monthly_schedule.py`
- Tests
