# BSCA

Tools for Bowery Senior Care Inc member data: a Qt6 desktop GUI and a
Python CLI for generating printable monthly schedule workbooks, plus a
PowerShell lookup script.

## Run the GUI

Easiest: launch the pre-built Windows executable.

```
dist\MonthlyScheduleGenerator.exe
```

Or from source. On Windows this batch file sets up the venv on first
run, then launches the GUI:

```
run.bat
```

Manual launch (assumes `.venv` exists and `requirements.txt` is
installed):

```
.venv\Scripts\python.exe gui.py
```

First launch shows a Settings dialog asking for paths to the Access
DB, output folder, Google Maps config, and travel-cache JSON. Change
them later via the ⚙ button. A combo in the top bar toggles between
English and 简体中文.

A run produces one workbook per member into the configured output
folder. The summary at the bottom of the window lists any failures —
members who couldn't be scheduled either because they lack the
required supporting-table rows (no Enrollment, no active
Authorization, or are absent for the whole month) or because schedule
generation hit an error (travel-time resolution, file write, etc.).

## CLI: `new_monthly_schedule.py`

Generates the same workbooks the GUI does. Select members one of three
ways (exactly one required):

```
# single member
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5

# explicit list
python new_monthly_schedule.py --center-ids 24010,24011 --year 2026 --month 5

# every member on an MLTC plan code
python new_monthly_schedule.py --plan HOF --year 2026 --month 5
```

Options:

- `--output-path DIR` — base output directory (default `.`). Single
  and list modes write `DIR/Schedule_<id>_<YYYY-MM>.xlsx`; `--plan`
  writes into `DIR/<CODE>_<YYYY-MM>/`.
- `--db-path PATH` — Access DB path (default the BOWERY3 share).
- `--google-config PATH` — file containing the Google Maps API key
  (default `google_maps.config`, gitignored). Required: Pick-Up /
  Drop-Off use a Google Routes drive-time estimate.
- `--geo-cache PATH` — local JSON cache of geocoded coords + route
  minutes (default `geo_cache.json`, gitignored).

Full examples (run from the repo root, with `google_maps.config` in
place):

```
# One member -> .\out\Schedule_24010_2026-05.xlsx
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5 --output-path .\out

# Several members by id, all into .\out
python new_monthly_schedule.py --center-ids 24010,24011,24015 --year 2026 --month 5 --output-path .\out

# Every member on a plan -> .\out\HOF_2026-05\Schedule_<id>_2026-05.xlsx
python new_monthly_schedule.py --plan HOF --year 2026 --month 5 --output-path .\out

# Custom key + cache locations
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5 --output-path .\out --google-config C:\keys\gmaps.config --geo-cache .\out\geo_cache.json
```

Pick-Up = Arrival − T and Drop-Off = Departure + T, where T is the
estimated car-drive minutes from the member's address to a fixed
default location. Coordinates come from the Contacts `Long Lat`
column, else the local cache, else the Google Geocoding API. A
member whose travel time cannot be resolved (no coords/address, or
an API error) is skipped and listed in the run summary. See
`docs/superpowers/specs/2026-05-18-travel-time-offsets-design.md`.

A batch run continues past a failing member and prints a summary to
stderr (`Wrote N of M ... ; K failed.` plus an itemized `Failures:`
block). Exit code is `0` on full success, `2` if any member failed or
a plan matched nobody, `1` on a DB / driver error.

The Microsoft Access ODBC driver must match the Python interpreter's
bitness.

## Database schema

The scheduler reads from five Access tables: `Contacts` plus the four
supporting tables `Enrollment`, `Authorization`, `Absences`, and
`Availability`. A member gets scheduled when an Enrollment row covers
the month, an Authorization row's effective window covers the target
date and lists the right weekday, no Absence row blocks that day, and
any Availability rule for that weekday leaves a wide-enough arrival
window. See [`docs/database.md`](docs/database.md) for the full schema
reference and per-day eligibility flow.

## Testing the GUI safely

`scripts\make_test_db.py` creates or resets an Access test DB so you
can exercise the GUI without touching production data. Each scenario
gets its own gitignored `test_dbs/<scenario>.accdb`. Re-running the
same command resets the DB back to its seeded state.

```
# happy_path: one fully set-up member, every weekday filled
python scripts\make_test_db.py --scenario happy_path --use

# missing_data: three members, one each missing Enrollment, Authorization,
# or with an absence covering the whole month — exercises all three
# eligibility-stage failure reasons
python scripts\make_test_db.py --scenario missing_data --use

# mid_period_change: one member, two Authorization rows carving up
# the month with different auth_days each half
python scripts\make_test_db.py --scenario mid_period_change --use

# plan_full: five HOF members — three happy, one missing auth, one
# with a Tuesday availability window too tight for the session minimum
python scripts\make_test_db.py --scenario plan_full --use

# populate_real_members: keep the real Contacts intact, seed the four
# supporting tables against every real Center ID — ~90% happy,
# ~10% deliberate failures spread across all three failure reasons
python scripts\make_test_db.py --scenario populate_real_members --use
```

`--use` flips `bsca_settings.json` so the GUI immediately picks up the
test DB on next launch. Drop `--use` if you just want to create the
file without changing the GUI's pointer.

To switch back to production, edit the DB path via the GUI's Settings
dialog (⚙ button) or by editing `bsca_settings.json` directly. Full
design in
[`docs/superpowers/specs/2026-05-27-test-db-script-design.md`](docs/superpowers/specs/2026-05-27-test-db-script-design.md).

## Build the standalone `.exe`

```
.venv\Scripts\pyinstaller.exe MonthlyScheduleGenerator.spec --noconfirm
```

Produces `dist\MonthlyScheduleGenerator.exe`.

## `Get-Contact.ps1`

Interactive PowerShell lookup of a member by Center ID:

```
pwsh ./Get-Contact.ps1 -CenterID 24010
```

## Create supporting tables

One-shot DDL bootstrap. Given a fresh `.accdb` whose only table is
`Contacts`, this script issues `CREATE TABLE` for the four
supporting tables `Enrollment`, `Authorization`, `Absences`, and
`Availability`, including the `[Health Plan]` column on
`Authorization` from the get-go.

```
python scripts\create_supporting_tables.py --db <PATH> [--quiet]
```

No data is written. After this run succeeds, populate the new
tables with the backfill scripts below
(`backfill_availability_from_hha.py`,
`backfill_authorization_from_contacts.py`). The script fails
loudly if any of the four tables already exists — drop the
offending tables in Access and re-run. The expected column lists
are in [`docs/database.md`](docs/database.md).

## Backfill Availability from HHA notes

One-shot script that parses the free-text `Contacts.HHA` column and
writes the resulting end-of-day constraints to the `Availability`
table. Rows that contain time content but can't be safely
auto-interpreted (morning HHA, midday splits, date-conditioned
entries, free-text notes) are emitted to a dated CSV for human
review; rows with no time content are silently ignored.

```
python scripts\backfill_availability_from_hha.py --db <PATH> [--dry-run] [--csv-out DIR] [--quiet]
```

Assumes the center is open 08:00–16:00. An HHA window starting
mid-afternoon (e.g. `(4.5.6) 2:30-7pm` → Thu/Fri/Sat) becomes that
day's `avail_end`; windows fully after 16:00 produce no constraint.
`--dry-run` parses, writes the CSV, and rolls back the DB
transaction. The upsert is idempotent and only ever moves
`avail_end` earlier — re-running never widens a previously
shortened window. The ambiguous CSV lands at
`<csv-out>/hha_backfill_ambiguous_<YYYY-MM-DD>.csv` (utf-8-sig so
Excel renders CJK correctly). Full design in
[`docs/superpowers/specs/2026-06-01-hha-availability-backfill-design.md`](docs/superpowers/specs/2026-06-01-hha-availability-backfill-design.md).

## Backfill Authorization from Contacts

One-shot script that aligns the `Authorization` table with
`Contacts` in two ways:

1. For every Contact whose Authorization rows already exist, fills
   any blank `Health Plan` column with the value from
   `Contacts.[Health Plan]`. Non-blank values are left alone —
   Authorization is the going-forward source of truth.
2. For every Contact with no Authorization row, inserts one from
   the legacy Contacts columns `SADC` → `auth_days`,
   `Auth BGN`/`Auth EXP` → `auth_start`/`auth_end` (and the
   matching `effective_*` pair), and `Health Plan`.

Members with missing source data are emitted to a dated CSV for
human review.

```
python scripts\backfill_authorization_from_contacts.py --db <PATH> [--dry-run] [--csv-out DIR] [--quiet]
```

`--dry-run` runs the full pass, writes the CSV, then rolls back
the DB transaction so the operator can preview without
committing. The skipped CSV lands at
`<csv-out>/auth_backfill_skipped_<YYYY-MM-DD>.csv` (utf-8-sig so
Excel renders CJK correctly). Full design in
[`docs/superpowers/specs/2026-06-02-authorization-backfill-design.md`](docs/superpowers/specs/2026-06-02-authorization-backfill-design.md).

## Setup

```
python -m pip install -r requirements.txt
```

Then provide a Google Maps API key (used for geocoding + Routes).
Copy the template and replace the single line with your real key:

```
copy google_maps.config.example google_maps.config
```

`google_maps.config` is gitignored. The file's entire contents (the
one line, trimmed) are used as the key — no comments. Point
`--google-config PATH` elsewhere if you keep the key file at another
location.

## Run tests

```
.venv\Scripts\pytest -v
```

Design docs and specs live under [`docs/superpowers/specs/`](docs/superpowers/specs/);
implementation plans under [`docs/superpowers/plans/`](docs/superpowers/plans/).
