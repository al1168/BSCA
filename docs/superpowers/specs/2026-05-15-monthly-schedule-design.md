# Monthly Schedule Workbook — Design

**Date:** 2026-05-15
**Status:** Approved (design); pending implementation plan

## 1. Purpose & Scope

A new PowerShell script, `New-MonthlySchedule.ps1`, generates a printable Excel
workbook for **one SADC member** for **one month**. The workbook contains two
tables:

1. **Attendance** — Date, Day, Time-In, Time-Out
2. **Transportation** — Date, Day, Pick-Up Time, Arrival Time, Departure Time,
   Drop-Off Time

Member identity/header data comes from the Access database. The times are
**script-generated placeholders** for now; real business rules ("restrictions")
are layered in later through designed seams (Sections 4).

`Get-Contact.ps1` is left unchanged — it remains the interactive lookup tool.
`New-MonthlySchedule.ps1` is self-contained and runs its own scoped query, so
there is no unrelated refactor of existing code.

## 2. Parameters

| Parameter     | Type   | Required | Default                                                            |
|---------------|--------|----------|--------------------------------------------------------------------|
| `-CenterID`   | int    | Yes      | —                                                                  |
| `-Year`       | int    | Yes      | —                                                                  |
| `-Month`      | int    | Yes      | — (validated 1–12)                                                  |
| `-DbPath`     | string | No       | `\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb`           |
| `-OutputPath` | string | No       | `.\Schedule_<CenterID>_<YYYY-MM>.xlsx`                              |
| `-PreviewData`| switch | No       | off — when set, emit computed row objects and skip Excel entirely  |

## 3. Data Flow

1. Connect to Access via `Microsoft.ACE.OLEDB.12.0` (provider confirmed present
   on this machine).
2. Query `SELECT [Center ID], [Last Name], [First Name], [Health Plan],
   [SADC Auth] FROM [Contacts] WHERE [Center ID] = ?`.
3. **No matching row** → warn and exit with a non-zero code; no file written.
   **DB path missing** → throw (same behavior as `Get-Contact.ps1`).
4. Parse `SADC Auth` (e.g. `"1.3.4.5"`) into a set of weekday numbers using the
   encoding **1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat, 7=Sun**. Split on any
   non-digit separator.
5. Build every calendar date from the 1st through the last day of
   `Year`/`Month`.
6. For each date, compute the 3-letter day abbreviation (`Fri`, `Sat`, …) and
   determine eligibility (Section 4).

### Column mapping (confirmed against the live DB schema)

| Header field         | Source                                             |
|----------------------|----------------------------------------------------|
| `ID`                 | `Center ID` (also the `-CenterID` parameter)       |
| `Name`               | `Last Name` + `, ` + `First Name`                  |
| `Auth Days`          | `SADC Auth` (raw string shown in header)            |
| `MLTC`               | `Health Plan`                                      |
| Company name         | Fixed constant `Bowery Senior Care Inc`            |

## 4. Time Generation & Day Eligibility

### 4a. Day eligibility — single seam

The decision "should this date get generated times?" is isolated in one
function, `Test-DayEligible`, consulted per date by `New-DailySchedule`.

- **Now:** a date is eligible ⟺ its weekday is in the authorized set parsed
  from `SADC Auth`.
- `Test-DayEligible` accepts an optional **exclusions** parameter (default
  empty): a list of date ranges plus an optional termination date. With an
  empty default, behavior is identical to today.
- This is the **single seam** through which all future date-affecting sources
  plug in, with no restructuring:
  - **Vacation ranges** (e.g. 5/10/2026–5/16/2026) → those dates ineligible.
  - **Termination date** (e.g. 5/10/2026) → that date and all later dates
    ineligible.
  - **Auth period** (`Auth BGN` / `Auth EXP`) → dates outside the window
    ineligible.
  - **Other visit types** → represented as additional exclusion entries.
- A future `Get-MemberExclusions` function will read a separate
  vacation/termination table and produce the exclusions list, which
  `New-MonthlySchedule` will pass in. **That table and its reader are NOT built
  now** — only the parameter seam and the empty default are built.

### 4b. Time generation — extendable rules object

A single `$ScheduleRules` object at the top of the script defines all tunable
constraints; `New-DailySchedule` reads from it and never hardcodes times.

Rules object holds, per plan:

- `ArrivalWindow` = { Earliest, Latest }
- `DepartureWindow` = { Earliest, Latest }
- `MinSessionHours`, `MaxSessionHours`
- `PickUpLeadMin` = { Min, Max } — minutes before Arrival
- `DropOffTrailMin` = { Min, Max } — minutes after Departure
- `TimeInDriftMin` = { Min, Max } — Time-In relative to Arrival
- `TimeOutDriftMin` = { Min, Max } — Time-Out relative to Departure
- `RoundToMinutes` — snap generated times (1 = no snap; 5 = snap to :05)

**Per-plan keying:** `$ScheduleRules` is keyed by `Health Plan`, with a
`Default` entry used when the member's plan has no specific entry. Built now
because `Health Plan` is already pulled and it is only a few lines.

**Placeholder defaults** (modeled on the provided image — a morning half-day
session ≈ 08:00–12:30):

- Arrival ≈ 08:15, window 08:05–08:25
- Departure ≈ 12:15, window 12:05–12:25
- Pick-Up = Arrival − 8–12 min
- Drop-Off = Departure + 8–12 min
- Time-In = Arrival + 0–3 min
- Time-Out = Departure − 0–3 min
- `RoundToMinutes` = 1, `MinSessionHours` = 3, `MaxSessionHours` = 6

**One coherent schedule per eligible day:** Arrival and Departure are drawn
within their windows; Pick-Up/Drop-Off and Time-In/Time-Out are derived from
them so both tables stay mutually consistent for the same day.

**Post-generation assertion:** after the rules are applied,
`New-DailySchedule` re-validates the ordering and session length:

```
Pick-Up < Arrival ≤ Time-In   …   Time-Out ≤ Departure < Drop-Off
MinSessionHours ≤ (Departure − Arrival) ≤ MaxSessionHours
```

A rule combination that violates this fails loudly (thrown error / failing
test) rather than emitting silent garbage.

### 4c. Rendering of ineligible days

An ineligible day (non-authorized weekday, future vacation, or post-termination)
renders the same way: the row shows Date + Day, and all time cells are blank.
A future visual marker for vacation days (e.g. a `VAC` label) would be a small
additive change at render time — noted as optional future, **not built now**.

### 4d. Explicitly out of scope (YAGNI, confirmed)

- No separate vacation/termination table schema.
- No exclusion-source reading code (`Get-MemberExclusions` deferred).
- No scriptblock/plug-in constraint engine.

Only the `Test-DayEligible` seam (empty default) and the `$ScheduleRules`
object plus the post-generation assertion are built now.

## 5. Workbook Layout

Built via **Excel COM automation** (Office is present on this machine;
`ImportExcel` is not installed and no install is required). The workbook size
(~62 data rows total) is far below any COM performance concern.

Single worksheet, named `Schedule`, two tables stacked vertically with a
**manual page break** between them so each prints on its own page:

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
- All table cells are bordered and center-aligned, matching the provided image.
- Dates formatted `M/d/yyyy`; times formatted `HH:mm`.
- Time values are written into **normal editable cells** so a wrong time can be
  corrected in-place and reprinted, with no re-run.
- Print areas / page breaks are configured so Table 1 and Table 2 each occupy
  their own page.
- The file is saved as `.xlsx`. Excel is quit and all COM objects released in a
  `finally` block to prevent orphaned `EXCEL.EXE` processes.

## 6. Error Handling

| Condition                       | Behavior                                          |
|---------------------------------|---------------------------------------------------|
| `DbPath` not found              | Throw (matches `Get-Contact.ps1`)                 |
| No member for `CenterID`        | Warn, exit non-zero, no file written              |
| `Month` outside 1–12            | Parameter validation error                        |
| `SADC Auth` empty/unparseable   | Treat as no authorized weekdays (all blank); warn |
| Excel COM unavailable / fails   | Clear error message                               |
| Any failure after Excel started | Excel quit + COM released in `finally`            |
| Rule set violates ordering      | Throw from post-generation assertion              |

## 7. Testing

Pure logic is factored into independently testable functions, covered by
Pester without the database or Excel:

- `Get-AuthorizedWeekdays` — parses `SADC Auth` strings into weekday sets;
  tested with `"1.3.4.5"`, empty, malformed, and separator variants.
- `Get-MonthDates` — produces the full date list for a month; tested across a
  31-day month, 30-day month, and February (leap and non-leap).
- `Test-DayEligible` — weekday rule plus exclusions; tested with empty
  exclusions (current behavior), a vacation range, and a termination date.
- `New-DailySchedule` — tested against a custom `$ScheduleRules` (e.g. tight
  windows, a 5-minute snap); asserts the post-generation ordering and
  session-length constraints hold.

Integration / manual:

- `-PreviewData` switch emits computed row objects (no Excel) for fast
  data verification and scripted checks.
- Manual end-to-end: run for `CenterID 24010`, May 2026; open the file and
  compare against the provided reference image.

## 8. Open Items / Future Work (not in this implementation)

- `Get-MemberExclusions` and the vacation/termination/other-visits table.
- Wiring `Auth BGN` / `Auth EXP` into the `Test-DayEligible` exclusions.
- Optional visual marker (e.g. `VAC`) for vacation days.
- Real time-generation business rules replacing placeholder defaults.
