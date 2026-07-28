# Per-Plan Active Member Counts (Plan Table) — Design

**Date:** 2026-07-28
**Status:** Approved

## Problem

Choosing "Entire Plan" today means picking a bare plan code from a
small dropdown with no sense of scale: the user can't see how many
members a plan run will produce, or how plans compare. The user
provided an HTML mockup showing the desired replacement: a table of
plans with Active/Inactive member counts, an All Members total row,
row-click selection wired to the Who radios, roster captions, and a
scope caption under the Generate button.

## Decision summary (user-confirmed)

- **Full table replaces the plan dropdown** (mockup), not counts
  appended to the dropdown items.
- **Active = enrolled in the selected month**: a member is active for
  (year, month) when an Enrollment row overlaps any day of that month
  (`start_date <= month_end AND (end_date IS NULL OR end_date >=
  month_start)`) — the same overlap rule the scheduler's eligibility
  uses. Counts react to the Month/Year pickers.
- Inactive = the plan's remaining members (total − active).
- The custom day-range picker does NOT affect counts (month
  granularity).
- Scope caption counts **active members**, not "timesheets" (the
  mockup's wording overpromises: authorization gaps and absences can
  still skip an active member).

## Components

### 1. Counts query (`monthly_schedule/db.py`)

New `get_plan_member_counts(db_path, month_start, month_end)` returning
`{"plans": {plan_code: {"total": int, "active": int}}, "total_active": int}`:

- Query 1 — totals per plan:
  `SELECT [Health Plan], COUNT(*) FROM [Contacts] WHERE [Center ID] IS
  NOT NULL GROUP BY [Health Plan]`
- Query 2 — active per plan (Access supports EXISTS, not
  COUNT(DISTINCT)):
  `SELECT c.[Health Plan], COUNT(*) FROM [Contacts] c WHERE
  c.[Center ID] IS NOT NULL AND EXISTS (SELECT 1 FROM [Enrollment] e
  WHERE e.[Center ID] = c.[Center ID] AND e.[start_date] <= ? AND
  (e.[end_date] IS NULL OR e.[end_date] >= ?)) GROUP BY c.[Health Plan]`
- Plan codes are normalized (strip/upper) to match the existing
  case-insensitive Access comparisons; NULL/blank plans are kept under
  a `""` key so the All Members total is honest.
- `total_active` sums active across ALL plans, including codes not in
  the GUI's 8-plan list (All Members runs schedule everyone).
- Same FileNotFoundError/RuntimeError contract as the other db helpers.

### 2. Background counts worker (`gui/counts_worker.py`, new file)

`CountsWorker(QThread)` with `finished(bool, dict)`: calls
`get_plan_member_counts`, emits `(True, counts)` or `(False,
{"error": str})`. Mirrors the existing worker patterns
(schedule/print workers); COM is not involved so no pythoncom needed.

### 3. Plan table UI (`gui/main_window.py`)

Replace `_plan_combo` with a `QTableWidget` inside the Who group:

- Columns: Plan / Active members / Inactive (headers via i18n).
  8 fixed rows from `PLAN_CODES` plus a bold **All Members** total row.
  Read-only, no vertical scrollbar (height fits 9 rows + header),
  row-level selection.
- Row click → check the "Entire Plan" radio + remember that plan code;
  All Members row click → check the "All Members" radio. Selecting
  Single/Multiple modes clears the table highlight (table stays
  visible). The reverse also holds: checking "Entire Plan" with no row
  chosen defaults to the first plan.
- Count cells show "—" until counts arrive (and on failure).
- Footer captions under the table: "Roster for {month} {year}"
  (selected month, not today) and "Inactive members are excluded from
  generated timesheets." On counts failure the roster caption becomes
  "Member counts unavailable" (no popup — counts are informational).
- Scope caption (small, gray, centered `QLabel`) directly under the
  Generate button, visible only in Entire Plan / All Members modes:
  - plan: "{n} active member(s) for {plan} in {month} {year}"
  - all: "{n} active member(s) across all plans in {month} {year}"

### 4. Refresh triggers

Counts reload: once on window open; on Month/Year change (debounced
~300 ms single-shot QTimer so spinning through months doesn't hammer
Access); after Settings saves a changed `db_path`. Only the latest
in-flight worker's result is applied (stale results discarded).

### 5. Generation plumbing

`mode == "plan"` reads the selected plan code from the table state —
the same code string previously read from `_plan_combo`, so
validation, worker, CLI, and output-folder naming are untouched.
`_validate` gains nothing new: a plan is always selected in plan mode
(default first row).

### 6. i18n (`gui/i18n.py`)

New en+zh keys: table headers (plan/active/inactive), a dedicated
"All Members" total-row label (`plan_table.all_members` — independent
of the radio's key so the two can diverge), roster caption, exclusion
caption, counts-unavailable caption, and the two scope captions. Existing key-parity test covers both languages.

## Error handling

- DB missing/unreadable: cells show "—", roster caption shows the
  unavailable message; generation validation still reports DB problems
  exactly as today when the user actually runs.
- Counts worker never blocks the UI; failures never popup.
- A plan with zero members still renders (0 / 0) and remains
  selectable; generation then reports "no members" as it does today.

## Testing

- `tests/test_db.py`: `get_plan_member_counts` against the script-built
  test DBs — overlap rule (starts before month-end, ends after
  month-start, NULL end), inactive math, NULL Center ID skipped,
  blank/unknown plan bucketed under `""`, `total_active` includes
  unknown plans.
- Counts→row-model mapping (pure function): 8 fixed codes always
  present, missing plans → 0/0, "—" placeholder state, total row math.
- Scope caption wording for plan/all modes (en).
- Debounce: rapid month changes collapse to one query (QTimer test
  pattern as in existing worker tests).
- i18n key parity (existing test).
