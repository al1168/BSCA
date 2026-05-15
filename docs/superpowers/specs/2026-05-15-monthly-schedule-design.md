# Monthly Schedule Workbook — Design

**Date:** 2026-05-15
**Status:** Approved (design); pending implementation plan
**Implementation:** Python 3 + `pyodbc` (Access) + `openpyxl` (Excel)

## 1. Purpose & Scope

A new Python script, `new_monthly_schedule.py`, generates a printable Excel
workbook for **one SADC member** for **one month**. The workbook contains two
tables:

1. **Attendance** — Date, Day, Time-In, Time-Out
2. **Transportation** — Date, Day, Pick-Up Time, Arrival Time, Departure Time,
   Drop-Off Time

Member identity/header data comes from the Access database. The times are
**script-generated placeholders** for now; real business rules ("restrictions")
are layered in later through designed seams (Section 4).

`Get-Contact.ps1` is left unchanged — it remains the interactive PowerShell
lookup tool. `new_monthly_schedule.py` is a self-contained Python script that
runs its own scoped query, so there is no refactor of existing code. The two
tools coexist; the project is intentionally bilingual at this small scale.

## 2. CLI Parameters (argparse)

| Argument         | Type | Required | Default                                                            |
|------------------|------|----------|--------------------------------------------------------------------|
| `--center-id`    | int  | Yes      | —                                                                  |
| `--year`         | int  | Yes      | —                                                                  |
| `--month`        | int  | Yes      | — (validated 1–12)                                                  |
| `--db-path`      | str  | No       | `\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb`           |
| `--output-path`  | str  | No       | `./Schedule_<CenterID>_<YYYY-MM>.xlsx`                              |
| `--preview-data` | flag | No       | off — when set, print computed rows and skip writing the workbook  |

Exit codes: `0` success; non-zero on no-member, validation failure, or DB/driver
error (see Section 6).

## 3. Data Flow

1. Connect to Access via **`pyodbc`** using the Microsoft Access ODBC driver:
   `DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=<db-path>;`.
2. Query, with a parameterized `?` placeholder:
   `SELECT [Center ID], [Last Name], [First Name], [Health Plan], [SADC Auth]
   FROM [Contacts] WHERE [Center ID] = ?`.
3. **No matching row** → warn and exit with a non-zero code; no file written.
   **DB path missing** → exit with a clear error (mirrors `Get-Contact.ps1`).
4. Parse `SADC Auth` (e.g. `"1.3.4.5"`) into a set of weekday numbers using the
   encoding **1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat, 7=Sun**. Split on any
   non-digit separator.
5. Build every calendar date from the 1st through the last day of
   `year`/`month`.
6. For each date, compute the 3-letter day abbreviation (`Fri`, `Sat`, …) and
   determine eligibility (Section 4).

### Column mapping (confirmed against the live DB schema)

| Header field | Source                                       |
|--------------|----------------------------------------------|
| `ID`         | `Center ID` (also the `--center-id` argument)|
| `Name`       | `Last Name` + `, ` + `First Name`            |
| `Auth Days`  | `SADC Auth` (raw string shown in header)      |
| `MLTC`       | `Health Plan`                                |
| Company name | Fixed constant `Bowery Senior Care Inc`      |

## 4. Time Generation & Day Eligibility

### 4a. Day eligibility — single seam

The decision "should this date get generated times?" is isolated in one
function, `is_day_eligible(date, authorized_weekdays, exclusions=None)`,
consulted per date by the daily-schedule builder.

- **Now:** a date is eligible ⟺ its weekday is in the authorized set parsed
  from `SADC Auth`.
- The `exclusions` parameter defaults to `None`/empty: a list of date ranges
  plus an optional termination date. With the empty default, behavior is
  identical to today.
- This is the **single seam** through which all future date-affecting sources
  plug in, with no restructuring:
  - **Vacation ranges** (e.g. 5/10/2026–5/16/2026) → those dates ineligible.
  - **Termination date** (e.g. 5/10/2026) → that date and all later dates
    ineligible.
  - **Auth period** (`Auth BGN` / `Auth EXP`) → dates outside the window
    ineligible.
  - **Other visit types** → represented as additional exclusion entries.
- A future `get_member_exclusions` function will read a separate
  vacation/termination table and produce the exclusions list, which the script
  will pass in. **That table and its reader are NOT built now** — only the
  parameter seam and the empty default are built.

### 4b. Time generation — extendable rules object

A module-level `SCHEDULE_RULES` dict defines all tunable constraints; the
daily-schedule builder reads from it and never hardcodes times.

Rules object holds, per plan:

- `arrival_window` = { earliest, latest }
- `departure_window` = { earliest, latest }
- `min_session_hours`, `max_session_hours`
- `pickup_lead_min` = { min, max } — minutes before Arrival
- `dropoff_trail_min` = { min, max } — minutes after Departure
- `time_in_drift_min` = { min, max } — Time-In relative to Arrival
- `time_out_drift_min` = { min, max } — Time-Out relative to Departure
- `round_to_minutes` — snap generated times (1 = no snap; 5 = snap to :05)

**Per-plan keying:** `SCHEDULE_RULES` is keyed by `Health Plan`, with a
`"Default"` entry used when the member's plan has no specific entry. Built now
because `Health Plan` is already pulled and it is only a few lines.

**Placeholder defaults** (modeled on the provided image — a morning half-day
session ≈ 08:00–12:30):

- Arrival ≈ 08:15, window 08:05–08:25
- Departure ≈ 12:15, window 12:05–12:25
- Pick-Up = Arrival − 8–12 min
- Drop-Off = Departure + 8–12 min
- Time-In = Arrival + 0–3 min
- Time-Out = Departure − 0–3 min
- `round_to_minutes` = 1, `min_session_hours` = 3, `max_session_hours` = 6

**One coherent schedule per eligible day:** Arrival and Departure are drawn
within their windows; Pick-Up/Drop-Off and Time-In/Time-Out are derived from
them so both tables stay mutually consistent for the same day.

**Post-generation assertion:** after the rules are applied, the builder
re-validates the ordering and session length:

```
Pick-Up < Arrival ≤ Time-In   …   Time-Out ≤ Departure < Drop-Off
min_session_hours ≤ (Departure − Arrival) ≤ max_session_hours
```

A rule combination that violates this raises an exception (and fails the
corresponding test) rather than emitting silent garbage.

### 4c. Rendering of ineligible days

An ineligible day (non-authorized weekday, future vacation, or post-termination)
renders the same way: the row shows Date + Day, and all time cells are blank.
A future visual marker for vacation days (e.g. a `VAC` label) would be a small
additive change at render time — noted as optional future, **not built now**.

### 4d. Explicitly out of scope (YAGNI, confirmed)

- No separate vacation/termination table schema.
- No exclusion-source reading code (`get_member_exclusions` deferred).
- No plug-in/callback constraint engine.

Only the `is_day_eligible` seam (empty default) and the `SCHEDULE_RULES`
object plus the post-generation assertion are built now.

## 5. Workbook Layout

Built via **`openpyxl`** — the `.xlsx` is written directly, with no Excel
process launched (no orphaned `EXCEL.EXE`, faster and deterministic). The
workbook size (~62 data rows total) is trivial.

Single worksheet, named `Schedule`, two tables stacked vertically with a
**manual row page break** between them (`openpyxl` `Break` in `ws.row_breaks`)
so each prints on its own page:

```
Bowery Senior Care Inc
MLTC: <Health Plan>
ID: <CenterID>    Name: <Last, First>    Auth Days: <raw SADC Auth>

| Date      | Day | Time-In | Time-Out |
| 5/1/2026  | Fri | 08:17   | 12:13    |
| 5/2/2026  | Sat |         |          |
| …         | …   | …       | …        |
----------------- PAGE BREAK -----------------
Bowery Senior Care Inc
MLTC: <Health Plan>
ID: <CenterID>    Name: <Last, First>    Auth Days: <raw SADC Auth>

| Date      | Day | Pick-Up Time | Arrival Time | Departure Time | Drop-Off Time |
| 5/1/2026  | Fri | 08:05        | 08:15        | 12:15          | 12:25         |
| 5/2/2026  | Sat |              |              |                |               |
| …         | …   | …            | …            | …              | …             |
```

Formatting:

- The header block is repeated above each table so each printed page is
  self-identifying.
- All table cells are bordered (`openpyxl.styles.Border`) and center-aligned,
  matching the provided image.
- Dates written as real date cells with number format `m/d/yyyy`.
- Times written as text strings `HH:MM` so a wrong time can be corrected
  in-place by simply typing over it (avoids Excel time-serial confusion when
  the user edits), then reprinted — no re-run required.
- Print area and page setup configured (`ws.print_area`, `ws.page_setup`,
  fit-to-width) so Table 1 and Table 2 each occupy their own page.
- Saved as `.xlsx` via `workbook.save(output_path)`.

## 6. Error Handling

| Condition                          | Behavior                                         |
|------------------------------------|--------------------------------------------------|
| `db-path` not found                | Clear error, non-zero exit                       |
| Access ODBC driver missing / wrong bitness | Clear message naming the driver and the 32/64-bit Python/driver match requirement |
| No member for `center-id`          | Warn, exit non-zero, no file written             |
| `month` outside 1–12               | argparse / validation error, non-zero exit       |
| `SADC Auth` empty/unparseable      | Treat as no authorized weekdays (all blank); warn|
| `pyodbc` connection/query error    | Clear error message, non-zero exit               |
| Rule set violates ordering         | Exception from the post-generation assertion     |

## 7. Testing (pytest)

Pure logic is factored into independently testable functions, covered without
the database or Excel:

- `get_authorized_weekdays` — parses `SADC Auth` strings into weekday sets;
  tested with `"1.3.4.5"`, empty, malformed, and separator variants.
- `get_month_dates` — produces the full date list for a month; tested across a
  31-day month, 30-day month, and February (leap and non-leap).
- `is_day_eligible` — weekday rule plus exclusions; tested with empty
  exclusions (current behavior), a vacation range, and a termination date.
- `build_daily_schedule` — tested against a custom `SCHEDULE_RULES` (e.g.
  tight windows, a 5-minute snap); asserts the post-generation ordering and
  session-length constraints hold.

Integration / manual:

- `--preview-data` prints computed row objects (no Excel write) for fast
  data verification and scripted checks.
- Manual end-to-end: run for `--center-id 24010 --year 2026 --month 5`; open
  the file and compare against the provided reference image.

## 8. Dependencies & Environment

- **Python 3** (CPython on Windows).
- **`pyodbc`** — Access connectivity via ODBC.
- **`openpyxl`** — `.xlsx` generation; no Excel install required.
- **Microsoft Access ODBC driver** (`Microsoft Access Driver (*.mdb,
  *.accdb)`), part of the Access Database Engine redistributable. **Its
  bitness must match the Python interpreter** (64-bit Python ⇒ 64-bit driver).
  This is the one new environmental risk introduced by choosing Python over
  PowerShell (whose ACE OLEDB path was already verified working this session);
  the error handling in Section 6 surfaces a bitness mismatch explicitly.
- A `requirements.txt` pins `pyodbc` and `openpyxl`.

## 9. Open Items / Future Work (not in this implementation)

- `get_member_exclusions` and the vacation/termination/other-visits table.
- Wiring `Auth BGN` / `Auth EXP` into the `is_day_eligible` exclusions.
- Optional visual marker (e.g. `VAC`) for vacation days.
- Real time-generation business rules replacing placeholder defaults.
