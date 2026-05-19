# Attendance Column Widths + Signature/Date Line Minimum — Design

**Date:** 2026-05-18
**Status:** Approved (design); pending implementation plan
**Builds on:** `docs/superpowers/specs/2026-05-18-workbook-footer-centering-design.md`

## 1. Purpose & Scope

Two output tweaks:

1. The **Attendance (left/Table 1) table** is too narrow — give its
   columns a generous minimum width so the table fills the page.
   (Transportation/right table's general sizing is unchanged.)
2. The **Signature and Date write-on lines** are too short — give
   each line a guaranteed minimum length, in **both** footers.

Only `monthly_schedule/workbook.py` changes (`_autosize_columns` +
a new `_ensure_line_min` step in `build_workbook`), plus its test
`tests/test_workbook.py`. `build_workbook(member, rows,
output_path)` keeps its signature; no other module changes.

## 2. Current Behavior (base)

`_autosize_columns(ws, table_header_row, last_row)` sets every data
column (left A–D = cols 1–4, right F–K = cols 6–11) to
`min(_WIDTH_MAX=40, max(_WIDTH_MIN=4, longest*1.15 + 2))` over the
data region, and the spacer column E to `SPACER_WIDTH=3`. The left
footer's signature rule is column **B**, its date rule column **D**;
the right footer's signature rule is columns **G,H**, date rule
**J,K**. With only 4 short left columns the Attendance table looks
small and its single-column rule lines are very short.

## 3. New Constants

```python
_LEFT_MIN_WIDTH = 16   # min width for each Attendance (left) column
_SIG_LINE_MIN   = 22   # min total width of a Signature rule line
_DATE_LINE_MIN  = 14   # min total width of a Date rule line
```

(Tweakable numbers; chosen so the left table roughly doubles in
width and the lines are comfortably writable.)

## 4. Attendance Column Minimum (`_autosize_columns`)

For **left-block columns only** (column index `< SPACER_COL`, i.e.
1–4) the floor becomes `_LEFT_MIN_WIDTH` instead of `_WIDTH_MIN`:

```
width = min(_WIDTH_MAX, max(floor, longest*_WIDTH_FACTOR + _WIDTH_PAD))
where floor = _LEFT_MIN_WIDTH if col < SPACER_COL else _WIDTH_MIN
```

Right-block columns (≥ `RIGHT_FIRST_COL`) keep `floor = _WIDTH_MIN`
(unchanged). Spacer column E stays `SPACER_WIDTH`. Resulting left
columns: Date/Day/Time-In/Time-Out each ≥ 16 (≈ 41 → ≈ 64 total).

## 5. Signature/Date Line Minimum (`_ensure_line_min`)

New pure helper, run **after** `_autosize_columns` so it can only
**increase** widths:

```python
def _ensure_line_min(ws, rule_cols, line_min):
    total = sum(ws.column_dimensions[get_column_letter(c)].width
                for c in rule_cols)
    if total >= line_min:
        return
    add = (line_min - total) / len(rule_cols)
    for c in rule_cols:
        letter = get_column_letter(c)
        ws.column_dimensions[letter].width += add
```

It distributes the deficit evenly across the rule columns so their
combined width becomes exactly `line_min`; columns already summing
to ≥ `line_min` are left untouched. It never shrinks a column and is
**not** re-capped at `_WIDTH_MAX` (a guaranteed writable line takes
precedence; with these numbers no rule column exceeds ~22, well under
40).

`build_workbook` calls it four times, after `_autosize_columns`,
matching the footer rule layout:

| Block | Line | `rule_cols` | min |
|-------|------|-------------|-----|
| Left  | Signature | `(2,)` (B)        | `_SIG_LINE_MIN` |
| Left  | Date      | `(4,)` (D)        | `_DATE_LINE_MIN` |
| Right | Signature | `(7, 8)` (G,H)    | `_SIG_LINE_MIN` |
| Right | Date      | `(10, 11)` (J,K)  | `_DATE_LINE_MIN` |

The left signature rule is column B (also the `Day` data column),
so B widens to ≥ 22 — intended "fill the page" behavior. The right
rule columns are already wide; this mostly affects the Attendance
footer (G+H ≈ 21.3 → 22; J+K ≈ 31.7 → unchanged), exactly where the
lines were too short.

## 6. Order in `build_workbook`

…write tables → write footers → column page break → `print_area`
→ `print_options.horizontalCentered` → page setup →
`_autosize_columns(ws, table_header_row, last_data_row)` (now with
the left-block floor) → the four `_ensure_line_min(...)` calls →
`wb.save(output_path)`. Everything before autosize is unchanged.

## 7. Error Handling

No new paths. Empty `rows` ⇒ left columns still floored to 16 from
the header row's content, footer/lines still enforced; valid
workbook. Unwritable path still raises naturally (caller's `write`
stage).

## 8. Testing (`tests/test_workbook.py`)

Keep all existing side-by-side / footer / centering assertions,
**except** the now-invalid line
`assert ws.column_dimensions["H"].width > ws.column_dimensions["B"].width`
— it must be **removed/replaced**, because column B (left signature
rule) is now intentionally ≥ 22 and will exceed column H (~16), so
that old "wide label col > Day col" check no longer holds. Add:

- Every left data column ≥ `_LEFT_MIN_WIDTH`:
  `ws.column_dimensions[c].width >= 16` for `c` in `"A","B","C","D"`.
- Left signature line: `ws.column_dimensions["B"].width >= 22`.
- Left date line: `ws.column_dimensions["D"].width >= 14`.
- Right signature line:
  `ws.column_dimensions["G"].width + ws.column_dimensions["H"].width
  >= 22 - 1e-6`.
- Right date line:
  `ws.column_dimensions["J"].width + ws.column_dimensions["K"].width
  >= 14 - 1e-6`.
- Right block NOT given the left floor:
  `ws.column_dimensions["G"].width < 16` (its short `Day` content
  plus the small even line-min bump stays well under 16, proving the
  16 floor is left-block-only).
- `ws.column_dimensions["E"].width == 3` (spacer unchanged — already
  asserted).

Float widths: use the `- 1e-6` tolerance on the summed-line
assertions (the even split can land a hair under due to float
arithmetic).

Manual e2e deferred (needs a real key + unlocked DB): regenerate and
visually confirm the Attendance table fills the page and the
Signature/Date lines are long enough to write on.

## 9. Out of Scope (YAGNI)

- Stretch-to-exact-page-width scaling (rejected in favor of the
  predictable per-column minimum).
- Widening the Transportation/right table's general columns (only
  its rule lines are guaranteed a minimum, same as the left).
- Configurable widths via CLI/args (constants are edited in source).
- Any change to data, eligibility, geometry, the column break, the
  caption, or the CLI.
