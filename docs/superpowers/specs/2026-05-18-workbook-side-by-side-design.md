# Workbook Side-by-Side Layout — Design

**Date:** 2026-05-18
**Status:** Approved (design); pending implementation plan
**Builds on:** `docs/superpowers/specs/2026-05-15-monthly-schedule-design.md` §5

## 1. Purpose & Scope

Change the generated workbook so that:

1. On screen, the two tables (attendance + transportation) are
   displayed **side by side**, not stacked vertically.
2. Printing still produces **each table on its own page**.
3. Every column is **wide enough to show its full text** (no
   truncation).

Only `monthly_schedule/workbook.py` changes, plus its test
`tests/test_workbook.py`. `daily_schedule.py`, `rules.py`, `rows.py`,
`db.py`, `new_monthly_schedule.py`, `travel.py`, `eligibility.py`,
`health_plan.py` are unchanged. The function signature
`build_workbook(member, rows, output_path)` is unchanged, so callers
(`new_monthly_schedule.process_member`) are unaffected.

## 2. Sheet Layout (single sheet `Schedule`)

Column blocks (1-based column indices in parentheses):

| Cols | Block |
|------|-------|
| A–D (1–4) | **Table 1** — `Date | Day | Time-In | Time-Out` |
| E (5) | spacer (visual gap; fixed width ≈ 3) |
| F–K (6–11) | **Table 2** — `Date | Day | Pick-Up Time | Arrival Time | Departure Time | Drop-Off Time` |

Both blocks start at the same top rows so they line up row-for-row
on screen:

- Rows 1–3 = the header block, written **once per block**:
  - Row 1: `Bowery Senior Care Inc` (bold)
  - Row 2: `MLTC: <display_plan(health_plan)>`
  - Row 3: `ID: <center_id>   Name: <Last, First>   Auth Days: <auth_days>`
    (a single combined string)
  - Each header line is written to that block's first column and
    **merged across the block's column span** (A1:D1, A2:D2, A3:D3
    for the left block; F1:K1, F2:K2, F3:K3 for the right block).
    Merging guarantees the long org/member text displays fully and
    never forces a data column wide.
- Row 4 = the table header row (the column labels), bold, centered,
  thin-box border.
- Rows 5 .. 4+len(rows) = one row per calendar day: `Date` as a real
  date cell formatted `m/d/yyyy`, `Day` 3-letter, the time values
  (blank string on ineligible days), every cell centered with a
  thin-box border. This is exactly today's per-row content and
  styling, only repositioned into each block's columns.

The left block's `Date` is column A; the right block's `Date` is
column F (its columns are offset by `RIGHT_FIRST_COL - 1 = 5`).

## 3. Separate-Page Printing

- A manual **column page break** is inserted after column E
  (`ws.col_breaks.append(Break(id=5))`, `Break` from
  `openpyxl.worksheet.pagebreak`). With the print area covering both
  blocks, this paginates as **Page 1 = columns A–E (Table 1 +
  spacer)**, **Page 2 = columns F–K (Table 2)**.
- `ws.print_area = "A1:K{last_row}"` where
  `last_row = 4 + len(rows)`.
- Page setup:
  - `ws.page_setup.fitToWidth = 0` — must NOT be 1; fit-to-width
    would scale every column onto a single page and cancel the
    manual column break.
  - `ws.page_setup.fitToHeight = 1` — each page scaled to one page
    tall so all ~31 day rows + header fit on one page.
  - `ws.sheet_properties.pageSetUpPr.fitToPage = True`.
  - `ws.page_setup.orientation = "portrait"`.

Net effect: opening in Excel shows both tables side by side; File →
Print yields exactly two pages, each self-identifying via its own
header block.

## 4. Column Widths (auto-size from content)

openpyxl cannot perform Excel's true AutoFit (Excel computes that on
open); widths are set explicitly.

For each data column in both blocks, width =
`max(len(str(cell_value)) for non-empty cells in that column,
including the table header label) * 1.15 + 2`, clamped to
`[4, 40]`. Set via
`ws.column_dimensions[get_column_letter(col)].width`.

The merged header lines are **excluded** from this computation (a
merged cell spans the block, so Excel renders its full text across
the merged range regardless of any single column's width). The
spacer column E is a fixed small width (≈ 3).

## 5. Components (`monthly_schedule/workbook.py`)

- Module constants: `COMPANY_NAME`, the border/alignment/font
  styles, `TABLE1_HEADERS`/`TABLE1_KEYS`,
  `TABLE2_HEADERS`/`TABLE2_KEYS` (kept). Add `LEFT_FIRST_COL = 1`,
  `SPACER_COL = 5`, `RIGHT_FIRST_COL = 6`, `SPACER_WIDTH = 3`.
- `_member_name(member)` — unchanged.
- `_write_header_block(ws, start_row, first_col, last_col, member)` —
  writes the 3 header lines, each merged across
  `[first_col, last_col]` on its row; bold on row 1; returns the
  first free row after the block (`start_row + 3`).
- `_write_table(ws, start_row, first_col, headers, keys, rows)` —
  writes the bold/centered/bordered header row then the day rows,
  with `Date` at `first_col`, `Day` at `first_col+1`, and `keys`
  starting at `first_col+2`; all cells centered + boxed; returns the
  first free row after the table.
- `_autosize_columns(ws, col_ranges)` — sets each data column's
  width per §4; sets the spacer column to `SPACER_WIDTH`.
- `build_workbook(member, rows, output_path)` — orchestrates: left
  block at `LEFT_FIRST_COL`, right block at `RIGHT_FIRST_COL`,
  header+table for each, the column break after `SPACER_COL`,
  `print_area`, page setup, autosize, save; returns `output_path`.

## 6. Error Handling

No new error paths. Inputs (`member`, `rows`) are the same as today;
an empty `rows` list still produces a valid workbook (just the two
header blocks + table-header rows, no day rows). The function still
raises naturally if the output path is unwritable (surfaced by the
caller as a `write`-stage per-member failure, unchanged).

## 7. Testing (`tests/test_workbook.py` — rewritten for the new geometry)

Build to a `tmp_path`, reload with `openpyxl.load_workbook`, assert:

- `ws["A1"].value == COMPANY_NAME` and `ws["F1"].value ==
  COMPANY_NAME` (header block per block).
- `ws["A2"].value == "MLTC: Elderplan Homefirst"` (HOF → mapped) and
  `ws["F2"].value` likewise; `ws["A3"].value` /
  `ws["F3"].value` contain `ID: 24010`, `Name: Cheng, Lizhu`,
  `Auth Days: 1.3.4.5`.
- Header line cells are merged: `"A1:D1"`, `"A2:D2"`, `"A3:D3"`,
  `"F1:K1"`, `"F2:K2"`, `"F3:K3"` are all present in
  `{str(r) for r in ws.merged_cells.ranges}`.
- Row 4 is the table-header row: cells A4..D4 ==
  `["Date","Day","Time-In","Time-Out"]`; cells F4..K4 ==
  `["Date","Day","Pick-Up Time","Arrival Time","Departure Time",
  "Drop-Off Time"]`.
- For the supplied eligible row (e.g. 2026-05-01), row 5: `A5` is a
  date cell with `number_format == "m/d/yyyy"`, `C5`/`D5` are the
  Time-In/Time-Out values; the right block on the same row 5 has the
  pickup/arrival/departure/dropoff values at H5..K5.
- The ineligible row's time cells are blank (`None`/`""`).
- Exactly one **column** break at column 5:
  `ws.col_breaks` has one break with `id == 5` (and `ws.row_breaks`
  has none).
- `ws.print_area` spans to column K (contains `"K"`).
- Column widths set: `ws.column_dimensions["E"].width == SPACER_WIDTH`
  (≈3) and a wide-label column (e.g. `H`, "Pick-Up Time") wider than
  the `Day` column (`B`).
- `ws.page_setup.fitToWidth == 0` and
  `ws.page_setup.fitToHeight == 1`.

The test fixtures (`MEMBER` with `health_plan: "HOF"`,
`auth_days: "1.3.4.5"`, plus `address`/`long_lat` keys; one eligible
+ one ineligible `ROWS` entry) match the current test file.

## 8. Out of Scope (YAGNI)

- Two-worksheet variant (cannot be side by side in one view).
- True Excel AutoFit (impossible without Excel rendering).
- Freezing panes, repeated print titles, custom page margins/scale
  beyond fit-to-height.
- Any change to which days are eligible, the times, the data, or the
  CLI.
