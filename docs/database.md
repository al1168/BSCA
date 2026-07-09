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
| DOB | Date/Time | |
| Health Plan | Short Text | Drives the per-plan timing rules in [monthly_schedule/rules.py](../monthly_schedule/rules.py). |
| Address | Short Text | Member's home address, used for travel-time calculation. |
| Long Lat | Short Text | Optional pre-computed `lng,lat` pair. When present, the scheduler skips the Google Geocoding call. |
| ... | | Other administrative fields exist on Contacts but are not consumed by the scheduler. |

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

Center-wide closures (e.g., holidays affecting everyone) are not
modeled as a dedicated table — they are entered as one Absence per
member. Revisit if duplicate data entry becomes painful.

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

## Relationships

```
Contacts (Center ID, PK)
   ↑       ↑       ↑       ↑
   │       │       │       │
Enrollment  Authorization  Absences  Availability
(Center ID FK)  (Center ID FK)  (Center ID FK)  (Center ID FK)
```

All four supporting tables are many-to-one against Contacts via
`Center ID`. There are no relationships between the supporting tables
themselves — each is queried independently by the scheduler.

## How the Scheduler Uses the Data

For each calendar day `D` in the requested schedule month, the
scheduler runs an ordered set of eligibility checks. The first
failing check makes the day ineligible (an empty row in the output
workbook).

1. **Enrollment.** Find an Enrollment row covering `D`. None → ineligible.
2. **Authorization period.** Find an Authorization row where `effective_start <= D <= effective_end`. None → ineligible.
3. **Authorized weekday.** That row's `auth_days` must contain `D.isoweekday()`. Otherwise → ineligible.
4. **Absence.** If any Absence row covers `D` → ineligible.
5. **Availability.** If an Availability row matches (`Center ID`, `Day Of Week`, `effective_start_date <= D <= effective_end_date (or NULL)`), narrow the arrival window:
   - `effective lo = max(plan.arrival_window_lo, avail_start)`
   - `effective hi = min(plan.arrival_window_hi, avail_end − plan.session_span_min_lower)`
   - If `effective lo > effective hi`, day → ineligible.
6. Otherwise → eligible. Generate times.

If a member is ineligible for *every* day in the month for a
structural reason (no enrollment row overlaps the month, no
authorization row overlaps the month, or absences cover every
authorized day), the member is reported in the run-summary failures
block:

| Condition | Failure reason |
| --- | --- |
| Zero Enrollment rows overlap the month | `not enrolled during {YYYY-MM}` |
| Zero Authorization rows overlap the month | `no active authorization for {YYYY-MM}` |
| Every authorized day blocked by Absences | `absent for entire {YYYY-MM}` |

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

1. Create the four new tables (Enrollment, Authorization, Absences,
   Availability) by running
   [`scripts/create_supporting_tables.py`](../scripts/create_supporting_tables.py)
   against the .accdb.
2. For each active member, create:
   - One Enrollment row with `start_date` = their original enrollment
     date and `end_date` = NULL.
   - One Authorization row carrying the old `SADC` value as
     `auth_days`, with `auth_start`/`auth_end` and
     `effective_start`/`effective_end` set to the current
     authorization period.
3. Leave the legacy authorization columns on Contacts in place. They
   are not dropped — the scheduler simply stops reading them.

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
