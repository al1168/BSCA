# Attendance Column Widths + Signature/Date Line Minimum Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Attendance (left) table columns a 16-wide floor so it fills the page, and guarantee a minimum Signature/Date rule-line length in both footers.

**Architecture:** `_autosize_columns` gains a left-block-only `_LEFT_MIN_WIDTH` floor; a new pure `_ensure_line_min` helper runs after autosize and raises (only increasing) the rule columns so each line meets its minimum; `build_workbook` calls it four times (left/right × signature/date). `tests/test_workbook.py` is updated (full-file replacement) — the now-invalid `H > B` assertion is removed and width-minimum assertions added. `build_workbook(member, rows, output_path)` signature unchanged; no other module changes.

**Tech Stack:** Python 3.13, openpyxl, pytest. Tests run from repo root with `python -m pytest`. Windows, `python`.

**Spec:** `docs/superpowers/specs/2026-05-18-attendance-widths-line-min-design.md`

---

## File Structure

| File | Change |
|------|--------|
| `monthly_schedule/workbook.py` | Full-file replacement: add `_LEFT_MIN_WIDTH=16`/`_SIG_LINE_MIN=22`/`_DATE_LINE_MIN=14`; left-block floor in `_autosize_columns`; new `_ensure_line_min`; four calls in `build_workbook` after autosize. Everything else unchanged. |
| `tests/test_workbook.py` | Full-file replacement: existing assertions kept EXCEPT the removed `H > B` line; new width-minimum assertions appended. |

The test and implementation change together → **one atomic test-first task**, then a deferred manual-verification task.

---

## Task 1: Left-block width floor + line minimum (atomic, test-first)

**Files:** Modify `monthly_schedule/workbook.py`, `tests/test_workbook.py` (both FULL-FILE replacements).

- [ ] **Step 1: Replace the ENTIRE contents of `tests/test_workbook.py` with:**

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

    # print area spans to column K, through the footer (row 9)
    assert ws.print_area is not None
    assert "K" in ws.print_area
    assert "K9" in ws.print_area.replace("$", "")

    # spacer column fixed width (unchanged)
    assert ws.column_dimensions["E"].width == 3

    # page setup: not fit-to-width, fit each page to one page tall
    assert ws.page_setup.fitToWidth == 0
    assert ws.page_setup.fitToHeight == 1

    # --- footer: bold caption merged per block ---
    # ROWS has 2 entries -> last_data_row = 6, caption row 8, sig row 9
    assert ws["A8"].value == "Attendance Sheet"
    assert ws["F8"].value == "Transportation Sheet"
    assert "A8:D8" in merged
    assert "F8:K8" in merged

    # --- signature/date row 9 with ruled (bottom-border) blanks ---
    assert ws.cell(row=9, column=1).value == "Signature:"
    assert ws.cell(row=9, column=3).value == "Date:"
    assert ws.cell(row=9, column=2).border.bottom.style == "thin"
    assert ws.cell(row=9, column=4).border.bottom.style == "thin"
    assert ws.cell(row=9, column=6).value == "Signature:"
    assert ws.cell(row=9, column=9).value == "Date:"
    for c in (7, 8, 10, 11):
        assert ws.cell(row=9, column=c).border.bottom.style == "thin"

    # --- horizontal print centering on ---
    assert ws.print_options.horizontalCentered is True

    # --- footer text did NOT bloat a data column ---
    # (autosize is bounded to the data region; col F is the right
    # Date col ~13.5 and is not a rule column)
    assert ws.column_dimensions["F"].width < 20

    # --- Attendance (left) column minimum: each left col >= 16 ---
    for c in ("A", "B", "C", "D"):
        assert ws.column_dimensions[c].width >= 16 - 1e-6

    # --- guaranteed Signature/Date line lengths (both footers) ---
    assert ws.column_dimensions["B"].width >= 22 - 1e-6   # left sig
    assert ws.column_dimensions["D"].width >= 14 - 1e-6   # left date
    assert (ws.column_dimensions["G"].width
            + ws.column_dimensions["H"].width) >= 22 - 1e-6
    assert (ws.column_dimensions["J"].width
            + ws.column_dimensions["K"].width) >= 14 - 1e-6

    # --- left 16-floor is NOT applied to the right block ---
    assert ws.column_dimensions["G"].width < 16
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_workbook.py -q`
Expected: FAIL — the current build leaves left columns at content width (e.g. `B` ≈ 5.45, not ≥ 16 or ≥ 22), so the new minimum assertions fail. (`column_dimensions["A"].width >= 16` is the first to fail; the removed `H > B` line is gone so it does not error.)

- [ ] **Step 3: Replace the ENTIRE contents of `monthly_schedule/workbook.py` with:**

```python
"""Render the two schedule tables side by side in one workbook.

Both tables sit on one sheet so they display side by side when the
file is opened; a manual column page break between them makes each
print on its own page. Header lines are merged across each table's
column span so long text shows fully without widening a data column.
Each table has a bold caption and a ruled Signature/Date line below
it, and is horizontally centered on its printed page. The Attendance
(left) columns have a generous minimum width so that table fills the
page; the Signature/Date rule lines are guaranteed a minimum length
in both footers.
"""

from openpyxl import Workbook
from openpyxl.styles import Border, Side, Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.pagebreak import Break

from monthly_schedule.health_plan import display_plan

COMPANY_NAME = "Bowery Senior Care Inc"

_THIN = Side(style="thin")
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_RULE = Border(bottom=_THIN)
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
LEFT_CAPTION = "Attendance Sheet"
RIGHT_CAPTION = "Transportation Sheet"
_WIDTH_FACTOR = 1.15
_WIDTH_PAD = 2
_WIDTH_MIN = 4
_WIDTH_MAX = 40
_LEFT_MIN_WIDTH = 16                    # Attendance (left) column floor
_SIG_LINE_MIN = 22                      # min total Signature rule width
_DATE_LINE_MIN = 14                     # min total Date rule width


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


def _write_footer(ws, data_last_row, first_col, last_col, caption,
                  sig_label_col, sig_rule_cols,
                  date_label_col, date_rule_cols):
    """After a blank spacer row: a bold caption merged across
    [first_col, last_col], then a Signature/Date row with
    bottom-bordered blank rule cells. Row layout:
      data_last_row + 1  -> blank spacer (nothing written)
      data_last_row + 2  -> caption
      data_last_row + 3  -> Signature/Date line
    """
    cap_row = data_last_row + 2
    sig_row = data_last_row + 3
    cap = ws.cell(row=cap_row, column=first_col, value=caption)
    cap.font = _BOLD
    ws.merge_cells(
        start_row=cap_row, start_column=first_col,
        end_row=cap_row, end_column=last_col,
    )
    ws.cell(row=sig_row, column=sig_label_col, value="Signature:")
    for col in sig_rule_cols:
        ws.cell(row=sig_row, column=col).border = _RULE
    ws.cell(row=sig_row, column=date_label_col, value="Date:")
    for col in date_rule_cols:
        ws.cell(row=sig_row, column=col).border = _RULE


def _autosize_columns(ws, table_header_row, last_row):
    """Width per data column = longest value/label in it (rows from
    the table-header row down through `last_row`; merged header lines
    and the footer are excluded by the caller's bound). Left
    (Attendance) columns get the `_LEFT_MIN_WIDTH` floor so that
    table fills the page; the spacer column is fixed."""
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
        floor = _LEFT_MIN_WIDTH if col < SPACER_COL else _WIDTH_MIN
        width = longest * _WIDTH_FACTOR + _WIDTH_PAD
        width = min(_WIDTH_MAX, max(floor, width))
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.column_dimensions[
        get_column_letter(SPACER_COL)
    ].width = SPACER_WIDTH


def _ensure_line_min(ws, rule_cols, line_min):
    """Raise the given rule columns' widths (distributed evenly,
    only increasing) until their combined width is at least
    `line_min`. Columns already summing to >= line_min are
    untouched."""
    total = sum(
        ws.column_dimensions[get_column_letter(c)].width
        for c in rule_cols
    )
    if total >= line_min:
        return
    add = (line_min - total) / len(rule_cols)
    for c in rule_cols:
        letter = get_column_letter(c)
        ws.column_dimensions[letter].width += add


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
    last_data_row = max(end_left, end_right) - 1

    _write_footer(
        ws, last_data_row, LEFT_FIRST_COL, left_last_col,
        LEFT_CAPTION,
        sig_label_col=1, sig_rule_cols=(2,),
        date_label_col=3, date_rule_cols=(4,),
    )
    _write_footer(
        ws, last_data_row, RIGHT_FIRST_COL, right_last_col,
        RIGHT_CAPTION,
        sig_label_col=6, sig_rule_cols=(7, 8),
        date_label_col=9, date_rule_cols=(10, 11),
    )
    footer_last_row = last_data_row + 3

    # column page break after spacer col E -> Table 1 | Table 2 pages
    ws.col_breaks.append(Break(id=SPACER_COL))

    ws.print_area = (
        f"A1:{get_column_letter(right_last_col)}{footer_last_row}"
    )
    ws.print_options.horizontalCentered = True
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 0
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    _autosize_columns(ws, table_header_row, last_data_row)
    _ensure_line_min(ws, (2,), _SIG_LINE_MIN)      # left signature (B)
    _ensure_line_min(ws, (4,), _DATE_LINE_MIN)     # left date (D)
    _ensure_line_min(ws, (7, 8), _SIG_LINE_MIN)    # right signature
    _ensure_line_min(ws, (10, 11), _DATE_LINE_MIN)  # right date (J,K)

    wb.save(output_path)
    return output_path
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_workbook.py -q`
Expected: PASS. (`B` = 16 from the left floor, then raised to 22 by `_ensure_line_min((2,), 22)`; `D` = 16 ≥ 14; right `G+H` ≈ 21.25 → bumped to 22; `J+K` ≈ 35 already ≥ 14; `G` ≈ 5.8 < 16 confirming the floor is left-only.) No openpyxl round-trip risk here — only `column_dimensions[...].width` floats, which round-trip exactly.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: ALL pass. `build_workbook`'s signature is unchanged, so `new_monthly_schedule.process_member` and `test_cli.py` are unaffected. Report the exact count and confirm the only workbook test is `test_side_by_side_workbook_structure`.

- [ ] **Step 6: Commit**

```bash
git add monthly_schedule/workbook.py tests/test_workbook.py
git commit -m "feat: Attendance column min width + guaranteed signature/date line length"
```

---

## Task 2: Manual end-to-end verification (deferred — document only)

**Files:** none (no code, no commit).

- [ ] **Step 1: Full suite once more**

Run: `python -m pytest -q`
Expected: ALL pass.

- [ ] **Step 2: Document the manual visual check**

A true visual confirmation needs a real workbook opened in Excel (a key in `google_maps.config` and an unlocked DB). Record, for the user to run later:

```
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5 --output-path .\out
```

Then open `.\out\Schedule_24010_2026-05.xlsx` and confirm:
- The **Attendance (left) table** now fills the page width far
  better (each column noticeably wider; less white space).
- The Signature and Date write-on lines under **both** tables are
  long enough to actually sign/date on.

Not run in CI; the mocked structural test in Task 1 is the
automated gate. No commit (nothing changed).

---

## Self-Review

**1. Spec coverage:**

- §1 scope / only `workbook.py` + its test, signature unchanged → Task 1 (full suite Step 5 confirms CLI unaffected).
- §2 base behavior preserved → header/table/footer/`build_workbook` ordering before autosize unchanged verbatim.
- §3 constants `_LEFT_MIN_WIDTH=16`, `_SIG_LINE_MIN=22`, `_DATE_LINE_MIN=14` → added by the constants block.
- §4 Attendance column floor: `floor = _LEFT_MIN_WIDTH if col < SPACER_COL else _WIDTH_MIN`, `width = min(_WIDTH_MAX, max(floor, longest*_WIDTH_FACTOR + _WIDTH_PAD))` → `_autosize_columns`; asserted by `A..D >= 16` and `G < 16` (right unaffected).
- §5 `_ensure_line_min(ws, rule_cols, line_min)`: sum widths, if `< line_min` add `(line_min-total)/n` to each (only increasing, not re-capped) → new helper; four calls `(2,)`/`(4,)`/`(7,8)`/`(10,11)` after autosize → `build_workbook`; asserted by `B>=22`, `D>=14`, `G+H>=22`, `J+K>=14`.
- §6 order: autosize then the four `_ensure_line_min` then save → matches `build_workbook` tail.
- §7 error handling: empty `rows` ⇒ left cols still floored from header content, lines still enforced; unwritable path still raises — no new paths.
- §8 testing: existing assertions kept; the now-invalid `assert H.width > B.width` REMOVED (and its "wide label > Day" comment); new minimum assertions added with `- 1e-6` float tolerance; `E == 3` kept; manual e2e deferred (Task 2).
- §9 out of scope: no stretch-to-page scaling, no general right-column widening, no CLI/config knobs, no data/geometry change — none implemented.

No gaps.

**2. Placeholder scan:** No "TBD/handle errors/similar to". Both files are complete replacements; every run step has an exact command + expected outcome; no unbounded uncertainty (the float widths round-trip exactly, unlike the earlier print-area/`$` case which is left untouched here via the existing `replace("$","")` line).

**3. Type/name consistency:** `_LEFT_MIN_WIDTH`/`_SIG_LINE_MIN`/`_DATE_LINE_MIN`, `_autosize_columns(ws, table_header_row, last_row)` (floor via `col < SPACER_COL`, `SPACER_COL=5`, left cols 1–4), `_ensure_line_min(ws, rule_cols, line_min)`, the four call sites `(2,)`/`(4,)`/`(7,8)`/`(10,11)` matching the `_write_footer` rule layout (left B/D, right G,H/J,K) and the test's `B/D/G+H/J+K` assertions. `build_workbook`/`COMPANY_NAME` import surface unchanged for `tests/test_workbook.py` and `new_monthly_schedule.py`. All other helpers/constants byte-identical to the merged version.

No issues found.
