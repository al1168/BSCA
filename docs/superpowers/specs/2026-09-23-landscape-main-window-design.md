# Landscape Main Window — Design

**Date:** 2026-09-23
**Status:** Approved

## Problem

The main window stacks every control in one column, 560px wide. At
open it is already 770px tall, and after a run the progress bar, log
pane and Open Folder / Print buttons appear underneath and push it to
roughly 1000px. On a 1366x768 laptop the bottom of the window is off
screen as soon as a run finishes: the user cannot see the summary or
the Print button without dragging the window around.

The sibling Cathay Monthly Timesheet Generator solved the same problem
with a two-column landscape window (its spec section 6): controls on
the left, progress / log / summary on the right, sized so everything
is visible at once on a 1366x768 display. This spec brings the BSCA
window to the same shape.

## Decision summary (user-confirmed)

- Two-column landscape layout, modelled on Cathay's main window.
- Left column is about 560px, not Cathay's 400px: the four Who radios
  in one row and the three-column plan table need the room.
- Right column holds the progress bar, a Log pane and a separate
  Summary pane, all always visible. The run summary moves from the end
  of the log into the Summary pane.
- Open Folder and Print are always visible in the left column. Print
  is disabled until a run has produced schedule files. Open Folder
  falls back to the Settings output folder when nothing has run yet.
- Window opens at 1280x720 with a minimum of 1100x680. The left column
  must fit within the window height with no scrolling; a test enforces
  it.

## Layout

```
+------------------------------------------------------------------+
| Title                       [English v] [gear] | [progress bar]   |
| +-- Who -------------------------------------+ | Log              |
| | (o) Single ( ) Multiple ( ) Plan ( ) All  | | +--------------+ |
| | Member ID: [_______]                       | | |              | |
| | +-------------------------------------+    | | |              | |
| | | Plan | Active | Inactive |  (9 rows)|    | | |              | |
| | +-------------------------------------+    | | +--------------+ |
| | roster caption            excluded caption | | Summary          |
| +--------------------------------------------+ | +--------------+ |
| +-- When -----------------------------------+  | |              | |
| | Month [Sept v]  Year [2026]               |  | |              | |
| | [ ] Custom range  From [1] To [30]        |  | |              | |
| +-------------------------------------------+  | |              | |
|  Save To  C:\Users\...\output       [Change…]  | |              | |
| +-- Actions --------------------------------+  | |              | |
| | [ ] Debug (per-day reason CSV)            |  | |              | |
| | [ ] All Members: per-MLTC folders         |  | |              | |
| | [        Generate Schedule        ]       |  | |              | |
| |        scope caption (gray)               |  | |              | |
| | [Open Output Folder] [Print All Schedules]|  | |              | |
| +-------------------------------------------+  | +--------------+ |
+------------------------------------------------------------------+
```

### Left column (`QWidget`, fixed width 560, min 520)

Same widgets and behaviour as today, in this order:

1. Top bar: title label, language combo, gear button.
2. **Who** group: radio row, stacked input panel, plan table, roster
   and excluded captions. Unchanged apart from spacing.
3. **When** group: month, year, custom day-range row. Unchanged.
4. **Save To** row: bold label, output path elided in the middle on
   one line (full path as tooltip), Change button. No group box.
5. **Actions** group (new `QGroupBox`, title key `actions.title`):
   debug checkbox, per-MLTC-folders checkbox, Generate button, scope
   caption, then Open Output Folder and Print All Schedules side by
   side in one row.
6. A stretch so the column hugs the top.

### Right column (`QVBoxLayout`, stretch 1)

1. Progress bar. Always visible; range (0, 1) value 0 when idle, so it
   shows empty rather than an indeterminate sweep.
2. Log label (key `log.title`) and the read-only log `QPlainTextEdit`
   (Consolas 9, `setMaximumBlockCount(5000)`), stretch 2.
3. Summary label (key `summary.title`) and a read-only summary
   `QPlainTextEdit`, stretch 3. Word wrap on; plain proportional font.

### Fitting the height

The left column measured 710px with the app's real font (Segoe UI
9pt) before tightening. The target is a left column
`sizeHint().height()` of at most 680px so the 720px default window and
a 1366x768 laptop (about 690px available) both show it in full.
Levers applied, in order (implemented 2026-09-23, result 678px):

1. Column spacing 4px and group-box layout spacing 4px with tight
   content margins, instead of the previous 12px.
2. Plan table row height 22px via
   `verticalHeader().setDefaultSectionSize(22)`; the fixed table
   height formula already derives from that value.
3. Open Folder and Print on one row instead of two.
4. Generate button 34px tall instead of 40px.
5. Save To is a plain row rather than a group box, saving the frame
   and title.
6. The Save To path is one line elided in the middle at 360px, with
   the full path as a tooltip. A long path that wrapped pushed the
   column to 686px.

Measured on the offscreen platform with no fonts, the same column
reads 656px, so the geometry test points Qt at the Windows fonts
folder and sets Segoe UI 9pt to see the real metrics.

## Behaviour changes

- `_run()` no longer toggles visibility of the log, progress bar or
  buttons. It clears both panes, resets the progress bar, and disables
  Generate and Print while running.
- `_on_finished()` writes the summary text (or `error_text`) to the
  Summary pane instead of appending it to the log. The failure warning
  dialog is unchanged. Print is enabled only when `generated_paths` is
  non-empty; Open Folder is always enabled.
- `_open_output_folder()` opens `_last_out_dir` when set, else the
  Settings `output_path`. If neither is a directory it does nothing,
  as today.
- `_print_schedules()` still uses the log pane for per-file progress
  lines. It no longer needs to make the log or progress bar visible.
- Print progress shares the same progress bar; `_on_print_finished`
  resets it to (0, 1) / 0.

## i18n

New keys in both languages in `gui/i18n.py`:

| Key | English | Chinese |
|---|---|---|
| `actions.title` | Actions | 操作 |
| `log.title` | Progress log | 进度日志 |
| `summary.title` | Summary | 摘要 |

The `opts.mltc_folders` text is shortened in both languages so it
fits the 560px column without clipping (checkboxes do not wrap):
English "All Members: one folder per MLTC plan", Chinese
"所有成员：每个 MLTC 计划一个文件夹". No other text changes. Existing
`opts.*` keys keep their names even though the widgets now sit in
the Actions group.

## Tests

New `tests/test_main_window.py`, gated with
`pytest.importorskip("PyQt6")` and run under `QT_QPA_PLATFORM=offscreen`
(set in the test via `os.environ.setdefault` before the import),
following Cathay's `tests/test_main_window.py`:

- `test_window_is_landscape_and_fully_visible`: minimum size at least
  1100x680, opens at 1280x720 or larger, width > height, left column
  `maximumWidth() <= 600`, left column `sizeHint().height() <= 680`.
- `test_summary_pane_shows_result`: `_on_finished(True, payload)` with
  a minimal payload puts the summary text in the summary pane, not the
  log; `_on_finished(False, {"error_text": "bad"})` puts "bad" in the
  summary pane (warning dialog monkeypatched away).
- `test_print_button_enabled_only_after_generation`: disabled after
  construction; enabled after `_on_finished` with a non-empty
  `generated_paths`; disabled again after one with an empty list.
- `test_long_output_path_stays_on_one_line`: a very long path is
  elided (contains an ellipsis), kept whole in the tooltip, and the
  label is no taller than the Change button.
- `test_open_folder_falls_back_to_settings_path`: with `_last_out_dir`
  None and a settings `output_path` pointing at `tmp_path`, the folder
  opener is called with that path (`os.startfile` monkeypatched).

Tests monkeypatch `app_settings` so no real settings file or database
is touched; the counts worker runs against a missing DB path and
simply reports unavailable, as it already does today.

## Out of scope

- Any change to the Settings dialog, the worker, or the generated
  output.
- Restyling beyond layout (colours, fonts, icons).
- The Cathay app itself.

## Follow-up

Rebuild `dist/MonthlyScheduleGenerator.exe` after the change so the
packaged app picks up the new window.

## Scaling on large windows (added 2026-09-25)

**Problem.** Maximized on a 1920x1080 monitor, the left column stayed
520px wide and its controls ended about 360px above the bottom of the
window. The log and summary panes took all the extra room, so the
left column shrank to 27% of the width.

**Rule.** Every pixel and font size in the window is a design value
for the 1280x720 default. `_fit_ui_scale()` runs on every resize and
picks the UI scale in 0.1 steps between 1.0 and 2.0:

1. The ceiling is the width ratio, `max_ui_scale(width)`, which is
   window width / 1280 rounded down to a step.
2. Step down from there until the left column's `sizeHint()` height
   fits the window height. The height is measured, not taken from the
   height ratio, because padding, spacing and check-box indicators do
   not grow with the text. A height ratio picked 1.4 at 1080p and left
   159px empty. Measuring picks 1.5 and leaves about 75px, close to
   the 43px at the default size.
3. Each scale's height is measured once and cached, so dragging the
   window edge re-lays out only when the chosen scale changes. A
   language change clears the cache and re-fits, because Chinese text
   uses a taller font.

**What scales.** The window font (Segoe UI 9pt × scale, inherited by
every widget without a font of its own), the title, Generate and log
fonts, the gray caption pixel sizes, every fixed width and height
registered through `_fix_size()`, the left column's min/max width, the
plan table's row height, number column widths and fixed height, and
the Save To elide width. Layout margins, spacing and check-box
indicators stay at design size. Dialogs are not scaled.

**Results** (offscreen, Segoe UI):

| Window | Scale | Left column | Share of width |
|---|---|---|---|
| 1280x720 | 1.0 | 520px | 41% |
| 1366x768 maximized | 1.0 | 520px | 39% |
| 1920x1080 maximized | 1.5 | 780px | 41% |

**Tests** in `tests/test_main_window.py`: the width ceiling steps, the
1080p window (scale 1.5, fonts and fixed sizes scaled, every plan row
visible, left column at least 39% of the width and its controls
filling 90% of the height without overflowing), a wide but short
window staying within the height, shrinking back to 1.0, Chinese text
still fitting, and the Save To path eliding to the scaled width.
