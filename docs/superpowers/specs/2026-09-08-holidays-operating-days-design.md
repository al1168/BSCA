# Holidays and Operating Days

Date: 2026-09-08

## Goal

Let the center record company holidays and its weekly operating hours in
the Access database, and have the monthly scheduler honor both: no times
are generated on a holiday or on a weekday the center is closed, and the
hard day bounds (earliest Time-In, latest Time-Out) come from that
weekday's opening and closing times instead of the Settings dialog.

Staff enter holidays and hours through a new **Company Calendar** dialog
in BSCA Member Manager (the sibling repo, `BSCA-Members`). That side is
specified in
`BSCA-Members/docs/superpowers/specs/2026-09-08-company-calendar-design.md`;
this document covers the tables, the Setup chain, and the scheduler.

## Decisions

- **OperatingDays wins per weekday.** Its opening/closing times replace
  the plan rules' `earliest_time_in` / `latest_time_out`. The two
  Settings fields are removed from the Monthly Schedule Generator's
  Settings dialog so there is one place to edit hours. The built-in
  08:00–16:00 in `monthly_schedule/rules.py` stays as the code default
  used by tests and by callers that pass no calendar.
- **Closed days look like non-authorized weekdays.** A holiday or closed
  weekday is blank on the timesheet, blank on the activity log, and
  absent from the billing sheet's Remark column. It is *not* an absence.
- **A weekday with no OperatingDays row is closed.** The table holds at
  most one row per weekday. "Deleting the day" in the dialog removes the
  row.
- **Data hygiene: unusable rows read as closed.** An OperatingDays row
  with a missing time, or a closing time at or before its opening time,
  is ignored, so that weekday is closed rather than generating sessions
  outside the center's hours. A range where every attendable day is
  closed gets its own skip reason, so staff look at the calendar
  instead of hunting for an enrollment problem.
- **Missing tables fail the run**, exactly like the other supporting
  tables. Re-running the Setup GUI (idempotent) creates them. The
  Members app lists them in its startup schema warning.

## 1. Database tables

Both tables are created by `scripts/create_supporting_tables.py` (two
new entries in `_DDLS`; the "already exists" skip applies as usual).

### Holidays

| Field | Type | Notes |
| --- | --- | --- |
| ID | AUTOINCREMENT PK | |
| holiday_name | TEXT(255) | e.g. `Labor Day`. |
| date | DATETIME | The single closed date (date part only). A multi-day closure is one row per day. |

Semantics: day `D` is a holiday iff any row's `date` equals `D`.
Duplicate dates are allowed and harmless.

### OperatingDays

| Field | Type | Notes |
| --- | --- | --- |
| ID | AUTOINCREMENT PK | |
| day_name | TEXT(20) | `Monday` … `Sunday`, for readability in Access. |
| Day Of Week | LONG | 1 = Monday … 7 = Sunday, the same convention as `Availability.[Day Of Week]`. The scheduler matches on this column, never on `day_name`. |
| opening_time | DATETIME | Time-of-day only (stored as `1899-12-30 HH:MM`, like `Availability.avail_start`). |
| closing_time | DATETIME | Same. Must be later than `opening_time`. |

Semantics: weekday `W` is open iff a row with `[Day Of Week] = W`
exists. If more than one row exists for a weekday (hand edits in
Access), the one with the largest `ID` wins.

### Setup step: seed_operating_days

New script `scripts/seed_operating_days.py`, registered in
`setup_gui/setup_worker.py`'s `SETUP_STEPS` immediately after
`create_supporting_tables`. It takes `--db PATH`, and:

- if `OperatingDays` has zero rows, inserts the seven default rows
  (Monday…Sunday, 08:00–16:00) and prints `Seeded 7 operating days`;
- otherwise prints `OperatingDays already has N rows; left unchanged`
  and returns 0.

It never overwrites edits, so re-running Setup is safe.

`docs/database.md` gets a section for each table and drops the sentence
under Absences that says center-wide closures are entered as one
Absence per member. `scripts/README.md` lists the new script.

## 2. Scheduler

### 2a. Fetching (`monthly_schedule/db.py`)

- `get_holidays(db_path) -> list[dict]` with keys `id`, `name`, `date`
  (a `datetime.date`).
- `get_operating_days(db_path) -> list[dict]` with keys `id`,
  `day_of_week` (int), `opening_time`, `closing_time` (both `'HH:MM'`,
  via the existing `_datetime_to_hhmm`).

Both use `_fetch_all_unfiltered`. A missing table raises the same
`pyodbc.Error` path as any other missing table.

### 2b. `CenterCalendar` (new module `monthly_schedule/center_calendar.py`)

```python
class CenterCalendar:
    def __init__(self, holidays, operating_days): ...
    def closed_reason(self, day) -> tuple | None
    def rules_for(self, day, plan_rules) -> dict
```

- `closed_reason(day)` returns a 2-tuple or `None`: `("holiday", name)`
  when `day` is in Holidays, `("weekday", None)` when its weekday has
  no OperatingDays row, else `None`. Holidays are checked first so the
  debug wording names the holiday even on an otherwise-closed weekday.
- `rules_for(day, plan_rules)` returns a shallow copy of `plan_rules`
  with `earliest_time_in` and `latest_time_out` replaced by the
  weekday's `opening_time` / `closing_time`. On a closed day it returns
  `plan_rules` unchanged (the caller never generates times for it).
- `CenterCalendar.always_open()` classmethod: no holidays, no
  OperatingDays rows, and `rules_for` returns `plan_rules` unchanged.
  Used when `calendar` is omitted, so existing tests and the audit
  script keep their behavior.

### 2c. Eligibility (`monthly_schedule/per_day.py`)

New constant `REASON_DAY_CENTER_CLOSED = "center closed on this day"`.

`compute_day_eligibility(day, ctx, plan_rules, calendar=None)` runs, in
order:

1. enrolled (unchanged)
2. active authorization (unchanged)
3. **center open** — if `calendar.closed_reason(day)` is not `None`,
   return `DayEligibility(eligible=False, reason=REASON_DAY_CENTER_CLOSED)`
4. authorized weekday (unchanged)
5. one-offs / absence / availability window (unchanged)

`compute_day_eligibility` uses `calendar` only for step 3. Step 5 reads
`earliest_time_in` / `latest_time_out` from the `plan_rules` it is
given, exactly as today; the per-weekday substitution happens once, in
`rows.py`, which passes the rewritten `day_rules` (see 2d). When
`calendar` is `None`, step 3 is skipped.

`compute_month_failure(year, month, ctx, ..., calendar=None)` treats a
closed day like a wrong weekday: it is neither schedulable nor
unblocked. So a member authorized only on a weekday the center never
opens is skipped with `REASON_NO_ELIGIBLE_DAYS`.

### 2d. Rows and debug (`monthly_schedule/rows.py`)

`build_rows(...)` and `build_debug_rows(...)` accept `calendar=None`
(defaulting to `CenterCalendar.always_open()`). For every day they call
`day_rules = calendar.rules_for(day, plan_rules)` and pass `day_rules`
to `compute_day_eligibility` and `build_daily_schedule`. The
`plan_default_window` used by the time-cache invalidation guard is
computed from `day_rules` per day, so a changed opening time
invalidates cached times for that weekday only. Closed days get
`status = "ineligible"` (blank everywhere, per the decision above).

Debug CSV wording (`_simple_reason`):

- holiday: `Center closed (Labor Day)`
- closed weekday: `Center closed on Sundays`

`_simple_reason` gains a `closed` argument carrying the calendar's
`closed_reason` tuple.

### 2e. Callers

`gui/worker.py`, `new_monthly_schedule.py`, and
`scripts/audit_enrollment_gate.py` each fetch holidays and operating
days once per run, build one `CenterCalendar`, and pass it to
`build_rows`, `build_debug_rows`, and `compute_month_failure`. The
`MemberContext` class is unchanged.

### 2f. Settings dialog

`gui/settings_dialog.py` drops the earliest Time-In and latest Time-Out
rows; `gui/app_settings.py` drops the two keys from the default
`schedule_rules`. Old settings files that still contain them load fine:
the loader drops unknown rule keys. The i18n table entries for the two
labels are removed.

### 2g. Test DB scaffold

`scripts/make_test_db.py` creates both tables (importing the two DDL
constants) and seeds the seven default OperatingDays rows in every
scenario, so GUI scenario runs behave as before. `seed_happy_path`
additionally adds one holiday on a weekday inside the target month so
the scenario visibly exercises the feature.

## 3. Members app

See `BSCA-Members/docs/superpowers/specs/2026-09-08-company-calendar-design.md`.
Summary: a "🏢 Company Calendar" toolbar button opens a dialog with a
Holidays list (add/delete, immediate writes) and a seven-row
Operating Days editor (Open checkbox + opening/closing times, saved in
one transaction). Both tables join `REQUIRED_SCHEMA`.

## 4. Testing

BSCA repo (pytest, existing style):

- `tests/test_center_calendar.py`: holiday lookup, closed weekday,
  holiday-on-closed-weekday precedence, `rules_for` substitution and
  the always-open fallback, largest-ID-wins on duplicate weekday rows.
- `tests/test_per_day.py`: closed day rejected before the weekday
  check; open day uses the weekday's bounds; month failure counts closed
  days as unschedulable.
- `tests/test_rows.py`: closed day is blank with status `ineligible`;
  debug wording for both closed kinds; cache guard invalidates when a
  weekday's hours change.
- `tests/test_db.py`: mapping of the two new fetches (mocked cursor,
  as the existing fetch tests do).
- `tests/test_create_supporting_tables.py`: both DDLs present.
- `tests/test_seed_operating_days.py`: seeds seven rows into an empty
  table; no-op on a populated table; `--db` missing returns 2.
- `tests/test_setup_worker.py`: step list includes the seed step in
  the right position.
- `tests/test_settings_dialog.py` / `tests/test_app_settings.py`:
  the two fields are gone; a legacy settings file still loads.

After the code lands, rebuild the packaged exes (`dist\`) for both the
scheduler and the Setup GUI, per the usual workflow.
