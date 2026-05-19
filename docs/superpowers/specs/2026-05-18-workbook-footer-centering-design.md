# Workbook Footer + Page Centering — Design

**Date:** 2026-05-18
**Status:** Approved (design); pending implementation plan
**Builds on:** `docs/superpowers/specs/2026-05-18-workbook-side-by-side-design.md`

## 1. Purpose & Scope

Two adjustments to the generated workbook:

1. Below each table, add a bold **caption** then a **Signature/Date
   write-on line** (ruled blank cells with a bottom border).
2. **Horizontally center** each table on its printed page.

Only `monthly_schedule/workbook.py` changes, plus its test
`tests/test_workbook.py`. `build_workbook(member, rows,
output_path)` keeps its signature, so `new_monthly_schedule.py` is
unaffected. No other module changes.

## 2. Current Geometry (unchanged base)

From the side-by-side layout already in place:

- Left block = Table 1 in columns **A–D** (1–4); spacer **E** (5);
  right block = Table 2 in columns **F–K** (6–11).
- Rows 1–3 = per-block header (each line merged across the block).
- Row 4 = `table_header_row` (the column labels).
- Rows 5 .. `last_data_row` = day rows, where
  `last_data_row = table_header_row + len(rows)` (= `4 + len(rows)`;
  with empty `rows`, `last_data_row == 4`, i.e. no day rows).
- Manual **column page break** after column E (`Break(id=5)`).
- `fitToWidth = 0`, `fitToHeight = 1`, portrait, `fitToPage = True`.

## 3. Footer (per block, below the data)

Three rows are appended **per block**, in that block's columns, so
each footer prints on the same page as its table:

| Row | Content |
|-----|---------|
| `last_data_row + 1` | blank spacer row (nothing written) |
| `last_data_row + 2` | **caption** — bold; left = `Attendance Sheet`, right = `Transportation Sheet`; written at the block's first column and **merged across the block's columns** (`A:D` / `F:K`) |
| `last_data_row + 3` | **Signature/Date line** (see below) |

### Signature/Date line (`last_data_row + 3`)

The write-on rule is rendered as **adjacent cells given a
bottom-only border** (no cell merge needed — abutting bottom borders
render as one continuous underline; this avoids merged-cell border
quirks and is visually identical to the approved "ruled blank
cells"). A new style constant `_RULE = Border(bottom=Side(
style="thin"))` is used.

- **Left block (A–D):**
  - `A` = `Signature:`
  - `B` = blank, `_RULE` bottom border (signature rule)
  - `C` = `Date:`
  - `D` = blank, `_RULE` bottom border (date rule)
- **Right block (F–K):**
  - `F` = `Signature:`
  - `G`, `H` = blank, each `_RULE` bottom border (signature rule)
  - `I` = `Date:`
  - `J`, `K` = blank, each `_RULE` bottom border (date rule)

Each footer spans only its own table's columns, so the left rule
segments are shorter than the right's (the left table is 4 columns,
the right 6). Labels are left-aligned, not bordered.

The new last used row is `footer_last_row = last_data_row + 3`.

## 4. Print & Page Setup

- `ws.print_area = "A1:K{footer_last_row}"` — extends the print area
  so each block's footer is on the same page as its table.
- The existing column page break and `fitToWidth=0` /
  `fitToHeight=1` / portrait / `fitToPage=True` are **unchanged**
  (fit-to-height now also scales the 3 extra footer rows onto the
  page).
- Add **horizontal print centering**:
  `ws.print_options.horizontalCentered = True`. Vertical centering
  is intentionally NOT set.

**Known openpyxl API note (verify on the red/green run):** the
attribute path is `ws.print_options.horizontalCentered` (the
`PrintOptions` object), not `ws.page_setup`. It should round-trip
through save/`load_workbook` as `True`. If openpyxl exposes or
reloads it in an equivalent-but-different form, adjust ONLY the test
assertion's form (not the behavior) to match the real round-trip and
report it — same handling pattern used for the column-break /
page-setup round-trips previously.

## 5. Auto-Size Interaction

`_autosize_columns` must scan **only `table_header_row` ..
`last_data_row`** (the data region), exactly as today — it must NOT
include the new footer rows. Consequence: the bold caption
(e.g. `Transportation Sheet`, ~19 chars) and the
`Signature:`/`Date:` labels never widen a data column. The caption
is also merged across the block (spans, doesn't dictate any single
column's width); the rule cells are empty. The spacer column E stays
fixed at `SPACER_WIDTH`.

## 6. Components (`monthly_schedule/workbook.py`)

- New constants: `_RULE = Border(bottom=Side(style="thin"))`,
  `LEFT_CAPTION = "Attendance Sheet"`,
  `RIGHT_CAPTION = "Transportation Sheet"`.
- New `_write_footer(ws, data_last_row, first_col, last_col,
  caption, rule_layout)` — writes the blank spacer row, the merged
  bold caption at `data_last_row + 2`, and the Signature/Date line at
  `data_last_row + 3` per `rule_layout` (the per-block column
  positions for `Signature:`, the signature rule cells, `Date:`, and
  the date rule cells). Called once for the left block (A–D layout)
  and once for the right block (F–K layout).
- `build_workbook` changes: after writing both tables, compute
  `last_data_row` (= `table_header_row + len(rows)`); call
  `_write_footer` for each block; set
  `footer_last_row = last_data_row + 3`; `print_area =
  "A1:K{footer_last_row}"`; `ws.print_options.horizontalCentered =
  True`; `_autosize_columns(ws, table_header_row, last_data_row)`
  (bounded to the data region).
- `_write_header_block`, `_write_table`, `_autosize_columns`'s
  internal logic, and all existing constants are otherwise
  unchanged. `COMPANY_NAME`, `build_workbook` remain importable
  unchanged.

## 7. Error Handling

No new error paths. Empty `rows` ⇒ `last_data_row == 4`; the footer
is still written at rows 5/6/7; valid workbook. An unwritable output
path still raises naturally (surfaced by the caller as a
`write`-stage per-member failure, unchanged).

## 8. Testing (`tests/test_workbook.py` — extended)

Keep all existing side-by-side assertions (per-block header at
`A1`/`F1`, merged header ranges, table-header row 4, aligned data
row 5, ineligible row blank, one column break id 5, no row breaks,
print area to column K, autosized widths, `fitToWidth==0` /
`fitToHeight==1`). Add, using the same `MEMBER`/`ROWS` fixture
(`len(ROWS) == 2` ⇒ `last_data_row = 6`, so caption row = 8,
signature row = 9):

- `ws["A8"].value == "Attendance Sheet"` and
  `"A8:D8"` in the merged-range set; `ws["F8"].value ==
  "Transportation Sheet"` and `"F8:K8"` in the merged set.
- Signature/Date row 9: `ws.cell(9,1).value == "Signature:"`,
  `ws.cell(9,3).value == "Date:"`,
  `ws.cell(9,2).border.bottom.style == "thin"`,
  `ws.cell(9,4).border.bottom.style == "thin"`; right block:
  `ws.cell(9,6).value == "Signature:"`,
  `ws.cell(9,9).value == "Date:"`,
  `ws.cell(9,7).border.bottom.style == "thin"` and
  `ws.cell(9,8).border.bottom.style == "thin"`,
  `ws.cell(9,10).border.bottom.style == "thin"` and
  `ws.cell(9,11).border.bottom.style == "thin"`.
- `ws.print_area` contains `"K9"` (spans through the footer).
- `ws.print_options.horizontalCentered is True`.
- Footer text did not bloat a data column: e.g.
  `ws.column_dimensions["F"].width < 20` (the `Transportation
  Sheet` caption, ~24 if it had counted, is excluded; column F is
  the right block's `Date` column ≈ 13.5).

Manual e2e deferred (needs a real key + unlocked DB): regenerate and
visually confirm the caption + ruled Signature/Date line under each
table and that each table is horizontally centered on its page.

## 9. Out of Scope (YAGNI)

- Vertical print centering.
- Configurable caption text or footer layout.
- Equalizing the left/right rule lengths (each footer spans its own
  table width).
- Any change to data, eligibility, the side-by-side geometry, the
  column break, or the CLI.
