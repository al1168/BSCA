# Scripts

Operational scripts for setting up and maintaining the BSCA Access
database. Run each from the repo root with the project venv's
Python interpreter (`.venv\Scripts\python.exe`).

For the full design behind each one, see the linked spec in
[docs/superpowers/specs/](../docs/superpowers/specs/). For the
database schema reference, see [docs/database.md](../docs/database.md).

## What each script does

| Script | Purpose |
| --- | --- |
| [`create_supporting_tables.py`](create_supporting_tables.py) | DDL bootstrap. Issues `CREATE TABLE` for the five supporting tables (`Enrollment`, `Authorization`, `Absences`, `Availability`, `OneOffAvailability`) on an `.accdb` that already contains `Contacts`. No data is written. |
| [`backfill_authorization_from_contacts.py`](backfill_authorization_from_contacts.py) | Aligns the `Authorization` table with `Contacts`: fills blank `[Health Plan]` on existing rows, and inserts one new row per Contact-with-no-authorization from the legacy `SADC` / `Auth BGN` / `Auth EXP` / `Health Plan` columns. Skipped members go to a dated CSV. |
| [`backfill_availability_from_hha.py`](backfill_availability_from_hha.py) | Parses the free-text `Contacts.HHA` column and writes end-of-day constraints to the `Availability` table. Ambiguous rows (morning HHA, midday splits, date-conditioned entries) go to a dated CSV for human review. |
| [`audit_sadc.py`](audit_sadc.py) | Read-only audit. Lists every distinct `Contacts.[SADC]` value with its member count and what the current SADC parser produces. Writes a dated CSV with an empty `expected_output` column for the operator to fill in by hand. Used to surface SADC notation variants (e.g. `1.2.3->2.4`, `1.2.3(9am-1pm)`) before changing the parser. |
| [`add_one_off_availability_table.py`](add_one_off_availability_table.py) | Idempotent DDL migration. Adds the `OneOffAvailability` table to an existing `.accdb` that already has the original four supporting tables. Safe to run repeatedly: skips with a friendly message if the table already exists. |
| [`make_test_db.py`](make_test_db.py) | Creates or resets a gitignored test `.accdb` seeded with one of several scenarios (`happy_path`, `missing_data`, `mid_period_change`, `plan_full`, `populate_real_members`). Used to exercise the GUI without touching prod. |

Run `audit_sadc.py` whenever you suspect the SADC parser is
mis-handling a notation variant in production. The CSV it writes
(`sadc_audit_<YYYY-MM-DD>.csv`) is the spec input for any future
parser change — fill in `expected_output` for the rows you want to
correct, then hand the CSV back to drive the update.

## Migration steps for a new DB

If you have an `.accdb` whose only table is `Contacts` and you want
to bring it up to the full schema with all supporting tables
populated, run these in order:

```
# 1. Create the five supporting tables (empty).
python scripts\create_supporting_tables.py --db <PATH>

# 2. Backfill Authorization — preview first, then apply.
python scripts\backfill_authorization_from_contacts.py --db <PATH> --dry-run
python scripts\backfill_authorization_from_contacts.py --db <PATH>

# 3. Backfill Availability from HHA notes — preview, then apply.
python scripts\backfill_availability_from_hha.py --db <PATH> --dry-run
python scripts\backfill_availability_from_hha.py --db <PATH>
```

After step 1 you have empty supporting tables. After step 2, every
Contact has at least one Authorization row with `[Health Plan]`
filled. After step 3, members whose `Contacts.HHA` text describes
an end-of-day constraint have matching Availability rows.

After step 3, you have a fully migrated database. The
`OneOffAvailability` table starts empty; there is no backfill
script for it (no legacy source).

If your `.accdb` was created **before** the `OneOffAvailability`
table existed, run the standalone migration to add it without
re-creating the other tables:

    python scripts\add_one_off_availability_table.py --db <PATH>

The script is idempotent — running it on a DB that already has the
table prints "already exists" and exits 0.

Each backfill drops a CSV next to the run that lists members it
couldn't process — review those, fix the offending Contacts row,
and re-run. Both backfills are idempotent (only-fill-blanks / only-shorten).

## Common flags

| Flag | Used by | Effect |
| --- | --- | --- |
| `--db PATH` | all five | Path to the Access `.accdb`. Required. |
| `--dry-run` | both backfills | Run the full pass, write the CSV, then `rollback()` instead of `commit()`. Use this first against any DB you care about. |
| `--csv-out DIR` | both backfills | Directory for the skipped/ambiguous CSV (default `.`). |
| `--quiet` | all except `make_test_db.py` | Suppress per-row stdout; the run summary still prints. |
| `--scenario NAME` | `make_test_db.py` | Which seed scenario to apply. |
| `--use` | `make_test_db.py` | After seeding, flip `bsca_settings.json` so the GUI immediately picks up the new test DB. |

## Exit codes

- `0` — clean run (skipped members are reported via the CSV, not via the exit code).
- `2` — DB path doesn't exist, or the Microsoft Access ODBC driver fails to open it (check that the driver's bitness matches your Python interpreter).
