# Workbook Side-by-Side Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the two schedule tables side by side on one sheet (each with its own merged header block), with a manual column page break so each still prints on its own page, and content-sized column widths so no text truncates.

**Architecture:** `monthly_schedule/workbook.py` is rewritten in place: per-block header (3 lines, each merged across the block's columns), `_write_table` offset to a starting column, a column page break after spacer column E, content-based column widths, and `fitToWidth=0`/`fitToHeight=1` page setup. `tests/test_workbook.py` is rewritten for the new geometry. `build_workbook(member, rows, output_path)` keeps its signature, so `new_monthly_schedule.process_member` is unaffected. No other module changes.

**Tech Stack:** Python 3.13, openpyxl, pytest. Tests run from repo root with `python -m pytest`. Windows, `python`.

**Spec:** `docs/superpowers/specs/2026-05-18-workbook-side-by-side-design.md`

---

## File Structure

| File | Change |
|------|--------|
| `monthly_schedule/workbook.py` | Full rewrite: side-by-side geometry, merged per-block headers, column page break, autosize, page setup. Public name `build_workbook` and `COMPANY_NAME` unchanged. |
| `tests/test_workbook.py` | Full rewrite of the single structural test for the new geometry. |

The test and implementation change together (the geometry change is holistic — splitting would leave a broken intermediate), so this is **one atomic task** (test-first), followed by a deferred manual-verification task.

**Known openpyxl API risks (verify on the red/green run):** column page breaks via `ws.col_breaks.append(Break(id=5))` and reading them back as `ws.col_breaks.count` / `list(ws.col_breaks.brk)[0].id`; and `ws.page_setup.fitToWidth`/`fitToHeight` round-tripping as ints `0`/`1`. These mirror the row-break + date round-trip patterns already proven in this codebase. If openpyxl reads any of these back in a different but equivalent form, adjust ONLY the test assertion's form (not the behavior) to match the real round-trip, and report it as DONE_WITH_CONCERNS with the exact diff and rationale.

---

## Task 1: Rewrite workbook.py side-by-side + its test (atomic, test-first)

**Files:** Modify `monthly_schedule/workbook.py`, `tests/test_workbook.py`.

- [ ] **Step 1: Replace `tests/test_workbook.py` entirely with the new geometry test**

Replace the full contents of `tests/test_workbook.py` with:

```python
from datetime import date, datetime

from openpyxl import load_workbook

from monthly_schedule.workbook import build_workbook, COMPANY_NAME

MEMBER = {
    "center_id": 24010,
    "last_name": "Cheng",
    "first_name": "Lizhu",
    "health_plan": "HOF",
    "auth_days": "1.3.4.5",
}

ROWS = [
    {
        "date": date(2026, 5, 1), "day": "Fri",
        "pickup": "08:05", "arrival": "08:15", "time_in": "08:17",
        "time_out": "12:13", "departure": "12:15", "dropoff": "12:25",
    },
    {
        "date": date(2026, 5, 2), "day": "Sat",
        "pickup": "", "arrival": "", "time_in": "",
        "time_out": "", "departure": "", "dropoff": "",
    },
]


def test_side_by_side_workbook_structure(tmp_path):
    out = tmp_path / "sched.xlsx"
    build_workbook(MEMBER, ROWS, str(out))
    assert out.exists()

    wb = load_workbook(str(out))
    ws = wb["Schedule"]

    # per-block header: left block at col A, right block at col F
    assert ws["A1"].value == COMPANY_NAME
    assert ws["F1"].value == COMPANY_NAME
    assert ws["A2"].value == "MLTC: Elderplan Homefirst"
    assert ws["F2"].value == "MLTC: Elderplan Homefirst"
    for cell in ("A3", "F3"):
        v = ws[cell].value
        assert "ID: 24010" in v
        assert "Name: Cheng, Lizhu" in v
        assert "Auth Days: 1.3.4.5" in v

    # each header line merged across its block's columns
    merged = {str(rng) for rng in ws.merged_cells.ranges}
    for rng in ("A1:D1", "A2:D2", "A3:D3",
                "F1:K1", "F2:K2", "F3:K3"):
        assert rng in merged

    # table-header row is row 4 for both blocks
    assert [ws.cell(row=4, column=c).value
            for c in range(1, 5)] == [
        "Date", "Day", "Time-In", "Time-Out"
    ]
    assert [ws.cell(row=4, column=c).value
            for c in range(6, 12)] == [
        "Date", "Day", "Pick-Up Time", "Arrival Time",
        "Departure Time", "Drop-Off Time",
    ]

    # first data row (row 5), left and right blocks aligned
    assert ws.cell(row=5, column=1).value == datetime(2026, 5, 1)
    assert ws.cell(row=5, column=1).number_format == "m/d/yyyy"
    assert ws.cell(row=5, column=3).value == "08:17"   # Time-In
    assert ws.cell(row=5, column=4).value == "12:13"   # Time-Out
    assert ws.cell(row=5, column=6).value == datetime(2026, 5, 1)
    assert ws.cell(row=5, column=6).number_format == "m/d/yyyy"
    assert ws.cell(row=5, column=8).value == "08:05"   # Pick-Up
    assert ws.cell(row=5, column=9).value == "08:15"   # Arrival
    assert ws.cell(row=5, column=10).value == "12:15"  # Departure
    assert ws.cell(row=5, column=11).value == "12:25"  # Drop-Off

    # ineligible row (row 6) blank in both blocks
    assert ws.cell(row=6, column=3).value in (None, "")
    assert ws.cell(row=6, column=8).value in (None, "")

    # exactly one COLUMN break at column 5; no row breaks
    assert ws.col_breaks.count == 1
    assert list(ws.col_breaks.brk)[0].id == 5
    assert ws.row_breaks.count == 0

    # print area spans to column K
    assert ws.print_area is not None
    assert "K" in ws.print_area

    # spacer column fixed width; a wide label column wider than Day
    assert ws.column_dimensions["E"].width == 3
    assert (ws.column_dimensions["H"].width
            > ws.column_dimensions["B"].width)

    # page setup: not fit-to-width, fit each page to one page tall
    assert ws.page_setup.fitToWidth == 0
    assert ws.page_setup.fitToHeight == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_workbook.py -q`
Expected: FAIL — the current stacked layout puts `COMPANY_NAME` only at `A1` (not `F1`), uses a row break (not a column break at col 5), no merged ranges, no column widths set, etc.

- [ ] **Step 3: Replace `monthly_schedule/workbook.py` entirely**

Replace the full contents of `monthly_schedule/workbook.py` with:

```python
"""Render the two schedule tables side by side in one workbook.

Both tables sit on one sheet so they display side by side when the
file is opened; a manual column page break between them makes each
print on its own page. Header lines are merged across each table's
column span so long text shows fully without widening a data column.
"""

from openpyxl import Workbook
from openpyxl.styles import Border, Side, Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.pagebreak import Break

from monthly_schedule.health_plan import display_plan

COMPANY_NAME = "Bowery Senior Care Inc"

_THIN = Side(style="thin")
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center")
_BOLD = Font(bold=True)

TABLE1_HEADERS = ["Date", "Day", "Time-In", "Time-Out"]
TABLE1_KEYS = ["time_in", "time_out"]
TABLE2_HEADERS = [
    "Date", "Day", "Pick-Up Time", "Arrival Time",
    "Departure Time", "Drop-Off Time",
]
TABLE2_KEYS = ["pickup", "arrival", "departure", "dropoff"]

LEFT_FIRST_COL = 1                      # A
SPACER_COL = 5                          # E
RIGHT_FIRST_COL = 6                     # F
SPACER_WIDTH = 3
HEADER_ROWS = 3                         # company / MLTC / ID-Name-Auth
_WIDTH_FACTOR = 1.15
_WIDTH_PAD = 2
_WIDTH_MIN = 4
_WIDTH_MAX = 40


def _member_name(member):
    return f"{member['last_name']}, {member['first_name']}"


def _write_header_block(ws, start_row, first_col, last_col, member):
    """Write the 3 header lines, each merged across [first_col,
    last_col]. Returns the first free row after the block."""
    lines = (
        COMPANY_NAME,
        f"MLTC: {display_plan(member['health_plan'])}",
        (
            f"ID: {member['center_id']}   "
            f"Name: {_member_name(member)}   "
            f"Auth Days: {member['auth_days']}"
        ),
    )
    for offset, text in enumerate(lines):
        row = start_row + offset
        cell = ws.cell(row=row, column=first_col, value=text)
        if offset == 0:
            cell.font = _BOLD
        ws.merge_cells(
            start_row=row, start_column=first_col,
            end_row=row, end_column=last_col,
        )
    return start_row + HEADER_ROWS


def _write_table(ws, start_row, first_col, headers, keys, rows):
    """Write the table-header row then one row per day, with Date at
    `first_col`, Day next, then `keys`. Returns the first free row
    after the table."""
    for offset, text in enumerate(headers):
        cell = ws.cell(row=start_row, column=first_col + offset,
                       value=text)
        cell.font = _BOLD
        cell.alignment = _CENTER
        cell.border = _BOX
    r = start_row + 1
    for row in rows:
        date_cell = ws.cell(row=r, column=first_col,
                            value=row["date"])
        date_cell.number_format = "m/d/yyyy"
        ws.cell(row=r, column=first_col + 1, value=row["day"])
        for k_off, key in enumerate(keys):
            ws.cell(row=r, column=first_col + 2 + k_off,
                    value=row[key])
        for col_off in range(len(headers)):
            cell = ws.cell(row=r, column=first_col + col_off)
            cell.alignment = _CENTER
            cell.border = _BOX
        r += 1
    return r


def _autosize_columns(ws, table_header_row, last_row):
    """Width per data column = longest value/label in it (rows from
    the table-header row down; merged header lines excluded) scaled
    and clamped. Spacer column fixed."""
    data_cols = (
        list(range(LEFT_FIRST_COL,
                    LEFT_FIRST_COL + len(TABLE1_HEADERS)))
        + list(range(RIGHT_FIRST_COL,
                      RIGHT_FIRST_COL + len(TABLE2_HEADERS)))
    )
    for col in data_cols:
        longest = 0
        for r in range(table_header_row, last_row + 1):
            value = ws.cell(row=r, column=col).value
            if value is None:
                continue
            longest = max(longest, len(str(value)))
        width = longest * _WIDTH_FACTOR + _WIDTH_PAD
        width = max(_WIDTH_MIN, min(_WIDTH_MAX, width))
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.column_dimensions[
        get_column_letter(SPACER_COL)
    ].width = SPACER_WIDTH


def build_workbook(member, rows, output_path):
    """Write the side-by-side workbook to output_path; return it."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Schedule"

    left_last_col = LEFT_FIRST_COL + len(TABLE1_HEADERS) - 1   # D
    right_last_col = RIGHT_FIRST_COL + len(TABLE2_HEADERS) - 1  # K

    _write_header_block(ws, 1, LEFT_FIRST_COL, left_last_col,
                        member)
    _write_header_block(ws, 1, RIGHT_FIRST_COL, right_last_col,
                        member)
    table_header_row = 1 + HEADER_ROWS                         # 4

    end_left = _write_table(ws, table_header_row, LEFT_FIRST_COL,
                            TABLE1_HEADERS, TABLE1_KEYS, rows)
    end_right = _write_table(ws, table_header_row, RIGHT_FIRST_COL,
                             TABLE2_HEADERS, TABLE2_KEYS, rows)
    last_row = max(end_left, end_right) - 1

    # column page break after spacer col E -> Table 1 | Table 2 pages
    ws.col_breaks.append(Break(id=SPACER_COL))

    ws.print_area = (
        f"A1:{get_column_letter(right_last_col)}{last_row}"
    )
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 0
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    _autosize_columns(ws, table_header_row, last_row)

    wb.save(output_path)
    return output_path
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_workbook.py -q`
Expected: PASS. If a `col_breaks`/`page_setup` assertion fails purely because openpyxl round-trips that attribute in an equivalent-but-different form (e.g. `fitToWidth` as `"0"` string, or `col_breaks` exposed differently), adjust ONLY that assertion's form to match the real reload (keeping the same behavioral intent), re-run, and report DONE_WITH_CONCERNS with the exact diff + why. Do NOT change `workbook.py`'s behavior to satisfy a cosmetic assertion-form mismatch.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: ALL pass. `new_monthly_schedule.process_member` calls `build_workbook(member, rows, path)` with the unchanged signature, and `test_cli.py` stubs/asserts only file existence and the summary — not internal cell geometry — so no CLI test regresses. Confirm the exact count and that the only workbook-related test is the new `test_side_by_side_workbook_structure`.

- [ ] **Step 6: Commit**

```bash
git add monthly_schedule/workbook.py tests/test_workbook.py
git commit -m "feat: side-by-side workbook layout with column page break"
```

---

## Task 2: Manual end-to-end verification (deferred — document only)

**Files:** none (no code, no commit).

- [ ] **Step 1: Full suite once more**

Run: `python -m pytest -q`
Expected: ALL pass.

- [ ] **Step 2: Document the manual visual check**

A true visual confirmation needs a real generated workbook opened in Excel (needs a key in `google_maps.config` and an unlocked DB). Record, for the user to run later:

```
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5 --output-path .\out
```

Then open `.\out\Schedule_24010_2026-05.xlsx` and confirm:
- Both tables appear **side by side** on the one `Schedule` sheet, each with its own header block, no truncated text.
- `File → Print` preview shows **two pages**: page 1 = the Time-In/Time-Out table, page 2 = the Pick-Up/Arrival/Departure/Drop-Off table.

This is not run in CI; the mocked structural test in Task 1 is the automated gate. No commit (nothing changed).

---

## Self-Review

**1. Spec coverage:**

- §1 scope / only `workbook.py` + its test change, `build_workbook` signature unchanged → Task 1 (no other files touched; verified by full suite in Step 5).
- §2 layout: left block A–D, spacer E, right block F–K; per-block 3-line header with line 3 the combined `ID:/Name:/Auth Days:` string; each header line merged across the block; table-header row 4; day rows from row 5; Date `m/d/yyyy` → `_write_header_block` (merge), `_write_table` (offset), `build_workbook` placement; asserted by the merged-range, A1/F1, row-4, and row-5 assertions.
- §3 separate-page printing: column break after col E (`Break(id=SPACER_COL=5)`), `print_area A1:K{last_row}`, `fitToWidth=0`, `fitToHeight=1`, `fitToPage=True`, portrait → `build_workbook`; asserted by the col_breaks/row_breaks/print_area/page_setup assertions.
- §4 auto-size from content: `_autosize_columns` longest value/label × 1.15 + 2 clamped [4,40], header lines excluded (loop starts at `table_header_row`), spacer fixed `SPACER_WIDTH` → asserted by `E == 3` and `H > B`.
- §5 components: `_member_name`, `_write_header_block`, `_write_table`, `_autosize_columns`, `build_workbook`, the new constants — all present with the spec'd signatures.
- §6 error handling: no new paths; empty `rows` → `_write_table` returns `table_header_row+1`, `last_row = table_header_row` (= 4), `print_area A1:K4`, autosize over header row only — valid workbook; unwritable path still raises naturally (caller's `write` stage).
- §7 testing: every listed assertion is in `test_side_by_side_workbook_structure` (A1/F1, A2/F2, A3/F3 substrings, six merged ranges, both table-header rows, aligned row 5 incl. right-block Date format, blank ineligible cells in both blocks, one column break id 5 + zero row breaks, print area to K, spacer width + H>B, fitToWidth 0 / fitToHeight 1).
- §8 out of scope: no second worksheet, no true AutoFit, no freeze/print-titles/custom margins, no data/eligibility/CLI change — none implemented.

No gaps.

**2. Placeholder scan:** No "TBD/handle errors/similar to". Both files are given as complete replacements; every run step has an exact command + expected outcome; the one anticipated openpyxl-API uncertainty is explicitly bounded (adjust assertion form only, report it) rather than left vague.

**3. Type/name consistency:** `COMPANY_NAME`, `TABLE1_HEADERS/KEYS`, `TABLE2_HEADERS/KEYS`, `LEFT_FIRST_COL=1`, `SPACER_COL=5`, `RIGHT_FIRST_COL=6`, `SPACER_WIDTH=3`, `HEADER_ROWS=3`, `_member_name`, `_write_header_block(ws,start_row,first_col,last_col,member)`, `_write_table(ws,start_row,first_col,headers,keys,rows)`, `_autosize_columns(ws,table_header_row,last_row)`, `build_workbook(member,rows,output_path)` — consistent between `workbook.py` and the test's expected geometry (left D=col4, right K=col11, break id 5, table-header row 4, data row 5). `build_workbook`/`COMPANY_NAME` remain importable exactly as `tests/test_workbook.py` and `new_monthly_schedule.py` expect.

No issues found.
