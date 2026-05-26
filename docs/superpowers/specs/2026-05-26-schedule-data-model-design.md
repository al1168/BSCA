# Scheduling Data Model Redesign

**Date:** 2026-05-26
**Status:** Approved (pending spec review)
**Scope:** Access database schema and the [monthly_schedule](../../../monthly_schedule/) scheduler's data flow.

## Goal

Replace the current "everything on Contacts" model with four supporting
tables that let the scheduler honor real-world member state: enrollment
periods, multi-year authorizations, one-off absences, and per-weekday
availability constraints. The current `SADC` field on Contacts (and
its related legacy auth columns) is retained as a historical record
but no longer read by the scheduler; weekday authorization data
moves to the new Authorization table.

## Design Decisions (Recap From Brainstorming)

| Decision | Choice |
| --- | --- |
| `SADC` (authorized weekdays) location | Scheduler reads from Authorization (`auth_days`) instead of Contacts. Legacy Contacts columns stay in place but unused. |
| `Health Plan` location | Stays on Contacts (drives [rules.py](../../../monthly_schedule/rules.py)) |
| Missing-authorization behavior | Skip member with explicit failure reason in the run summary |
| Default availability when no rule exists | Full plan-default hours; rules are subtractive constraints |
| Overlapping rows (same member, overlapping effective range) | Scheduler uses the row with the latest `effective_start` (or `start_date` / `effective_start_date` depending on the table) |
| Schema scope | Lean — only what the scheduler needs. No `Holidays`/`CenterClosures` table yet, no quantitative auth fields (`visits_per_week` etc.) |

## Table Definitions

### 1. Contacts (existing — only changes listed)

| Field | Status |
| --- | --- |
| Center ID (PK), Last Name, First Name, DOB, Health Plan, Address, Long Lat, ... | Unchanged |
| Chinese Name | New addition |
| **SADC**, **SADC Auth**, **SADC_Latest**, **Auth BGN**, **Auth EXP**, **TRANS Auth** | **Retained but unused by the scheduler.** Stay on Contacts as a historical record. The scheduler reads authorization data exclusively from the new Authorization table. |

Other existing fields on Contacts (not enumerated here) are unaffected
by this redesign.

### 2. Enrollment

Tracks when a member started and (if applicable) ended service. A
member who left and returned has multiple rows.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber, PK | |
| Center ID | Number, FK → Contacts.[Center ID] | |
| start_date | Date/Time | Inclusive |
| end_date | Date/Time, nullable | NULL = currently enrolled. Stored as a true Access NULL (not empty string) so SQL `WHERE end_date IS NULL OR end_date >= [day]` works naturally. |

### 3. Authorization

Tracks authorization periods and which weekdays are authorized within
each period. Two date pairs serve different purposes.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber, PK | |
| Center ID | Number, FK → Contacts.[Center ID] | |
| auth_start | Date/Time | First day of the authorization document's validity (insurance approval) |
| auth_end | Date/Time | Last day of the authorization document's validity |
| effective_start | Date/Time | First day THIS ROW's `auth_days` apply |
| effective_end | Date/Time | Last day THIS ROW's `auth_days` apply |
| auth_days | Short Text | Authorized weekdays. Same encoding as today's SADC (digits 1–7 separated by anything; parsed by [get_authorized_weekdays](../../../monthly_schedule/auth_days.py)). Example: `"1,3,5"` for Mon/Wed/Fri. |
| notes | Long Text, nullable | Free text |

**Any weekday change requires a new Authorization row** — for every
plan/company. The previous row is left in place as a historical
record; its `effective_end` is shortened to the day before the new
row takes over.

**Why two date pairs.** `auth_start`/`auth_end` describe the
authorization document (useful for audit/billing) — the date range
the insurance approved, never changed once entered.
`effective_start`/`effective_end` describe when the scheduler
actually consults this row. In the simple case they're identical;
when a later authorization supersedes an earlier one mid-period, the
older row's `effective_end` is shortened while its `auth_end` stays
at the document's original expiry.

**Examples:**

*Single authorization period, no mid-period change:*
| auth_start | auth_end | effective_start | effective_end | auth_days |
| --- | --- | --- | --- | --- |
| 2026-01-01 | 2026-12-31 | 2026-01-01 | 2026-12-31 | `1,3,5` |

*Mid-period change (new auth supersedes the old starting 2026-07-01):*
| auth_start | auth_end | effective_start | effective_end | auth_days |
| --- | --- | --- | --- | --- |
| 2026-01-01 | 2026-12-31 | 2026-01-01 | 2026-06-30 | `1,3,5` |
| 2026-07-01 | 2026-12-31 | 2026-07-01 | 2026-12-31 | `2,4` |

### 4. Absences

One-off absences blocking specific date ranges.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber, PK | |
| Center ID | Number, FK → Contacts.[Center ID] | |
| Leave Type | Short Text | Free text for now (e.g. "Vacation", "Hospital", "Sick"). Formalize to a lookup later if reporting demands it. |
| Start_Date | Date/Time | First absent day (inclusive) |
| End_Date | Date/Time | Last absent day (inclusive). For a single-day absence, equal to Start_Date. |
| Notes | Long Text, nullable | |

### 5. Availability

Per-weekday time-of-day constraints, with effective date ranges.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber, PK | |
| Center ID | Number, FK → Contacts.[Center ID] | |
| effective_start_date | Date/Time | First day this rule applies |
| effective_end_date | Date/Time, nullable | Last day; NULL = ongoing |
| Day Of Week | Integer | 1=Mon … 7=Sun (matches `datetime.date.isoweekday()`) |
| avail_start | Short Text | "HH:MM" — earliest the member can arrive |
| avail_end | Short Text | "HH:MM" — latest the member must leave |
| Notes | Long Text, nullable | |

**Time format.** Short Text `"HH:MM"` is chosen over Date/Time because
it matches how times are already represented in [rules.py](../../../monthly_schedule/rules.py)
and is human-readable in Access. `parse_hhmm` ([rules.py:29](../../../monthly_schedule/rules.py#L29))
already converts to minutes since midnight.

**Granularity.** One row per (member, weekday, effective period). A
Mon–Fri 10:00–15:00 availability is five rows. A "Tuesday 10–14:00,
other days no constraint" pattern is one row.

## Scheduler Data Flow

For each calendar day `D` in the target schedule month, eligibility is
determined by this ordered set of checks. The first one that fails
makes the day ineligible (empty row in the output). If every day
fails for a structural reason (no enrollment, no auth), the whole
member is flagged in the run-summary failures block.

1. **Enrollment** — find an Enrollment row with
   `start_date <= D` AND (`end_date IS NULL` OR `end_date >= D`).
   No match → day ineligible.
2. **Authorization (period)** — find an Authorization row with
   `effective_start <= D <= effective_end`. No match → day ineligible.
3. **Authorization (weekday)** — `D.isoweekday()` must be in that
   row's `auth_days`. Not in set → day ineligible.
4. **Absence** — if any Absence row has
   `Start_Date <= D <= End_Date`, day ineligible.
5. **Availability** — find any Availability row matching
   `Center ID`, `Day Of Week == D.isoweekday()`, and
   `effective_start_date <= D <= effective_end_date (or NULL)`.
   - If no row: use plan defaults from `rules.py`.
   - If a row exists: narrow the arrival window to
     `[max(plan.arrival_window_lo, avail_start),
       min(plan.arrival_window_hi, avail_end - plan.session_span_min_lower)]`.
   - If that window has `lo > hi` (no valid arrival time), day ineligible.
6. If still eligible → generate the daily schedule.

### Whole-Member Failures

If the member has any of these structural problems, surface as a
failure in the run summary (consistent with the existing `Failure`
namedtuple pattern in [new_monthly_schedule.py](../../../new_monthly_schedule.py)).
"Overlap" means "shares at least one day with the requested month."

| Condition | Failure reason |
| --- | --- |
| Zero Enrollment rows overlap the requested month | `"not enrolled during {YYYY-MM}"` |
| Zero Authorization rows overlap the requested month | `"no active authorization for {YYYY-MM}"` |
| Every authorized day in the month is blocked by Absences | `"absent for entire {YYYY-MM}"` |

A schedule month that *partially* overlaps an authorization or
enrollment boundary is NOT a whole-member failure — the per-day check
handles each day correctly, and the output workbook has empty rows
for days outside the valid range. The whole-member failure fires only
when there is no valid coverage anywhere in the month.

### Overlap Resolution

If two rows of the same kind overlap for the same member (e.g. two
Authorization rows with overlapping `effective_start`/`effective_end`),
the scheduler picks the row with the **latest `effective_start`** for
the day in question. Ties (same `effective_start`) are broken by the
largest `ID`. The same rule applies to Availability and Enrollment
(using `effective_start_date` and `start_date` respectively).

This is a deliberate choice over erroring: data-entry mistakes are
likely; the scheduler should always produce output and prefer the most
recently entered record.

## What Changes In Code

This spec defines the schema and behavior. A separate implementation
plan will cover the Python changes, which include at minimum:

- [monthly_schedule/db.py](../../../monthly_schedule/db.py) — new
  queries to fetch Enrollment, Authorization, Absences, Availability
  Rules per member.
- [monthly_schedule/eligibility.py](../../../monthly_schedule/eligibility.py) —
  the existing `Exclusions` scaffold becomes the seam that holds per-day
  eligibility derived from the new tables. The `is_day_eligible`
  signature may grow to take a richer "per-day context" object that
  includes the time window from Availability.
- [monthly_schedule/daily_schedule.py](../../../monthly_schedule/daily_schedule.py) —
  the arrival-window selection inside `build_daily_schedule` must accept
  a narrowed window from the per-day eligibility result, not just the
  plan default.
- [new_monthly_schedule.py](../../../new_monthly_schedule.py) `process_member`
  — assembles per-day eligibility for the month before time generation;
  surfaces whole-member structural failures via the existing `Failure`
  pipeline.
- [gui/i18n.py](../../../gui/i18n.py) — new summary failure reason keys
  for the three whole-member failures listed above.

The Access schema changes themselves happen in the Access GUI and are
not in the implementation plan's scope.

## Out of Scope (YAGNI)

- A `Holidays` / `CenterClosures` table for center-wide closed days.
  Today, each member's holiday is entered as an Absence. Revisit if
  duplicate-data entry becomes painful.
- Quantitative authorization fields (`visits_per_week`, `hours_per_week`,
  `auth_number`). Today's auths are weekday-based, not quantity-based.
  Revisit if billing audits or quantity-capped auths appear.
- A formal `LeaveTypes` lookup table for Absences. Free text is enough
  until reports demand consistent values.
- Validation that overlapping rows don't exist. The scheduler tolerates
  them (most-recent-wins); a separate data-quality report could surface
  them, but is out of scope here.
- Schema migration of existing data. The current `Contacts.SADC` (and
  related legacy auth columns) need to be backfilled into the new
  Authorization table — the legacy columns themselves stay in place
  but the scheduler stops reading them. The implementation plan
  should include a one-time backfill step or manual data-entry
  instructions, but the strategy is not in this spec.

## File Inventory (For The Eventual Implementation Plan)

Access schema (manual changes via the Access GUI):
- Create `Enrollment`, `Authorization`, `Absences`, `Availability`
  tables with FKs to `Contacts.[Center ID]`
- Legacy auth columns on Contacts (`SADC`, `SADC Auth`, `SADC_Latest`,
  `Auth BGN`, `Auth EXP`, `TRANS Auth`) stay in place; the scheduler
  stops reading them.

Python changes (in a future plan):
- `monthly_schedule/db.py`
- `monthly_schedule/eligibility.py`
- `monthly_schedule/daily_schedule.py`
- `new_monthly_schedule.py`
- `gui/i18n.py`
- `monthly_schedule/rules.py` (possibly, if availability-window narrowing exposes plan constants that need to be referenced)
- New tests in `tests/`
