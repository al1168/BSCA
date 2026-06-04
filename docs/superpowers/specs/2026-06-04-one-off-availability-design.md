# One-off availability — design

## Goal

Add a new supporting table `OneOffAvailability` so staff can record
single-day exceptions to a member's recurring availability without
removing the day from the schedule. Example: a member has a doctor
appointment 8:00–12:00 on 2026-06-05, so the scheduler should generate
their visit inside a 12:00–16:00 window for that one day instead of
their normal weekly availability.

The scheduler treats one-off rows as **higher priority than**
recurring `Availability` rows and **distinct from** `Absences`:

- One-off present, no conflict → that day uses the one-off window,
  the recurring weekly rule is ignored for that day.
- One-off present, conflict with absence / authorization / enrollment /
  duplicate row → the member is added to the run's flagged list and a
  conflict CSV row is written.
- No one-off → behavior is unchanged.

## Out of scope

- One-offs that **widen** availability (e.g., "available Saturday even
  though Sat is not in the weekly schedule"). One-offs may only
  narrow the window for a day on which the member is already
  authorized.
- Per-day overrides of pickup address, center, or route.
- A GUI editor for `OneOffAvailability`. Staff edit the table directly
  in Access, the same way they edit `Availability` and `Absences`
  today.
- Backfill from a legacy source. There is no prior column or sheet
  one-offs come from; the table starts empty.
- Changing the existing semantics of `Availability` rows (recurring
  weekly rules continue to apply on days without a one-off).

## Data model

New Access table, conventions matched to the existing supporting
tables created by [scripts/create_supporting_tables.py](../../../scripts/create_supporting_tables.py):

```sql
CREATE TABLE [OneOffAvailability] (
  [ID] AUTOINCREMENT PRIMARY KEY,
  [Center ID] DOUBLE,
  [date] DATETIME,
  [avail_start] DATETIME,
  [avail_end] DATETIME,
  [Notes] MEMO
)
```

| Column | Notes |
| --- | --- |
| `ID` | Surrogate key, used as the tie-break in conflict-detection. |
| `Center ID` | `DOUBLE` to match the FK convention used by `Authorization`, `Absences`, `Availability`. |
| `date` | The single calendar day this exception applies to. Stored as `DATETIME`; the time portion is ignored on read. |
| `avail_start`, `avail_end` | Time-of-day windows. Stored as `DATETIME` with the 1899-12-30 placeholder date, same as `Availability.avail_start`/`avail_end`. Read code reuses [`_datetime_to_hhmm`](../../../monthly_schedule/db.py#L231) to extract `"HH:MM"`. |
| `Notes` | Free-text MEMO. Same shape as the `Notes` column on the other tables. Not read by the scheduler. |

There is no `Day Of Week` column — the weekday is derived from `date`
where needed. There are no `effective_start_date` /
`effective_end_date` columns — a one-off is, by definition, a single
day.

### Why a new table instead of reusing `Availability`

The existing `Availability` table can technically represent a one-off
(set `effective_start_date == effective_end_date`, set `Day Of Week`
to the date's weekday, and the existing tie-break in
[`MemberContext.availability_for`](../../../monthly_schedule/eligibility_context.py#L44)
makes the one-off win over the recurring rule). The reason we add a
separate table anyway:

- The scheduler must distinguish one-offs from recurring rules to
  apply the conflict checks (Section "Conflict checks"). A recurring
  availability + an absence is **normal**; a one-off + an absence is
  a **flagged contradiction**. Encoding that distinction on top of a
  recurring-rule schema requires either a marker column or a brittle
  "single-day window means one-off" heuristic, both of which leave
  the recurring-rule schema mixed-purpose.
- The natural shape is different. A one-off has a `date`; a recurring
  rule has a weekday plus an effective range. Forcing them into one
  schema produces redundant columns (`Day Of Week` equal to the
  date's weekday, `effective_start_date == effective_end_date == date`)
  that the GUI form has to suppress.
- Reporting and auditing are easier when one-offs live in their own
  table.

## Reading the table

New helpers in [monthly_schedule/db.py](../../../monthly_schedule/db.py),
matching the existing `get_availability` / `get_all_availability`
pattern:

```python
ONE_OFFS_QUERY = (
    "SELECT [ID], [Center ID], [date], [avail_start], [avail_end] "
    "FROM [OneOffAvailability] "
    "WHERE [Center ID] = ?"
)

ALL_ONE_OFFS_QUERY = (
    "SELECT [ID], [Center ID], [date], [avail_start], [avail_end] "
    "FROM [OneOffAvailability]"
)

def map_one_off_row(row):
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "date": _to_date(row[2]),
        "avail_start": _datetime_to_hhmm(row[3]),
        "avail_end": _datetime_to_hhmm(row[4]),
    }

def get_one_offs(center_id, db_path): ...
def get_all_one_offs(db_path): ...
```

`get_one_offs` reuses the existing `_fetch_all` helper.
`get_all_one_offs` reuses `_fetch_all_unfiltered` and
`_index_by_center_id`, returning `{center_id: [one_off dicts]}` for the
batch worker modes.

## MemberContext

[`MemberContext`](../../../monthly_schedule/eligibility_context.py)
gains a fifth constructor argument and one lookup method:

```python
def __init__(self, enrollments, authorizations, absences,
             availabilities, one_offs):
    ...
    self._one_offs = list(one_offs)

def one_offs_for(self, day):
    """Return list of one-off rows whose date equals `day`. Empty list
    if none. May contain more than one row — the caller flags the
    duplicate as a conflict."""
    return [r for r in self._one_offs if r["date"] == day]
```

Returning a list (not a single row) is deliberate: detecting the
"two one-offs for the same day" conflict requires seeing all matches,
and the eligibility layer is where conflicts are turned into CSV
rows.

The per-member loops that build `MemberContext` (currently in the
workbook runner) pass `[]` for `one_offs` if the table is empty or
the column lookup found nothing — same shape as the existing
arguments.

## Scheduler integration

[`compute_day_eligibility`](../../../monthly_schedule/per_day.py#L29)
gains a new branch at the top. The one-off lookup runs **before** the
existing enrollment / authorization / absence checks, because when a
one-off is present those conditions become *conflicts to flag* rather
than *silent ineligibility reasons*.

New ordered logic:

1. **`one_offs = ctx.one_offs_for(day)`**.

2. If `one_offs` is non-empty:
   - Run the five conflict checks in order (see "Conflict checks"
     below). First match wins.
   - If any check fails: raise
     `OneOffConflict(center_id, day, reason)`. The caller catches it
     and adds the member to the flagged list.
   - If all checks pass: use the single row's
     `avail_start`/`avail_end` as the day's availability window and
     **skip the recurring availability lookup entirely**. Jump to
     step 4.

3. If `one_offs` is empty: the existing path applies, unchanged.
   - Not enrolled → `DayEligibility(eligible=False)`.
   - No active authorization → `DayEligibility(eligible=False)`.
   - Weekday not in `auth_days` → `DayEligibility(eligible=False)`.
   - `ctx.is_absent(day)` → `DayEligibility(eligible=False)`.
   - Call `ctx.availability_for(day)`. If it returns a row, use that
     window; otherwise the day is eligible with no arrival-window
     narrowing.

4. Intersect the day's availability window (one-off or recurring) with
   the plan's arrival window. If the intersection is empty,
   `DayEligibility(eligible=False)` — no flag. This is the same
   silent-skip behavior the recurring path already has when an
   `Availability` row doesn't intersect the plan.

Conflict propagation is handled one level up, at the per-member loop
in the workbook runner:

```python
try:
    elig = compute_day_eligibility(day, ctx, plan_rules)
except OneOffConflict as exc:
    flagged.append((exc.center_id, exc.day, exc.reason))
    skip_remaining_days_for_this_member()
```

A one-off conflict short-circuits the rest of that member's month.
The member ends up in the "couldn't generate" bucket the run already
produces for `compute_month_failure` reasons, plus a row in the
conflict CSV (Section "CSV output").

## Conflict checks

When `one_offs_for(day)` returns a non-empty list, apply these five
checks in order. **First match wins** — that's the reason carried in
the CSV.

| # | Check | Reason string |
| --- | --- | --- |
| 1 | `len(one_offs) > 1` | `"duplicate one-off rows for {date}"` |
| 2 | The one-off's `date` is not inside any of the member's `Enrollment` windows. | `"one-off on {date} outside enrollment window"` |
| 3 | No active authorization covers `date`. | `"one-off on {date} has no active authorization"` |
| 4 | `date.isoweekday()` is not in the active authorization's `auth_days`. | `"one-off on {date} falls on unauthorized weekday"` |
| 5 | `ctx.is_absent(date)` is True. | `"one-off on {date} conflicts with absence"` |

Order rationale: structural problems (duplicate row) come first,
then the "right to be scheduled" checks in the same order the
existing eligibility logic uses (enrollment → authorization →
weekday), then the absence conflict — which is only meaningful if
the one-off was otherwise valid.

Checks 1 and 5 are unique to one-offs. Checks 2, 3, and 4 are
*re-statements* of conditions that already cause silent ineligibility
in the existing path — they are escalated to flags **only when a
one-off is present**, because the act of entering a one-off implies
the operator believed the member should be scheduled that day, so a
contradiction is worth surfacing.

Check 3 (no active authorization) is added by symmetry with check 2
(outside enrollment window): both mean "the one-off was entered for a
day the member cannot attend." Confirm during user review that this
extra check is desired; if not, drop check 3 and let the no-auth case
fall through to silent ineligibility.

### What is not a conflict

If the one-off's `avail_start`/`avail_end` window does not intersect
the plan's arrival window (e.g., one-off says 12:00–16:00 but the
plan only allows arrival 09:00–11:00), `compute_day_eligibility`
returns `DayEligibility(eligible=False)` without raising. The day is
silently dropped from the schedule. This matches the existing
behavior for non-intersecting recurring `Availability` rows.

### New exception type

In [monthly_schedule/per_day.py](../../../monthly_schedule/per_day.py):

```python
class OneOffConflict(Exception):
    def __init__(self, center_id, day, reason):
        self.center_id = center_id
        self.day = day
        self.reason = reason
        super().__init__(f"{center_id} {day}: {reason}")
```

## CSV output

Conflict rows are written to a dated CSV alongside the generated
workbook, matching the convention of
`hha_backfill_ambiguous_<YYYY-MM-DD>.csv` and
`auth_backfill_skipped_<YYYY-MM-DD>.csv`:

`one_off_conflicts_<YYYY-MM-DD>.csv`

| Column | Example |
| --- | --- |
| `center_id` | `12345` |
| `last_name` | `Smith` |
| `first_name` | `Jane` |
| `date` | `2026-06-05` |
| `reason` | `one-off on 2026-06-05 conflicts with absence` |

Behavior:

- The CSV is only written if at least one conflict was found in the
  run, mirroring the existing skip-CSV pattern.
- Location: CLI working directory by default; GUI uses the configured
  output folder. (No new CLI flag — same default as the existing
  ambiguous/skipped CSVs.)
- One row per `(center_id, date)` conflict. If the same member has
  conflicts on multiple days (only possible if the run does not
  short-circuit; see Section "Scheduler integration"), each day gets
  its own row. Given the short-circuit, in practice there will be at
  most one row per member.

## Migration

Two paths, both idempotent:

**Fresh databases.** Add a 5th DDL constant to
[scripts/create_supporting_tables.py](../../../scripts/create_supporting_tables.py)
and append `("OneOffAvailability", _CREATE_ONE_OFF_AVAILABILITY)` to
`_DDLS`. `python scripts\create_supporting_tables.py --db <PATH>` now
creates five tables.

**Existing databases.** A new script
`scripts/add_one_off_availability_table.py` issues just the new
`CREATE TABLE` and exits cleanly with an "already exists" message if
the table is already present. Same `--db` / `--quiet` flags as the
bootstrap. The script is safe to run repeatedly.

[scripts/README.md](../../../scripts/README.md) is updated to:

- List `add_one_off_availability_table.py` in the script table.
- Mention `OneOffAvailability` in the migration-steps section.
- Note that no backfill exists (and none is planned), so on a fresh DB
  the table simply starts empty.

## Testing

**Unit tests** (new file `tests/test_per_day.py`, pure — no ODBC):

- `compute_day_eligibility` with empty `one_offs` matches the existing
  behavior on every existing case (regression coverage).
- A valid one-off narrows the arrival window: assert the returned
  `arrival_window` is the intersection of the one-off with the plan,
  not the recurring rule.
- Each of the five conflict reasons raises `OneOffConflict` with the
  correct `reason` string. One test per row of the conflict table.
- **Order test:** a member that satisfies multiple conflict conditions
  simultaneously (e.g., duplicate one-off rows AND on an unauthorized
  weekday AND absent) raises with the *first-match* reason
  (`"duplicate one-off rows for ..."`).
- A non-intersecting one-off window returns
  `DayEligibility(eligible=False)` without raising (silent-skip).

**Smoke test** (extend `tests/test_smoke.py`):

- One end-to-end case seeds a one-off via the test-DB scenario
  mechanism, runs the full workbook generator, and confirms the
  conflict CSV is written with the expected single row.

**Test-DB scenario** (extend
[scripts/make_test_db.py](../../../scripts/make_test_db.py)):

- New scenario `one_off_conflict` seeds a member with a one-off that
  collides with an absence, so the GUI can be exercised against the
  new failure mode end-to-end. The existing happy-path scenarios are
  unchanged; the new table will simply be empty in them.

## Out of scope (for future specs)

- A GUI dialog to add/edit one-offs without opening Access directly.
- "Widening" one-offs (e.g., a one-off that adds Saturday for a member
  whose recurring rule excludes Saturday).
- One-offs that override fields other than the time window (pickup
  address, center, route).
- A backfill source for one-offs.
- Surfacing non-intersecting one-off windows as a conflict (currently
  silent).
