# Landscape Main Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the single-column BSCA main window into a two-column landscape window (controls left, progress / log / summary right) so everything stays on screen after a run, matching the Cathay generator.

**Architecture:** `gui/main_window.py` keeps every widget and slot it has today; only `__init__` is restructured into a left `QWidget` panel and a right `QVBoxLayout`, plus a handful of slot edits so nothing is hidden/shown after a run and the summary lands in its own pane. Three i18n keys are added. A new offscreen PyQt test file pins the geometry and the new behaviour.

**Tech Stack:** Python 3.11, PyQt6, pytest (offscreen platform).

Spec: `docs/superpowers/specs/2026-09-23-landscape-main-window-design.md`

---

## File map

- Modify `gui/i18n.py` — add `actions.title`, `log.title`, `summary.title` to both language dicts; shorten `opts.mltc_folders` (English) so it fits a 560px column.
- Modify `gui/main_window.py` — `__init__` layout (lines ~114–413), `_retranslate`, `_open_output_folder`, `_print_schedules`, `_on_print_finished`, `_run`, `_on_finished`.
- Create `tests/test_main_window.py` — offscreen geometry and behaviour tests.
- Modify `docs/superpowers/specs/2026-09-23-landscape-main-window-design.md` — only if a fallback lever was needed to fit the height (record which).

---

### Task 1: i18n keys

**Files:**
- Modify: `gui/i18n.py` (English block near line 47–57, Chinese block near line 394–401)
- Test: `tests/test_i18n.py` (existing `test_key_parity` guards both dicts)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_i18n.py`:

```python
def test_landscape_window_keys_exist():
    from gui import i18n
    i18n.set_language("en")
    assert i18n.tr("actions.title") == "Actions"
    assert i18n.tr("log.title") == "Progress log"
    assert i18n.tr("summary.title") == "Summary"
    i18n.set_language("zh")
    assert i18n.tr("actions.title") == "操作"
    assert i18n.tr("log.title") == "进度日志"
    assert i18n.tr("summary.title") == "摘要"
```

- [ ] **Step 2: Run it to see it fail**

Run: `python -m pytest tests/test_i18n.py -q`
Expected: `test_landscape_window_keys_exist` FAILS (`tr` returns the key itself).

- [ ] **Step 3: Add the keys**

In the English dict, after `"save.change": "Change…",` insert:

```python
        # actions group / right column (spec 2026-09-23)
        "actions.title": "Actions",
        "log.title": "Progress log",
        "summary.title": "Summary",
```

and replace the `opts.mltc_folders` tuple with a single line that fits the
560px left column:

```python
        "opts.mltc_folders": "All Members: one folder per MLTC plan",
```

In the Chinese dict, after `"save.change": "更改…",` insert:

```python
        "actions.title": "操作",
        "log.title": "进度日志",
        "summary.title": "摘要",
```

and shorten the Chinese `opts.mltc_folders` to match:

```python
        "opts.mltc_folders": "所有成员：每个 MLTC 计划一个文件夹",
```

- [ ] **Step 4: Run the i18n tests**

Run: `python -m pytest tests/test_i18n.py -q`
Expected: all PASS (parity included).

- [ ] **Step 5: Commit**

```bash
git add gui/i18n.py tests/test_i18n.py
git commit -m "feat(gui): i18n keys for the landscape main window"
```

---

### Task 2: Geometry test and two-column layout

**Files:**
- Create: `tests/test_main_window.py`
- Modify: `gui/main_window.py` `__init__` and `_retranslate`

- [ ] **Step 1: Write the failing geometry test**

Create `tests/test_main_window.py`:

```python
"""Offscreen tests for the landscape main window (spec 2026-09-23)."""

import json
import os

import pytest

pytest.importorskip("PyQt6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from gui import app_settings  # noqa: E402

# Held in a module global: an unreferenced QApplication is garbage
# collected and the next widget built on it crashes the process.
_APP = None


@pytest.fixture(scope="module")
def app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    """A MainWindow backed by a throwaway settings file whose DB path
    does not exist, so the counts fetch fails fast and quietly."""
    settings_file = tmp_path / "bsca_settings.json"
    settings = dict(app_settings.DEFAULTS)
    settings["db_path"] = str(tmp_path / "missing.accdb")
    settings["output_path"] = str(tmp_path)
    settings_file.write_text(json.dumps(settings))
    monkeypatch.setattr(app_settings, "_SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr("gui.i18n._current_lang", "en")
    from gui.main_window import MainWindow
    w = MainWindow()
    yield w
    # Never let a running QThread reach interpreter teardown.
    for worker in list(w._counts_workers):
        worker.wait()
    w.deleteLater()
    app.processEvents()


def test_window_is_landscape_and_fully_visible(window):
    w = window
    assert w.minimumWidth() >= 1100 and w.minimumHeight() >= 680
    assert w.width() >= 1280 and w.height() >= 720
    assert w.width() > w.height()
    assert w._left_panel.maximumWidth() <= 600
    # Every left-column control fits inside the default window height.
    assert w._left_panel.sizeHint().height() <= 680
```

- [ ] **Step 2: Run it to see it fail**

Run: `python -m pytest tests/test_main_window.py -q`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute '_left_panel'`.

- [ ] **Step 3: Restructure `__init__`**

At module level in `gui/main_window.py`, after the imports, add:

```python
# Landscape layout (spec 2026-09-23): controls in a fixed-width left
# column, progress/log/summary on the right, everything on screen at
# once on a 1366x768 display.
WINDOW_SIZE = (1280, 720)
MIN_SIZE = (1100, 680)
LEFT_WIDTH = 560
PLAN_ROW_HEIGHT = 24
```

In `__init__`, replace `self.setMinimumWidth(560)` and the root layout
setup with:

```python
        root = QHBoxLayout(self)
        root.setSpacing(12)
        self._left_panel = QWidget()
        self._left_panel.setMinimumWidth(LEFT_WIDTH - 40)
        self._left_panel.setMaximumWidth(LEFT_WIDTH)
        left = QVBoxLayout(self._left_panel)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        right = QVBoxLayout()
        right.setSpacing(6)
        root.addWidget(self._left_panel, 0)
        root.addLayout(right, 1)
```

Then change every `root.addLayout(top)` / `root.addWidget(...)` for the
top bar, Who, When and Save To groups to `left.addLayout` /
`left.addWidget`. Tighten each group's layout right after it is created:

```python
        who_layout = QVBoxLayout(self._who_box)
        who_layout.setSpacing(4)
        who_layout.setContentsMargins(8, 4, 8, 6)
```

```python
        when_outer = QVBoxLayout(self._when_box)
        when_outer.setSpacing(4)
        when_outer.setContentsMargins(8, 4, 8, 6)
```

```python
        save_layout = QHBoxLayout(self._save_box)
        save_layout.setContentsMargins(8, 4, 8, 6)
```

Set the plan-table row height before the fixed-height calculation
(right after `self._plan_table = QTableWidget(...)`):

```python
        self._plan_table.verticalHeader().setDefaultSectionSize(PLAN_ROW_HEIGHT)
```

Replace the Options / Generate / Progress+Log / buttons section (from
`# ── Options` to just before `self._update_plan_table()`) with:

```python
        # ── Actions ────────────────────────────────────────────────
        self._actions_box = QGroupBox()
        actions = QVBoxLayout(self._actions_box)
        actions.setSpacing(4)
        actions.setContentsMargins(8, 4, 8, 6)
        self._debug_check = QCheckBox()
        actions.addWidget(self._debug_check)
        # All-Members only: split output into per-MLTC folders. Default
        # off -> everyone in one <Month>_<Year>_Timesheets folder.
        self._mltc_folders_check = QCheckBox()
        actions.addWidget(self._mltc_folders_check)

        self._generate_btn = QPushButton()
        self._generate_btn.setFixedHeight(40)
        gen_font = QFont()
        gen_font.setPointSize(11)
        gen_font.setBold(True)
        self._generate_btn.setFont(gen_font)
        self._generate_btn.clicked.connect(self._run)
        actions.addWidget(self._generate_btn)

        self._scope_label = QLabel()
        self._scope_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scope_label.setStyleSheet("color: gray; font-size: 11px;")
        actions.addWidget(self._scope_label)

        btn_row = QHBoxLayout()
        self._open_folder_btn = QPushButton()
        self._open_folder_btn.clicked.connect(self._open_output_folder)
        btn_row.addWidget(self._open_folder_btn)
        # Prints every schedule from the last run (never debug CSVs);
        # enabled only once a run has produced files.
        self._print_btn = QPushButton()
        self._print_btn.setEnabled(False)
        self._print_btn.clicked.connect(self._print_schedules)
        btn_row.addWidget(self._print_btn)
        actions.addLayout(btn_row)
        left.addWidget(self._actions_box)
        left.addStretch(1)

        # ── Right column: progress, log, summary ───────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        right.addWidget(self._progress)

        self._log_label = QLabel()
        right.addWidget(self._log_label)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        # A long run logs a line per member; cap the scrollback.
        self._log.setMaximumBlockCount(5000)
        right.addWidget(self._log, 2)

        self._summary_label = QLabel()
        right.addWidget(self._summary_label)
        self._summary = QPlainTextEdit()
        self._summary.setReadOnly(True)
        right.addWidget(self._summary, 3)

        self.setMinimumSize(*MIN_SIZE)
        self.resize(*WINDOW_SIZE)
```

Keep the existing `self._update_plan_table()` + fixed-height block, the
`LanguageManager` hookup and `self._start_counts_refresh()` after it.

In `_retranslate`, add:

```python
        self._actions_box.setTitle(tr("actions.title"))
        self._log_label.setText(tr("log.title"))
        self._summary_label.setText(tr("summary.title"))
```

- [ ] **Step 4: Run the geometry test and measure**

Run: `python -m pytest tests/test_main_window.py -q`

If the `sizeHint().height() <= 680` assertion fails, print the number
(`python -c` script constructing the window offscreen) and apply the
spec's levers in order: (1) spacing/margins as above, (2) row height 24,
(3) buttons on one row — all already applied — then (4) turn Save To
into a plain row (label + Change button in an `QHBoxLayout`, no
`QGroupBox`), and only then (5) drop Save To from the main window.
Record whichever of (4)/(5) was needed in the spec's "Fitting the
height" section.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gui/main_window.py tests/test_main_window.py
git commit -m "feat(gui): two-column landscape main window"
```

---

### Task 3: Summary pane, always-visible buttons, folder fallback

**Files:**
- Modify: `gui/main_window.py` `_run`, `_on_finished`, `_open_output_folder`, `_print_schedules`, `_on_print_finished`
- Test: `tests/test_main_window.py`

- [ ] **Step 1: Write the failing behaviour tests**

Append to `tests/test_main_window.py`:

```python
def _quiet_warning(monkeypatch):
    monkeypatch.setattr("gui.main_window.QMessageBox.warning",
                        lambda *a, **k: None)


def _ok_payload(paths):
    return {
        "scope": {"year": 2026, "month": 9, "mode": "single"},
        "verb_key": "summary.verb.generated",
        "success": len(paths),
        "total": len(paths),
        "out_dir": None,
        "failures": [],
        "generated_paths": paths,
    }


def test_summary_pane_shows_result(window, monkeypatch):
    _quiet_warning(monkeypatch)
    w = window
    w._on_finished(True, _ok_payload(["a.xlsx"]))
    assert w._summary.toPlainText().strip() != ""
    assert w._log.toPlainText() == ""
    assert w._generate_btn.isEnabled()
    w._on_finished(False, {"error_text": "bad"})
    assert w._summary.toPlainText() == "bad"


def test_print_button_enabled_only_after_generation(window, monkeypatch):
    _quiet_warning(monkeypatch)
    w = window
    assert w._open_folder_btn.isVisible() or not w.isVisible()
    assert not w._print_btn.isEnabled()
    w._on_finished(True, _ok_payload(["a.xlsx"]))
    assert w._print_btn.isEnabled()
    w._on_finished(True, _ok_payload([]))
    assert not w._print_btn.isEnabled()


def test_open_folder_falls_back_to_settings_path(window, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr("gui.main_window.sys.platform", "win32")
    monkeypatch.setattr("gui.main_window.os.startfile",
                        lambda p: opened.append(p), raising=False)
    w = window
    w._last_out_dir = None
    w._open_output_folder()
    assert opened == [str(tmp_path)]
```

Check the `verb_key` value: `grep -n "verb_key" gui/worker.py` and use
the key the worker actually emits (it is an i18n key such as
`summary.verb.generated`); `tr` on a missing key just returns the key,
so the test still passes either way.

- [ ] **Step 2: Run to see them fail**

Run: `python -m pytest tests/test_main_window.py -q`
Expected: `test_summary_pane_shows_result` fails (summary text lands in
the log, `_summary` empty); `test_print_button_enabled_only_after_generation`
fails (button stays disabled); `test_open_folder_falls_back_to_settings_path`
fails (`opened == []`).

- [ ] **Step 3: Update the slots**

`_open_output_folder`:

```python
    def _open_output_folder(self):
        target = self._last_out_dir or self._settings.get("output_path", "")
        if target and os.path.isdir(target):
            if sys.platform == "win32":
                os.startfile(target)
            else:
                subprocess.Popen(["xdg-open", target])
```

`_print_schedules` — delete the four visibility lines
(`self._progress.setVisible(True)`, `self._log.setVisible(True)`), keep
the range/value reset and the log lines.

`_on_print_finished` — first lines become:

```python
        self._print_btn.setEnabled(True)
        self._generate_btn.setEnabled(True)
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
```

`_run` — replace the block that clears/shows widgets with:

```python
        self._log.clear()
        self._summary.clear()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._generate_btn.setEnabled(False)
        self._print_btn.setEnabled(False)
        self._last_out_dir = out_dir
```

`_on_finished`:

```python
    def _on_finished(self, success: bool, payload: dict):
        if "error_text" in payload:
            summary = payload["error_text"]
        else:
            summary = self._build_summary(payload)
        self._summary.setPlainText(summary)
        self._generate_btn.setEnabled(True)
        self._last_generated = payload.get("generated_paths", []) or []
        self._printed_ok.clear()   # fresh files — nothing printed yet
        # Print only makes sense once at least one schedule was written,
        # even on a partial run where some members were skipped.
        self._print_btn.setEnabled(bool(self._last_generated))
        if not success:
            QMessageBox.warning(
                self, tr("msg.completed_errors.title"), summary
            )
```

- [ ] **Step 4: Run the whole GUI test file, then the full suite**

Run: `python -m pytest tests/test_main_window.py -q`
Expected: 4 PASS.

Run: `python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add gui/main_window.py tests/test_main_window.py
git commit -m "feat(gui): summary pane, persistent folder/print buttons"
```

---

### Task 4: Visual check and packaged exe

**Files:**
- Modify (if needed): `docs/superpowers/specs/2026-09-23-landscape-main-window-design.md`
- Build output: `dist/MonthlyScheduleGenerator.exe`

- [ ] **Step 1: Render an offscreen screenshot in both languages**

```bash
QT_QPA_PLATFORM=offscreen python - <<'EOF'
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
app = QApplication(sys.argv); app.setStyle("Fusion")
from gui.main_window import MainWindow
from gui.i18n import LanguageManager
w = MainWindow(); w.show()
def snap():
    w.grab().save("landscape_en.png")
    LanguageManager.instance().set_language("zh")
    w.grab().save("landscape_zh.png")
    print("left height", w._left_panel.sizeHint().height()); app.quit()
QTimer.singleShot(1500, snap); app.exec()
EOF
```

Open both PNGs and confirm: two columns, nothing clipped in the left
column (especially the per-MLTC checkbox text and the four radios), the
summary pane below the log.

- [ ] **Step 2: Rebuild the exe**

Run the project's usual PyInstaller build (see `MonthlyScheduleGenerator.spec`):

```bash
python -m PyInstaller MonthlyScheduleGenerator.spec --noconfirm
```

Expected: `dist/MonthlyScheduleGenerator.exe` updated. Launch it once
to confirm the window opens landscape.

- [ ] **Step 3: Commit any spec amendment**

```bash
git add docs/superpowers/specs/2026-09-23-landscape-main-window-design.md
git commit -m "docs: record height-fitting lever used for the landscape window"
```

(Skip if the spec did not change.)
