# Database Reference

This document describes the Access database schema the scheduler reads
from. It reflects the target design from
[docs/superpowers/specs/2026-05-26-schedule-data-model-design.md](superpowers/specs/2026-05-26-schedule-data-model-design.md);
not every table is necessarily live in the production database yet.

The database is a Microsoft Access file (`.accdb`) accessed via the
ODBC `Microsoft Access Driver (*.mdb, *.accdb)`. The driver's bitness
must match the Python interpreter's.

## Tables

### Contacts

The master member record. One row per member, keyed by `Center ID`.

| Field | Type | Notes |
| --- | --- | --- |
| Center ID | Number | Primary key. Used by every other table as the foreign key. |
| Last Name | Short Text | |
| First Name | Short Text | |
| Chinese Name | Short Text | |
| DOB | Short Text | Date of birth. Short Text in the live database (with occasional typos); normalized by `parse_flex_date` in [monthly_schedule/billing_workbook.py](../monthly_schedule/billing_workbook.py), which also tolerates a future migration to a real Date/Time column ([scripts/change_dob_to_date_in_contacts.py](../scripts/change_dob_to_date_in_contacts.py)). |
| Gender | Short Text | Read by the billing workbook. |
| Admission Date | Short Text | No longer read by the billing workbook — the ENROLLMENT DATE column now shows the member's earliest `Enrollment.start_date` (newer members leave this field blank). Still read by [scripts/backfill_enrollment_from_contacts.py](../scripts/backfill_enrollment_from_contacts.py). |
| Medicaid | Short Text | Member's Medicaid number, read by the billing workbook. |
| Member ID | Short Text | External Medicaid-style ID. Copied onto Authorization/TransportAuthorization rows by the backfill. |
| Health Plan | Short Text | Drives the per-plan timing rules in [monthly_schedule/rules.py](../monthly_schedule/rules.py). |
| Address | Short Text | Member's home address, used for travel-time calculation. |
| Long Lat | Short Text | Optional pre-computed `lng,lat` pair. When present, the scheduler skips the Google Geocoding call. |
| Group | Short Text | Free-text member tag typed into the Setup GUI's "Group" box. Added and seeded by [scripts/add_group_to_contacts.py](../scripts/add_group_to_contacts.py); only blank rows are filled, so hand edits survive re-runs. Not read by the scheduler. |
| ... | | Other administrative fields exist on Contacts but are not consumed by the scheduler. |

**Column-name normalization.** Databases exported from DBM.accdb name
these columns with underscores (`Center_ID`, `Admission`, `AuthBGN`,
…). The setup chain runs
[scripts/normalize_contacts_columns.py](../scripts/normalize_contacts_columns.py)
first, which renames the legacy columns in place (via DAO) and then
verifies every Contacts column BSCA reads actually exists: `Center ID`,
`Last Name`, `First Name`, `Health Plan`, `Admission Date`, `SADC`,
`HHA`, `Emergency`, `Auth BGN`, `Auth EXP`, `Member ID`, `SADC Auth`,
`TRANS Auth`, `Gender`, `DOB`, `Medicaid`, `Address`. A missing column
stops the chain with a readable error.

**Historical note — legacy authorization columns.** Contacts retains
several pre-redesign columns that the scheduler no longer reads:
`SADC`, `SADC Auth`, `SADC_Latest`, `Auth BGN`, `Auth EXP`,
`TRANS Auth`. These remain in the database as a historical record
(and may be used by other tools or reports), but the scheduler now
reads weekday authorization exclusively from the new Authorization
table. The setup-time backfill
([scripts/backfill_authorization_from_contacts.py](../scripts/backfill_authorization_from_contacts.py))
still consults some of these once, to seed the Authorization and
TransportAuthorization tables: `SADC` → `auth_days`,
`SADC Auth` → `Authorization.auth_number`,
`TRANS Auth` → `TransportAuthorization.auth_number`,
`Auth BGN`/`Auth EXP` → the date pairs.

### Enrollment

Tracks when a member is actively served. A member who left and came
back has multiple rows.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber | Primary key. |
| Center ID | Number | FK → Contacts. |
| start_date | Date/Time | Inclusive. First day the member is enrolled in this period. |
| end_date | Date/Time, nullable | Inclusive. NULL means currently enrolled. |

**Semantics:**
- A member is enrolled on day `D` iff there exists an Enrollment row
  with `start_date <= D` AND (`end_date IS NULL` OR `end_date >= D`).
- A returning member's earlier row keeps its old `end_date`; a new row
  is added with a new `start_date` and NULL `end_date`.

### Authorization

Records the authorization periods and which weekdays are authorized
during each period.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber | Primary key. |
| Center ID | Number | FK → Contacts. |
| auth_start | Date/Time | First day of the authorization document's validity (the insurance approval). |
| auth_end | Date/Time | Last day of the authorization document's validity. |
| effective_start | Date/Time | First day **this row's** `auth_days` apply. |
| effective_end | Date/Time | Last day **this row's** `auth_days` apply. |
| auth_days | Short Text | Authorized weekdays as digits 1–7 separated by any non-digit. `1=Mon` … `7=Sun`. Example: `"1,3,5"` for Mon/Wed/Fri. Parser: [monthly_schedule/auth_days.py](../monthly_schedule/auth_days.py). |
| notes | Long Text, nullable | Free-text context. |
| Health Plan | Short Text | The member's MLTC plan, copied from Contacts.[Health Plan] by the backfill. |
| Plan Type | Short Text, nullable | Kind of plan behind the authorization (e.g. `MAP`, `MLTC`), filled in by hand in Access. Shown in the billing workbook's PLAN TYPE column (from the month's latest active authorization). Added by [scripts/add_plan_type_to_authorization.py](../scripts/add_plan_type_to_authorization.py) on existing databases. |
| Member ID | Short Text, nullable | External Medicaid-style ID, copied from Contacts.[Member ID]. |
| auth_number | Short Text, nullable | Authorization number, copied from Contacts.[SADC Auth] by the backfill. |
| created_at | Date/Time | Timestamp set when the backfill inserts the row. |

**Any weekday change requires a new Authorization row** — this
applies to every plan/company. The previous row is left in place as
a historical record; its `effective_end` is shortened to the day
before the new row takes over.

**Why two date pairs.**
- `auth_start`/`auth_end` describe the authorization *document* —
  the date range the insurance approved. Useful for audit and
  billing. Once entered, these are not changed.
- `effective_start`/`effective_end` describe when the scheduler
  actually consults this row. In the simple case they equal
  `auth_start`/`auth_end`; when a later authorization supersedes
  this one mid-period, the older row's `effective_end` is shortened
  while `auth_end` stays at the document's original date.

**Examples:**

Single authorization period, no mid-period changes:
| auth_start | auth_end | effective_start | effective_end | auth_days |
| --- | --- | --- | --- | --- |
| 2026-01-01 | 2026-12-31 | 2026-01-01 | 2026-12-31 | `1,3,5` |

Weekday change mid-period (a new auth supersedes the old one
starting 2026-07-01):
| auth_start | auth_end | effective_start | effective_end | auth_days |
| --- | --- | --- | --- | --- |
| 2026-01-01 | 2026-12-31 | 2026-01-01 | 2026-06-30 | `1,3,5` |
| 2026-07-01 | 2026-12-31 | 2026-07-01 | 2026-12-31 | `2,4` |

The first row's `auth_end` stays at 2026-12-31 (the original
document's expiry); only its `effective_end` is shortened to
2026-06-30 to reflect that the new auth took over.

### TransportAuthorization

The member's **transportation** authorization. Same schema as
`Authorization` (every column, including `[ID]`), kept as its own table
because the transport authorization may eventually carry dates that
differ from the care authorization.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber | Primary key. |
| Center ID | Number | FK → Contacts. |
| auth_start / auth_end | Date/Time | Authorization document validity. |
| effective_start / effective_end | Date/Time | When this row applies. |
| auth_days | Short Text | Authorized weekdays (1–7). |
| notes | Long Text, nullable | Free-text context. |
| Health Plan | Short Text | Member's MLTC plan. |
| Member ID | Short Text, nullable | External Medicaid-style ID. |
| auth_number | Short Text, nullable | Transport authorization number, copied from Contacts.[TRANS Auth]. |
| created_at | Date/Time | Timestamp set when the backfill inserts the row. |
| Document | Attachment | Native Access ATTACHMENT (paperclip) field for scanned transport-auth documents. Added by [scripts/add_document_to_transport_authorization.py](../scripts/add_document_to_transport_authorization.py) via DAO — ODBC can't create ATTACHMENT fields, so it's not in the CREATE TABLE DDL. (`Authorization` carries the same field, added by the equivalent script.) |

**How the backfill populates it.** When it inserts an `Authorization`
row and the member's `Contacts.[TRANS Auth]` is non-blank, it also
inserts a `TransportAuthorization` row that is identical to the
Authorization row **except** `auth_number = TRANS Auth`, and records the
pairing in `AuthEdge`. A blank `TRANS Auth` produces no transport row.
(Today the dates/effective dates/`auth_days` are copied verbatim from
the care authorization; the separate table leaves room for them to
diverge later.)

### AuthEdge

Link table pairing each `Authorization` row with its
`TransportAuthorization` row.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber | Primary key. |
| authorization_id | Number (LONG) | FK → Authorization.[ID]. |
| transport_authorization_id | Number (LONG) | FK → TransportAuthorization.[ID]. |

The backfill captures each inserted row's autonumber via Access's
`SELECT @@IDENTITY` and writes one `AuthEdge` row per pair.

### Absences

One-off absences blocking specific date ranges (vacation, hospital
stay, etc.).

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber | Primary key. |
| Center ID | Number | FK → Contacts. |
| Leave Type | Short Text | Free text (e.g. `Vacation`, `Hospital`, `Sick`). |
| Start_Date | Date/Time | Inclusive. First absent day. |
| End_Date | Date/Time | Inclusive. Last absent day. For a one-day absence, equal to `Start_Date`. |
| Notes | Long Text, nullable | |

**Semantics:** day `D` is blocked iff any Absence row satisfies
`Start_Date <= D <= End_Date`.

Center-wide closures are modeled by the `Holidays` and `OperatingDays`
tables below, not as per-member absences.

### Availability

Per-weekday time-of-day constraints with effective date ranges.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber | Primary key. |
| Center ID | Number | FK → Contacts. |
| effective_start_date | Date/Time | First day this rule applies. |
| effective_end_date | Date/Time, nullable | Last day this rule applies. NULL = ongoing. |
| Day Of Week | Integer | 1=Mon … 7=Sun (matches Python's `date.isoweekday()`). |
| avail_start | Date/Time | Time-only DATETIME (Access stores the time portion with a 1899-12-30 placeholder date). Earliest the member can arrive. The Python layer renders this as `"HH:MM"` via [`map_availability_row`](../monthly_schedule/db.py). |
| avail_end | Date/Time | Time-only DATETIME, same storage convention as `avail_start`. Latest the member must leave. |
| Notes | Long Text, nullable | |

**Granularity.** One row per (member, weekday, effective period). A
"Mon–Fri 10:00–15:00" availability is five rows.

**Default.** If no Availability row matches a given (member,
weekday, date), the scheduler uses the plan's default arrival window
from [rules.py](../monthly_schedule/rules.py). Availability rows are
subtractive constraints — they tighten the window, never widen it.

**Why time-only DATETIME for times.** Access has no pure time-of-day
type — DATETIME with a placeholder date is the conventional way to
represent a wall-clock time, and it lights up Access's built-in time
picker in the UI. The Python layer always reads/writes the time
portion; the placeholder date (1899-12-30) is ignored.

### OneOffAvailability

A single-date availability override (spec
[2026-06-04-one-off-availability-design.md](superpowers/specs/2026-06-04-one-off-availability-design.md)).
Where `Availability` describes a recurring weekly pattern, a one-off
row pins the member's window for exactly one calendar date. Created by
[scripts/add_one_off_availability_table.py](../scripts/add_one_off_availability_table.py)
on existing databases.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber | Primary key. |
| Center ID | Number | FK → Contacts. |
| date | Date/Time | The single calendar date this override applies to. |
| avail_start | Date/Time | Time-only DATETIME (1899-12-30 placeholder date), rendered as `"HH:MM"` by [`map_one_off_row`](../monthly_schedule/db.py). |
| avail_end | Date/Time | Time-only DATETIME, same convention. |
| Notes | Long Text, nullable | |

**Semantics.** On a date with a one-off row, the row **replaces** the
recurring Availability lookup entirely, and the one-off window is
exempt from the drop-off/pick-up transport reserves that recurring
rows get (user decision, spec 2026-07-20). Two data situations are
hard errors that abort the member's schedule with a readable message
(`OneOffConflict` in [monthly_schedule/per_day.py](../monthly_schedule/per_day.py))
rather than being silently resolved:
- two or more one-off rows for the same member and date, or
- a one-off row on a date also covered by an Absence row.

### EmergencyContact

Emergency-contact people for each member, seeded from the free-text
`Contacts.[Emergency]` column by
[scripts/backfill_emergency_contacts_from_contacts.py](../scripts/backfill_emergency_contacts_from_contacts.py).
The scheduler does not read this table — it exists for other tooling
— but `create_supporting_tables.py` creates it as part of the
standard schema.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber | Primary key. |
| Center ID | Number | FK → Contacts. |
| Full Name | Short Text | |
| Phone Number | Short Text (50) | |
| Relationship | Short Text (100) | |

### Holidays

Company holidays: dates the center is closed for everyone. Entered
through the Members app's Company Calendar dialog.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber | Primary key. |
| holiday_name | Short Text | e.g. `Labor Day`. |
| date | Date/Time | The single closed date. A multi-day closure is one row per day. |

**Semantics:** day `D` is a holiday iff any row's `date` equals `D`.
The scheduler generates no times that day; it is blank on the
timesheet, the activity log and the billing sheet (not an absence).
The debug CSV says `Center closed (<holiday_name>)`.

### OperatingDays

Weekly operating hours, one row per **open** weekday. A weekday with
no row is closed. Seeded Monday–Sunday 08:00–16:00 by
[scripts/seed_operating_days.py](../scripts/seed_operating_days.py)
when the table is empty; edited through the Members app.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber | Primary key. |
| day_name | Short Text | `Monday` … `Sunday`, for readability in Access. |
| Day Of Week | Number (LONG) | 1 = Monday … 7 = Sunday, the same convention as `Availability.[Day Of Week]`. The scheduler matches on this column, never on `day_name`. |
| opening_time | Date/Time | Time-of-day only (`1899-12-30 HH:MM`), like `Availability.avail_start`. |
| closing_time | Date/Time | Same. Later than `opening_time`. |

**Semantics:** weekday `W` is open iff a row with `[Day Of Week] = W`
exists; if several exist, the largest `ID` wins. On an open day the
row's `opening_time` / `closing_time` replace the plan rules'
`earliest_time_in` / `latest_time_out` (the hard day bounds). A closed
weekday is blank like a non-authorized weekday; the debug CSV says
`Center closed on Sundays`. Implementation:
[monthly_schedule/center_calendar.py](../monthly_schedule/center_calendar.py).

### Codes

Lookup table mapping each health plan to its billing codes. Read by
the billing workbook ([monthly_schedule/billing_workbook.py](../monthly_schedule/billing_workbook.py))
via [`get_billing_codes`](../monthly_schedule/db.py). Not created by
`create_supporting_tables.py` — maintained by hand in Access.

| Field | Type | Notes |
| --- | --- | --- |
| Health Plan | Short Text | Plan code, matched case-insensitively after trimming (` hf ` → `HF`). |
| SADC Code | Short Text | Billing code for the day-care service. |
| Trans Code | Short Text | Billing code for transportation. |

If the table is missing or unreadable, the billing sheet degrades to
`????` placeholder codes instead of failing the run.

### Activities

Lookup table naming the activity columns of the activity-log
workbooks ([monthly_schedule/activity_log_workbook.py](../monthly_schedule/activity_log_workbook.py),
[monthly_schedule/cathay_activity_log.py](../monthly_schedule/cathay_activity_log.py)).
Read via [`get_activities`](../monthly_schedule/db.py). Not created by
`create_supporting_tables.py` — maintained by hand in Access.

| Field | Type | Notes |
| --- | --- | --- |
| A_ID | Short Text | Activity key matching the template's activity columns (normalized to upper-case, e.g. `A1`). |
| Activity_Name | Short Text | English activity name. |
| Frequency | Short Text | Weekdays the activity is offered, digits separated by dots (e.g. `1.2.3.4.5`). |
| C_name | Short Text | Chinese activity name. |

If the table is missing or unreadable, activity logs are skipped with
a warning instead of failing the run.

## Relationships

```
Contacts (Center ID, PK)
   ↑         ↑                ↑         ↑            ↑                  ↑
   │         │                │         │            │                  │
Enrollment  Authorization  Absences  Availability  OneOffAvailability  EmergencyContact
             │
             │ AuthEdge (authorization_id / transport_authorization_id)
             ↓
        TransportAuthorization (also Center ID FK → Contacts)
```

All supporting tables are many-to-one against Contacts via
`Center ID`. The only relationship between supporting tables is
`AuthEdge`, which pairs each Authorization row with its
TransportAuthorization row; everything else is queried independently
by the scheduler. `Codes` and `Activities` are standalone lookup
tables with no foreign keys.

## How the Scheduler Uses the Data

For each calendar day `D` in the requested schedule month, the
scheduler runs an ordered set of eligibility checks. The first
failing check makes the day ineligible (an empty row in the output
workbook).

1. **Enrollment.** Find an Enrollment row covering `D`. None → ineligible.
2. **Authorization period.** Find an Authorization row where `effective_start <= D <= effective_end`. None → ineligible.
3. **Center open.** `D` must not be a Holiday, and `D`'s weekday must have an OperatingDays row. Otherwise → ineligible (blank, not an absence — see the Holidays/OperatingDays sections above).
4. **Authorized weekday.** That row's `auth_days` must contain `D.isoweekday()`. Otherwise → ineligible.
5. **One-off override.** If a OneOffAvailability row exists for `D`, its window replaces steps 6–7's absence and availability lookups (a duplicate one-off or a one-off overlapping an Absence is a hard error — see the OneOffAvailability section). Otherwise:
6. **Absence.** If any Absence row covers `D` → ineligible.
7. **Availability.** Look up the Availability row matching (`Center ID`, `Day Of Week`, `effective_start_date <= D <= effective_end_date (or NULL)`). No row → eligible with the plan's full day bounds.
8. **Placement window.** Clip the availability window (recurring or one-off) to the day's hard bounds (the OperatingDays row's `opening_time`/`closing_time`, or the plan rules' fallback if no row applies), and for recurring rows reserve the transport lead/tail when the plan's `pickup_by_avail_start` / `dropoff_by_avail_end` rules apply (one-off rows are exempt). If the resulting window can't fit the plan's minimum session length, day → ineligible.
9. Otherwise → eligible. Generate times.

If a member is ineligible for *every* day in the month for a
structural reason, the member is skipped and reported in the
run-summary failures block (`compute_month_failure` in
[monthly_schedule/per_day.py](../monthly_schedule/per_day.py)):

| Condition | Failure reason |
| --- | --- |
| Zero Enrollment rows overlap the month | `not enrolled during this month` |
| Zero Authorization rows overlap the month | `no active authorization for this month` |
| No day is simultaneously enrolled, covered by an authorization, and on an authorized weekday | `no day is both enrolled and authorized this month` |
| Every schedulable day blocked by Absences | `absent for the entire month` |

Partial coverage (e.g., authorization covers May 1–15 but not the
rest of May) is **not** a whole-member failure — the output workbook
just has empty rows for May 16–31.

## Constraints and Data-Quality Notes

- **NULL semantics.** `Enrollment.end_date` and
  `Availability.effective_end_date` use Access NULL (a true Date
  field with no value) to mean "open-ended." Do not use empty strings
  — the SQL `IS NULL` checks rely on this.
- **Inclusive date ranges.** All date ranges in this database are
  inclusive on both ends.
- **Overlapping rows.** If two rows of the same kind cover the same
  day for the same member (e.g. two Authorization rows with
  overlapping `effective_start`/`effective_end`), the scheduler picks
  the row with the **latest `effective_start`** (or `start_date` /
  `effective_start_date` for Enrollment and Availability
  respectively). Ties are broken by the largest `ID`. This is a
  deliberate "most-recent-wins" policy — data-entry mistakes don't
  crash the scheduler.
- **Validation.** There is currently no automated check that rows do
  not overlap. A future data-quality report could surface them; for
  now, rely on the most-recent-wins fallback.

## Migration From the Pre-Redesign Schema

The previous schema stored authorized weekdays in a `SADC` column on
Contacts and used a constellation of Contacts columns (`SADC Auth`,
`SADC_Latest`, `Auth BGN`, `Auth EXP`, `TRANS Auth`) to track
authorization metadata. Migrating to this design requires:

1. Normalize the Contacts column names by running
   [`scripts/normalize_contacts_columns.py`](../scripts/normalize_contacts_columns.py)
   (needed for databases exported from DBM.accdb).
2. Create the eight supporting tables (Enrollment, Authorization,
   TransportAuthorization, Absences, Availability, OneOffAvailability,
   EmergencyContact, AuthEdge) by running
   [`scripts/create_supporting_tables.py`](../scripts/create_supporting_tables.py)
   against the .accdb.
3. For each active member, create:
   - One Enrollment row with `start_date` = their original enrollment
     date and `end_date` = NULL.
   - One Authorization row carrying the old `SADC` value as
     `auth_days`, with `auth_start`/`auth_end` and
     `effective_start`/`effective_end` set to the current
     authorization period.
4. Leave the legacy authorization columns on Contacts in place. They
   are not dropped — the scheduler simply stops reading them.
5. Create and fill the `Codes` and `Activities` lookup tables by hand
   in Access if billing codes and activity logs are wanted (both
   degrade gracefully when absent).

Per-member backfill of the new tables is now scripted in
[`scripts/backfill_authorization_from_contacts.py`](../scripts/backfill_authorization_from_contacts.py)
and
[`scripts/backfill_availability_from_hha.py`](../scripts/backfill_availability_from_hha.py).

## See Also

- [docs/superpowers/specs/2026-05-26-schedule-data-model-design.md](superpowers/specs/2026-05-26-schedule-data-model-design.md) — the design spec this reference is derived from
- [docs/superpowers/specs/2026-05-15-monthly-schedule-design.md](superpowers/specs/2026-05-15-monthly-schedule-design.md) — original scheduler spec
- [monthly_schedule/db.py](../monthly_schedule/db.py) — current SQL queries against Contacts
- [monthly_schedule/auth_days.py](../monthly_schedule/auth_days.py) — auth_days parser
- [monthly_schedule/rules.py](../monthly_schedule/rules.py) — per-plan timing rules
