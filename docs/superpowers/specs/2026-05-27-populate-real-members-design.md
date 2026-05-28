# `populate_real_members` Scenario

**Date:** 2026-05-27
**Status:** Approved (pending spec review)
**Scope:** A fifth scenario added to [scripts/make_test_db.py](../../../scripts/make_test_db.py) that preserves the real Contacts table and seeds the four supporting tables against the existing Center IDs, with a small sprinkle of intentional failures.

## Goal

Let the developer manually exercise the GUI against realistic data volume — every real member gets a happy-path setup so plan-mode batch generation produces real-looking output, with a deterministic 10% sprinkle of failures so the run-summary failures block is also exercised.

## Why It's Different From the Existing Scenarios

The existing `happy_path` / `missing_data` / `mid_period_change` / `plan_full` scenarios all **replace** Contacts with synthetic test members (Center IDs in the 99000s). This new scenario **keeps** the real Contacts intact and only seeds the four supporting tables against those real Center IDs. That means the truncation step needs to be scenario-aware — Contacts must be preserved for this one.

## Design Decisions (Recap From Brainstorming)

| Decision | Choice |
| --- | --- |
| Integration | New fifth scenario in `scripts/make_test_db.py`, not a separate script |
| Data variety | ~90% happy-path + 10% sprinkled failures, one of each failure type |
| Truncation hook | Per-scenario via `SCENARIOS_KEEP_CONTACTS` set; `_truncate_all` becomes `_truncate(conn, tables)` |
| Plan filter | None — seed every Contacts row regardless of `Health Plan` |
| Failure distribution | Deterministic by sorted-Center-ID index: every 10th, 20th, 30th in a 30-cycle |

## Refactor (Section 1)

Two surgical changes to `scripts/make_test_db.py`:

1. Split `DATA_TABLES` into two:
   ```python
   SUPPORTING_TABLES = ("Availability", "Absences", "Authorization", "Enrollment")
   DATA_TABLES = SUPPORTING_TABLES + ("Contacts",)
   ```
2. Add a set of scenarios that preserve Contacts (just the new one for now):
   ```python
   SCENARIOS_KEEP_CONTACTS = {"populate_real_members"}
   ```
3. Rename `_truncate_all(conn)` → `_truncate(conn, tables)` (takes the list explicitly).
4. In `main()`, choose the truncate list:
   ```python
   truncate_tables = (
       SUPPORTING_TABLES if args.scenario in SCENARIOS_KEEP_CONTACTS
       else DATA_TABLES
   )
   _truncate(conn, truncate_tables)
   ```

The existing four scenarios are not touched — they still see all five tables truncated, since they're not in `SCENARIOS_KEEP_CONTACTS`. The new scenario is added to the `SCENARIOS` dict alongside the existing four.

## Seeded Data (Section 2)

The scenario function reads `[Center ID]` from Contacts (ascending sort, deterministic), then iterates. For each `(idx, center_id)` the variant is selected by `idx % 30`:

| `idx % 30` | Variant | Tables seeded | Expected GUI behavior |
| --- | --- | --- | --- |
| `9` | **No Authorization** | Enrollment + Availability | Fails: `no active authorization for this month` |
| `19` | **Absent entire month** | Enrollment + Authorization + Availability + Absence (M1→MLAST) | Fails: `absent for the entire month` |
| `29` | **No Enrollment** | Authorization + Availability | Fails: `not enrolled during this month` |
| any other | **Happy path** | Enrollment + Authorization + 5 Availability rows | Schedule generates for every weekday |

Out of every 30 members: 27 happy + 3 failures (one of each kind). ≈90% happy / ≈10% failures total.

### Happy-path defaults (per member)

Identical shape to the existing `seed_happy_path` scenario, just iterated:

| Table | Inserted row(s) |
| --- | --- |
| Enrollment | `start_date = first day of (today.month, today.year − 1)`, `end_date = NULL` |
| Authorization | `auth_start = M1`, `auth_end = MNEXT_LAST`, `effective_start = M1`, `effective_end = MNEXT_LAST`, `auth_days = "1,2,3,4,5"` |
| Availability | 5 rows, one per weekday (`Day Of Week ∈ {1..5}`), `avail_start = 08:00`, `avail_end = 16:00`, `effective_start_date = enrollment start`, `effective_end_date = NULL` |

### Failure variants

- **No Authorization (`idx % 30 == 9`):** Insert Enrollment and the 5 Availability rows; **skip** the Authorization INSERT.
- **Absent entire month (`idx % 30 == 19`):** Insert everything from the happy path AND one Absence row: `Leave Type = "Vacation"`, `Start_Date = M1`, `End_Date = MLAST`.
- **No Enrollment (`idx % 30 == 29`):** Insert Authorization and 5 Availability rows; **skip** the Enrollment INSERT.

### Per-table `Center ID` conversion (mirrors existing scenarios)

| Table | Type | Conversion |
| --- | --- | --- |
| Enrollment | INTEGER | `int(center_id)` |
| Authorization, Absences, Availability | VARCHAR | `str(int(center_id))` |

## Operational Details (Section 3)

| Situation | Behavior |
| --- | --- |
| Contacts empty | Seed does nothing. Print `Seeded populate_real_members: 0 happy / 0 no-auth / 0 absent / 0 no-enrollment (0 members total)` so the empty result is visible. |
| Contacts has NULL Center IDs | Skip those rows (can't seed against a NULL FK). Print a one-line warning naming the count if any were skipped. |
| Contacts.Center ID is DOUBLE (float from pyodbc) | Cast to `int` once and reuse: `int` for Enrollment, `str(int(...))` for the three VARCHAR-keyed tables. |
| INSERT volume | ~7 inserts per happy member, ~6 per failure member. For 100 members that's roughly 700 statements; finishes in seconds. No batching needed. |
| End-of-run summary | Print one line: `Seeded populate_real_members: <H> happy / <A> no-auth / <B> absent / <E> no-enrollment (<T> members total)`. Lets the user confirm the mix at a glance. |
| Plan picked in GUI has no members | Existing GUI handles it — `No members found for plan {code}`. No change here. |
| Re-run | Truncate the four supporting tables and reseed. Contacts is preserved. Idempotent. |
| Date drift | Same as the other scenarios — dates are baked in at script-run time. If `today` rolls past the seeded auth window, re-run to retarget. |

## CLI Examples

```powershell
# First-time: create test_dbs/populate_real_members.accdb (copies prod),
# seed the four tables for every Contacts member, and point the GUI at it.
python scripts\make_test_db.py --scenario populate_real_members --use

# Reset the same DB back to a known state without re-copying.
python scripts\make_test_db.py --scenario populate_real_members
```

## Out of Scope (YAGNI)

- Configurable failure frequency / cycle ratio (`--every N`, `--no-failures`). Hardcode the 30-cycle for now; revisit if the manual flow demands more knobs.
- Per-plan filtering at seed time. The script seeds everyone; the GUI's plan picker filters at run time.
- Variations within the happy path (different availability windows per member, different auth periods). Uniform happy-path keeps manual verification predictable.
- Tests. Per the existing `make_test_db.py` spec, running the script IS the test. The end-of-run summary line lets the developer eyeball the result.

## What Changes In Code

Modified:
- `scripts/make_test_db.py`:
  - Replace `DATA_TABLES = ...` with the `SUPPORTING_TABLES + (Contacts,)` split.
  - Add `SCENARIOS_KEEP_CONTACTS = {"populate_real_members"}`.
  - Rename `_truncate_all(conn)` → `_truncate(conn, tables)`; update its single call site in `main()`.
  - Add `seed_populate_real_members(conn, today)`.
  - Register the new scenario in the `SCENARIOS` dict.

No changes to:
- Existing four scenario functions.
- `gui/`, `monthly_schedule/`, `new_monthly_schedule.py`.
- Tests (no test files needed per the parent spec).
