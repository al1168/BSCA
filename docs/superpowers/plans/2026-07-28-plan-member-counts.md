# Plan Member Counts Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "Entire Plan" dropdown with a clickable per-plan table showing Active/Inactive member counts for the selected month, an All Members total row, roster captions, and a scope caption under the Generate button.

**Architecture:** A new Access query pair in `monthly_schedule/db.py` returns per-plan totals and month-overlap active counts, merged by a pure helper. A pure view-model (`gui/plan_counts.py`) turns those counts into fixed 8-plan table rows and captions — fully unit-testable without Qt or ODBC. A small `CountsWorker` QThread fetches counts off the UI thread; `gui/main_window.py` hosts the `QTableWidget`, wires row clicks to the Who radios, debounces Month/Year changes, and never blocks or pops errors for count failures.

**Tech Stack:** Python 3.11, pyodbc/Access, PyQt6, pytest.

**Spec:** `docs/superpowers/specs/2026-07-28-plan-member-counts-design.md`

**Test command** (repo root `c:\Users\luald\OneDrive\Desktop\BSCA`): `python -m pytest <file> -v`

**Testing note:** existing `tests/test_db.py` tests assert query text + mapping + missing-db errors (no live ODBC). This plan follows that established pattern; counting math is tested via the pure `merge_plan_counts` / view-model helpers. GUI behavior is verified with a headless smoke script (as done for the settings dialog feature).

---

## File map

| File | Change |
|---|---|
| `monthly_schedule/db.py` | `PLAN_TOTALS_QUERY`, `PLAN_ACTIVE_QUERY`, `merge_plan_counts()`, `get_plan_member_counts()` |
| `gui/plan_counts.py` (new) | `PLAN_CODES` (moved here), `plan_table_rows()`, `scope_caption()` |
| `gui/counts_worker.py` (new) | `CountsWorker(QThread)` |
| `gui/main_window.py` | table UI replacing `_plan_combo`, captions, debounce, refresh wiring |
| `gui/i18n.py` | ~10 new keys × en/zh |
| `docs/scheduling-flow.md` | note the counts feature |
| Tests | `tests/test_db.py`, new `tests/test_plan_counts.py`, new `tests/test_counts_worker.py` |

---

### Task 1: Counts queries + merge helper (`monthly_schedule/db.py`)

**Files:**
- Modify: `monthly_schedule/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_db.py` (it already imports the `db` module as in its other tests — match the file's existing import style):

```python
def test_plan_totals_query_shape():
    q = db.PLAN_TOTALS_QUERY
    assert "[Health Plan]" in q
    assert "COUNT(*)" in q
    assert "[Contacts]" in q
    assert "[Center ID] IS NOT NULL" in q
    assert "GROUP BY" in q


def test_plan_active_query_shape():
    q = db.PLAN_ACTIVE_QUERY
    assert "EXISTS" in q
    assert "[Enrollment]" in q
    assert "e.[start_date] <= ?" in q
    assert "e.[end_date] IS NULL OR e.[end_date] >= ?" in q
    assert "GROUP BY" in q
    # COUNT(DISTINCT ...) is not valid Access SQL — the EXISTS form is required.
    assert "DISTINCT" not in q


def test_merge_plan_counts_math():
    totals = [("HF", 100), ("BCBS", 50)]
    active = [("HF", 96), ("BCBS", 44)]
    out = db.merge_plan_counts(totals, active)
    assert out["plans"]["HF"] == {"total": 100, "active": 96}
    assert out["plans"]["BCBS"] == {"total": 50, "active": 44}
    assert out["total_active"] == 140


def test_merge_plan_counts_normalizes_codes():
    # Access text comparison is case-insensitive and users hand-type
    # plan codes — ' hf ' and 'HF' are the same plan.
    out = db.merge_plan_counts([(" hf ", 2), ("HF", 3)], [("hf", 4)])
    assert out["plans"]["HF"] == {"total": 5, "active": 4}
    assert out["total_active"] == 4


def test_merge_plan_counts_blank_plan_bucketed():
    # NULL/blank Health Plan rows count under "" so the All Members
    # total stays honest (All Members runs schedule everyone).
    out = db.merge_plan_counts([(None, 7), ("", 1)], [(None, 3)])
    assert out["plans"][""] == {"total": 8, "active": 3}
    assert out["total_active"] == 3


def test_merge_plan_counts_active_plan_missing_from_totals():
    # Defensive: an active row for a plan absent from totals must not crash.
    out = db.merge_plan_counts([], [("HF", 2)])
    assert out["plans"]["HF"] == {"total": 0, "active": 2}
    assert out["total_active"] == 2


def test_get_plan_member_counts_missing_db_raises(tmp_path):
    import datetime
    with pytest.raises(FileNotFoundError):
        db.get_plan_member_counts(
            str(tmp_path / "nope.accdb"),
            datetime.date(2026, 7, 1), datetime.date(2026, 7, 31),
        )
```

(If `tests/test_db.py` imports functions individually rather than `db`, adapt the references to that style — check its first 15 lines first.)

- [ ] **Step 2:** Run `python -m pytest tests/test_db.py -v -k "plan_totals or plan_active or merge_plan or plan_member"`. Expected: FAIL with AttributeError (names don't exist); other tests untouched.

- [ ] **Step 3: Implement.** In `monthly_schedule/db.py`, after the `get_all_members` block:

```python
PLAN_TOTALS_QUERY = (
    "SELECT [Health Plan], COUNT(*) FROM [Contacts] "
    "WHERE [Center ID] IS NOT NULL GROUP BY [Health Plan]"
)

# Access has no COUNT(DISTINCT ...); EXISTS keeps one row per member.
PLAN_ACTIVE_QUERY = (
    "SELECT c.[Health Plan], COUNT(*) FROM [Contacts] c "
    "WHERE c.[Center ID] IS NOT NULL AND EXISTS ("
    "SELECT 1 FROM [Enrollment] e "
    "WHERE e.[Center ID] = c.[Center ID] "
    "AND e.[start_date] <= ? "
    "AND (e.[end_date] IS NULL OR e.[end_date] >= ?)"
    ") GROUP BY c.[Health Plan]"
)


def _normalize_plan(value):
    """' hf ' / None -> 'HF' / '' so hand-typed plan codes merge."""
    return str(value or "").strip().upper()


def merge_plan_counts(total_rows, active_rows):
    """Merge (plan, count) rows from the two plan-count queries into
    {"plans": {CODE: {"total": t, "active": a}}, "total_active": n}.
    Blank/NULL plans land under ''. total_active spans ALL plans,
    known to the GUI or not (All Members runs schedule everyone)."""
    plans = {}
    for plan, count in total_rows:
        entry = plans.setdefault(_normalize_plan(plan),
                                 {"total": 0, "active": 0})
        entry["total"] += int(count)
    total_active = 0
    for plan, count in active_rows:
        entry = plans.setdefault(_normalize_plan(plan),
                                 {"total": 0, "active": 0})
        entry["active"] += int(count)
        total_active += int(count)
    return {"plans": plans, "total_active": total_active}


def get_plan_member_counts(db_path, month_start, month_end):
    """Per-plan member counts for the month [month_start, month_end].

    A member is ACTIVE when an Enrollment row overlaps any day of the
    month: start_date <= month_end AND (end_date IS NULL OR end_date
    >= month_start) — the same overlap rule eligibility uses. Returns
    merge_plan_counts() output. Raises FileNotFoundError/RuntimeError
    like the other helpers."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    import pyodbc

    try:
        conn = pyodbc.connect(build_connection_string(db_path))
    except pyodbc.Error as exc:
        raise RuntimeError(
            "Could not open the Access database. Verify the Microsoft "
            "Access ODBC driver is installed and its bitness matches "
            "this Python interpreter (spec section 8). "
            f"Original error: {exc}"
        )
    try:
        cursor = conn.cursor()
        cursor.execute(PLAN_TOTALS_QUERY)
        totals = cursor.fetchall()
        # Param order: start_date <= month_END, end_date >= month_START.
        cursor.execute(PLAN_ACTIVE_QUERY, month_end, month_start)
        active = cursor.fetchall()
        return merge_plan_counts(totals, active)
    finally:
        conn.close()
```

- [ ] **Step 4:** Run `python -m pytest tests/test_db.py -v`. Expected: all PASS.

- [ ] **Step 5: Commit:**
```bash
git add monthly_schedule/db.py tests/test_db.py
git commit -m "feat(db): per-plan member counts with month-overlap active rule"
```

---

### Task 2: View-model (`gui/plan_counts.py`, new)

**Files:**
- Create: `gui/plan_counts.py`
- Create: `tests/test_plan_counts.py`
- Modify: `gui/main_window.py` (only the `PLAN_CODES` import), `gui/i18n.py` (scope keys used by `scope_caption`)

- [ ] **Step 1: Write the failing tests.** Create `tests/test_plan_counts.py`:

```python
from gui.plan_counts import PLAN_CODES, plan_table_rows, scope_caption


def _counts():
    return {
        "plans": {
            "HF": {"total": 100, "active": 96},
            "BCBS": {"total": 50, "active": 44},
            "": {"total": 9, "active": 5},       # unknown-plan bucket
        },
        "total_active": 145,
    }


def test_rows_cover_all_eight_plans_in_order():
    rows, total = plan_table_rows(_counts())
    assert [r[0] for r in rows] == PLAN_CODES
    assert len(rows) == 8


def test_rows_math_and_missing_plans_zero():
    rows, total = plan_table_rows(_counts())
    by_code = {code: (active, inactive) for code, active, inactive in rows}
    assert by_code["HF"] == ("96", "4")
    assert by_code["BCBS"] == ("44", "6")
    assert by_code["VCM"] == ("0", "0")          # not in counts -> 0/0
    # Total spans ALL plans, including the unknown bucket.
    assert total == "145"


def test_rows_loading_state_shows_dashes():
    rows, total = plan_table_rows(None)
    assert all(active == "—" and inactive == "—" for _c, active, inactive in rows)
    assert total == "—"


def test_scope_caption_plan_mode():
    text = scope_caption(_counts(), "plan", "HF", "July", 2026)
    assert "96" in text and "HF" in text and "July" in text and "2026" in text


def test_scope_caption_all_mode():
    text = scope_caption(_counts(), "all", "HF", "July", 2026)
    assert "145" in text and "July" in text


def test_scope_caption_loading_and_other_modes():
    assert "—" in scope_caption(None, "plan", "HF", "July", 2026)
    assert scope_caption(_counts(), "single", "HF", "July", 2026) == ""
    assert scope_caption(_counts(), "multiple", "HF", "July", 2026) == ""
```

- [ ] **Step 2:** Run `python -m pytest tests/test_plan_counts.py -v`. Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement.** Create `gui/plan_counts.py`:

```python
"""Pure view-model for the plan-counts table (spec 2026-07-28).

No Qt, no ODBC — main_window renders what these helpers return, so the
row math, loading states, and captions stay unit-testable."""

from gui.i18n import tr

# Single source of truth for the GUI's plan list (moved from main_window).
PLAN_CODES = ["HF", "HOF", "VCM", "BCBS", "ES", "AE", "HC", "BCSB"]

LOADING = "—"


def plan_table_rows(counts):
    """Rows for the fixed 8-plan table.

    `counts` is get_plan_member_counts() output, or None while loading /
    after a failure. Returns (rows, total_active_str) where each row is
    (plan_code, active_str, inactive_str). Unknown-plan members appear
    only in the total (the table lists the 8 known codes)."""
    rows = []
    for code in PLAN_CODES:
        if counts is None:
            rows.append((code, LOADING, LOADING))
            continue
        entry = counts["plans"].get(code, {"total": 0, "active": 0})
        active = entry["active"]
        inactive = max(0, entry["total"] - active)
        rows.append((code, str(active), str(inactive)))
    total = LOADING if counts is None else str(counts["total_active"])
    return rows, total


def scope_caption(counts, mode, plan_code, month_name, year):
    """Caption under the Generate button ('' outside plan/all modes)."""
    if mode not in ("plan", "all"):
        return ""
    if counts is None:
        n = LOADING
    elif mode == "plan":
        entry = counts["plans"].get(plan_code)
        n = str(entry["active"]) if entry else "0"
    else:
        n = str(counts["total_active"])
    key = "plan_table.scope.plan" if mode == "plan" else "plan_table.scope.all"
    return tr(key, count=n, plan=plan_code, month=month_name, year=year)
```

In `gui/i18n.py` add to the **en** block (after `"opts.print"`):

```python
        "plan_table.scope.plan": (
            "{count} active member(s) for {plan} in {month} {year}"
        ),
        "plan_table.scope.all": (
            "{count} active member(s) across all plans in {month} {year}"
        ),
```

and to the **zh** block (after its `"opts.print"`):

```python
        "plan_table.scope.plan": "{month} {year}：{plan} 共 {count} 名在册成员",
        "plan_table.scope.all": "{month} {year}：全部计划共 {count} 名在册成员",
```

In `gui/main_window.py`: delete the module-level `PLAN_CODES = [...]` line and add `from gui.plan_counts import PLAN_CODES` with the other `gui.` imports.

- [ ] **Step 4:** Run `python -m pytest tests/test_plan_counts.py tests/test_i18n.py -q`. Expected: all PASS (key parity holds). Then `python -m pytest -q` — full suite green (the import move must not break anything).

- [ ] **Step 5: Commit:**
```bash
git add gui/plan_counts.py gui/i18n.py gui/main_window.py tests/test_plan_counts.py
git commit -m "feat(gui): plan-counts view model + scope captions"
```

---

### Task 3: Counts worker (`gui/counts_worker.py`, new)

**Files:**
- Create: `gui/counts_worker.py`
- Create: `tests/test_counts_worker.py`

- [ ] **Step 1: Write the failing tests.** Create `tests/test_counts_worker.py` (same harness as `tests/test_print_worker.py`):

```python
import sys

import pytest

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer


@pytest.fixture(scope="module", autouse=True)
def _qapp():
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    yield app


from gui.counts_worker import CountsWorker


def _run_to_completion(worker, timeout_ms=5000):
    loop = QEventLoop()
    captured = []

    def on_finished(success, payload):
        captured.append((success, payload))
        loop.quit()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)

    worker.finished.connect(on_finished)
    worker.start()
    loop.exec()
    timer.stop()
    worker.wait(timeout_ms)
    assert captured, "worker did not emit finished within timeout"
    return captured[0]


def test_counts_worker_passes_month_bounds(monkeypatch):
    seen = {}

    def fake_counts(db_path, month_start, month_end):
        seen["args"] = (db_path, month_start, month_end)
        return {"plans": {}, "total_active": 0}

    monkeypatch.setattr(
        "gui.counts_worker.get_plan_member_counts", fake_counts
    )
    worker = CountsWorker("some.accdb", 2024, 2)   # Feb 2024 (leap year)
    success, payload = _run_to_completion(worker)
    assert success is True
    assert payload == {"plans": {}, "total_active": 0}
    import datetime
    assert seen["args"] == (
        "some.accdb",
        datetime.date(2024, 2, 1),
        datetime.date(2024, 2, 29),
    )


def test_counts_worker_surfaces_errors(monkeypatch):
    def boom(db_path, month_start, month_end):
        raise RuntimeError("no driver")

    monkeypatch.setattr("gui.counts_worker.get_plan_member_counts", boom)
    worker = CountsWorker("some.accdb", 2026, 7)
    success, payload = _run_to_completion(worker)
    assert success is False
    assert "no driver" in payload["error"]
```

- [ ] **Step 2:** Run `python -m pytest tests/test_counts_worker.py -v`. Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement.** Create `gui/counts_worker.py`:

```python
"""Background thread that fetches per-plan member counts.

Counts are informational (spec 2026-07-28): failures are emitted, not
raised — the main window shows an 'unavailable' caption, never a popup."""

import calendar
import datetime

from PyQt6.QtCore import QThread, pyqtSignal

from monthly_schedule.db import get_plan_member_counts


class CountsWorker(QThread):
    finished = pyqtSignal(bool, dict)   # (success, counts | {"error": str})

    def __init__(self, db_path, year, month, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._year = year
        self._month = month

    def run(self):
        try:
            last = calendar.monthrange(self._year, self._month)[1]
            counts = get_plan_member_counts(
                self._db_path,
                datetime.date(self._year, self._month, 1),
                datetime.date(self._year, self._month, last),
            )
            self.finished.emit(True, counts)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI caption
            self.finished.emit(False, {"error": str(exc)})
```

- [ ] **Step 4:** Run `python -m pytest tests/test_counts_worker.py -v`. Expected: all PASS.

- [ ] **Step 5: Commit:**
```bash
git add gui/counts_worker.py tests/test_counts_worker.py
git commit -m "feat(gui): background worker for plan member counts"
```

---

### Task 4: Table UI + selection wiring (`gui/main_window.py`)

**Files:**
- Modify: `gui/main_window.py`, `gui/i18n.py`

No new automated tests in this task (the repo has no QWidget-level test harness); logic stays in the tested view-model, and Step 4 smoke-verifies headlessly.

- [ ] **Step 1: i18n keys.** In `gui/i18n.py` add to **en** (after the `plan_table.scope.all` key from Task 2 (renamed from the plan's original `scope.*` — those keys already existed for the run summary)):

```python
        "plan_table.header.plan": "Plan",
        "plan_table.header.active": "Active members",
        "plan_table.header.inactive": "Inactive",
        "plan_table.all_members": "All Members",
        "plan_table.roster": "Roster for {month} {year}",
        "plan_table.unavailable": "Member counts unavailable",
        "plan_table.excluded": (
            "Inactive members are excluded from generated timesheets"
        ),
        "who.plan_hint": "Pick a plan in the table below.",
```

and to **zh**:

```python
        "plan_table.header.plan": "计划",
        "plan_table.header.active": "在册成员",
        "plan_table.header.inactive": "非在册",
        "plan_table.all_members": "所有成员",
        "plan_table.roster": "{month} {year} 名册",
        "plan_table.unavailable": "无法获取成员数量",
        "plan_table.excluded": "生成的考勤表不包含非在册成员",
        "who.plan_hint": "请在下方表格中选择计划。",
```

- [ ] **Step 2: Replace the plan panel and add the table.** In `gui/main_window.py`:

1. Extend the PyQt6.QtWidgets import with `QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView` (keep alphabetical order if the file uses it) and ensure `Qt` is imported from `PyQt6.QtCore`, plus `QFont` from QtGui (already imported for the title font). Change the Task 2 import line to `from gui.plan_counts import PLAN_CODES, plan_table_rows, scope_caption` — this task's methods use all three.

2. Replace Panel 2's combo contents (lines ~145-155) with a hint label:

```python
        # Panel 2 — plan (selection happens in the table below)
        p2 = QWidget()
        p2_layout = QHBoxLayout(p2)
        p2_layout.setContentsMargins(0, 0, 0, 0)
        self._plan_hint_label = QLabel()
        self._plan_hint_label.setWordWrap(True)
        p2_layout.addWidget(self._plan_hint_label, 1)
```

Delete `self._plan_combo` entirely and `self._plan_label_widget`.

3. After `who_layout.addWidget(self._who_stack)` insert the table + captions:

```python
        # Plan-counts table (spec 2026-07-28): always visible; rows are
        # the 8 known plans plus a bold All Members total row.
        self._plan_row = 0            # selected plan index into PLAN_CODES
        self._plan_counts = None      # last CountsWorker result (None=loading)
        self._counts_failed = False

        self._plan_table = QTableWidget(len(PLAN_CODES) + 1, 3)
        self._plan_table.verticalHeader().setVisible(False)
        self._plan_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._plan_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._plan_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._plan_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._plan_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._plan_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        header = self._plan_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._plan_table.setColumnWidth(1, 130)
        self._plan_table.setColumnWidth(2, 100)
        for row in range(len(PLAN_CODES) + 1):
            for col in range(3):
                item = QTableWidgetItem("")
                if col > 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter
                    )
                if row == len(PLAN_CODES):
                    font = QFont()
                    font.setBold(True)
                    item.setFont(font)
                self._plan_table.setItem(row, col, item)
        self._plan_table.cellClicked.connect(self._on_plan_row_clicked)
        who_layout.addWidget(self._plan_table)

        caption_row = QHBoxLayout()
        self._roster_label = QLabel()
        self._excluded_label = QLabel()
        for lbl in (self._roster_label, self._excluded_label):
            lbl.setStyleSheet("color: gray; font-size: 11px;")
        caption_row.addWidget(self._roster_label)
        caption_row.addStretch()
        caption_row.addWidget(self._excluded_label)
        who_layout.addLayout(caption_row)
```

4. Size the table once populated — add at the end of `__init__` (before `self._retranslate()`):

```python
        self._update_plan_table()
        row_h = self._plan_table.verticalHeader().defaultSectionSize()
        self._plan_table.setFixedHeight(
            self._plan_table.horizontalHeader().sizeHint().height()
            + row_h * (len(PLAN_CODES) + 1)
            + 2 * self._plan_table.frameWidth()
        )
```

5. New methods on `MainWindow` (near `_on_who_changed`):

```python
    def _on_plan_row_clicked(self, row: int, _col: int):
        if row < len(PLAN_CODES):
            self._plan_row = row
            self._radio_plan.setChecked(True)
        else:
            self._radio_all.setChecked(True)
        self._sync_plan_selection()

    def _sync_plan_selection(self):
        """Reflect the Who mode in the table highlight + scope caption."""
        mode_id = self._who_group.checkedId()
        if mode_id == 2:
            self._plan_table.selectRow(self._plan_row)
        elif mode_id == 3:
            self._plan_table.selectRow(len(PLAN_CODES))
        else:
            self._plan_table.clearSelection()
        self._update_scope_label()

    def _update_plan_table(self):
        rows, total = plan_table_rows(self._plan_counts)
        for i, (code, active, inactive) in enumerate(rows):
            self._plan_table.item(i, 0).setText(code)
            self._plan_table.item(i, 1).setText(active)
            self._plan_table.item(i, 2).setText(inactive)
        last = len(PLAN_CODES)
        self._plan_table.item(last, 0).setText(tr("plan_table.all_members"))
        self._plan_table.item(last, 1).setText(total)
        self._plan_table.item(last, 2).setText("")
        month = self._month_combo.currentIndex() + 1
        if self._counts_failed:
            self._roster_label.setText(tr("plan_table.unavailable"))
        else:
            self._roster_label.setText(tr(
                "plan_table.roster",
                month=tr(f"when.month.{month}"),
                year=self._year_spin.value(),
            ))
        self._update_scope_label()

    def _update_scope_label(self):
        mode_id = self._who_group.checkedId()
        mode = ["single", "multiple", "plan", "all"][mode_id]
        month = self._month_combo.currentIndex() + 1
        self._scope_label.setText(scope_caption(
            self._plan_counts, mode, PLAN_CODES[self._plan_row],
            tr(f"when.month.{month}"), self._year_spin.value(),
        ))
```

6. Extend `_on_who_changed` so mode changes drive the highlight:

```python
    def _on_who_changed(self, btn_id: int, checked: bool):
        if checked:
            self._who_stack.setCurrentIndex(btn_id)
            self._sync_plan_selection()
```

7. Scope label under the Generate button — right after the `self._generate_btn` is added to `root` (find `root.addWidget(self._generate_btn)`):

```python
        self._scope_label = QLabel()
        self._scope_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scope_label.setStyleSheet("color: gray; font-size: 11px;")
        root.addWidget(self._scope_label)
```

(If the button is added via a layout, place the label immediately after it in the same layout.) NOTE: `_scope_label` must be created before `_update_plan_table()` runs at the end of `__init__` — construction order: widgets first, then the sizing/populate block from sub-step 4.

8. `_retranslate` — replace the old plan-combo label line with:

```python
        self._plan_hint_label.setText(tr("who.plan_hint"))
        self._plan_table.setHorizontalHeaderLabels([
            tr("plan_table.header.plan"),
            tr("plan_table.header.active"),
            tr("plan_table.header.inactive"),
        ])
        self._excluded_label.setText(tr("plan_table.excluded"))
        self._update_plan_table()
```

9. Generation plumbing — in the start method replace `plan_code = self._plan_combo.currentText() if mode == "plan" else None` with:

```python
        plan_code = PLAN_CODES[self._plan_row] if mode == "plan" else None
```

- [ ] **Step 3:** Run `python -m pytest -q`. Expected: full suite passes (no automated UI tests, but imports and i18n parity must hold).

- [ ] **Step 4: Headless smoke.** Write to the scratchpad (NOT the repo) and run:

```python
import sys
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
with patch("gui.app_settings.load", return_value={
    "db_path": "nope.accdb", "output_path": ".", "google_api_key": "",
    "geo_cache": "geo_cache.json", "language": "en", "schedule_rules": {},
}):
    from gui.main_window import MainWindow, PLAN_CODES
    w = MainWindow()
    assert w._plan_table.rowCount() == len(PLAN_CODES) + 1
    assert w._plan_table.item(0, 0).text() == "HF"
    assert w._plan_table.item(len(PLAN_CODES), 0).text() == "All Members"
    assert w._plan_table.item(0, 1).text() == "—"     # loading state
    w._on_plan_row_clicked(3, 0)                       # BCBS row
    assert w._radio_plan.isChecked() and w._plan_row == 3
    w._on_plan_row_clicked(len(PLAN_CODES), 0)         # All Members row
    assert w._radio_all.isChecked()
    print("SMOKE OK")
```

Expected output: `SMOKE OK`. (Counts-fetch wiring lands in Task 5, so no worker runs here.)

- [ ] **Step 5: Commit:**
```bash
git add gui/main_window.py gui/i18n.py
git commit -m "feat(gui): plan table with member counts replaces plan dropdown"
```

---

### Task 5: Counts refresh wiring (`gui/main_window.py`)

**Files:**
- Modify: `gui/main_window.py`

- [ ] **Step 1: Implement the refresh plumbing.**

1. Imports: `from gui.counts_worker import CountsWorker`, `from gui.plan_counts import PLAN_CODES, plan_table_rows, scope_caption` (merge with the Task 2 import), and `QTimer` from `PyQt6.QtCore`.

2. In `__init__` (near `self._print_worker = None`):

```python
        self._counts_worker = None
        self._counts_seq = 0          # stale-result guard
        self._counts_timer = QTimer(self)
        self._counts_timer.setSingleShot(True)
        self._counts_timer.setInterval(300)   # debounce month spinning
        self._counts_timer.timeout.connect(self._start_counts_refresh)
```

3. Wire the triggers (next to the existing `_update_range_max` connections at lines ~220-224):

```python
        self._month_combo.currentIndexChanged.connect(
            lambda _i: self._counts_timer.start()
        )
        self._year_spin.valueChanged.connect(
            lambda _v: self._counts_timer.start()
        )
```

and at the very end of `__init__` (after `_retranslate()`):

```python
        self._start_counts_refresh()
```

4. New methods:

```python
    def _start_counts_refresh(self):
        """Fetch counts for the selected month on a background thread.
        Only the latest request's result is applied."""
        self._counts_seq += 1
        seq = self._counts_seq
        self._plan_counts = None
        self._counts_failed = False
        self._update_plan_table()
        worker = CountsWorker(
            self._settings.get("db_path", ""),
            self._year_spin.value(),
            self._month_combo.currentIndex() + 1,
        )
        worker.finished.connect(
            lambda ok, payload: self._on_counts_finished(seq, ok, payload)
        )
        self._counts_worker = worker
        worker.start()

    def _on_counts_finished(self, seq: int, success: bool, payload: dict):
        if seq != self._counts_seq:
            return   # a newer request superseded this one
        if success:
            self._plan_counts = payload
            self._counts_failed = False
        else:
            self._plan_counts = None
            self._counts_failed = True
        self._update_plan_table()
```

5. Refresh after Settings saves a new db_path — extend `_open_settings` (the method already updates `self._settings`):

```python
    def _open_settings(self):
        dlg = SettingsDialog(self._settings, self)
        if dlg.exec():
            result = dlg.get_settings()
            if result:
                old_db = self._settings.get("db_path")
                self._settings.update(result)
                app_settings.save(self._settings)
                self._out_label.setText(self._settings.get("output_path", "."))
                if self._settings.get("db_path") != old_db:
                    self._start_counts_refresh()
```

- [ ] **Step 2:** Run `python -m pytest -q`. Expected: full suite passes.

- [ ] **Step 3: Headless smoke of the refresh loop.** Scratchpad script:

```python
import sys
from unittest.mock import patch
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
fake = {"plans": {"HF": {"total": 10, "active": 7}}, "total_active": 7}
with patch("gui.app_settings.load", return_value={
    "db_path": "nope.accdb", "output_path": ".", "google_api_key": "",
    "geo_cache": "geo_cache.json", "language": "en", "schedule_rules": {},
}), patch("gui.counts_worker.get_plan_member_counts", return_value=fake):
    from gui.main_window import MainWindow
    w = MainWindow()
    loop = QEventLoop(); QTimer.singleShot(1500, loop.quit); loop.exec()
    assert w._plan_table.item(0, 1).text() == "7", w._plan_table.item(0, 1).text()
    assert w._plan_table.item(0, 2).text() == "3"
    w._radio_plan.setChecked(True)
    assert "7" in w._scope_label.text()
    print("SMOKE OK")
```

Expected: `SMOKE OK`. Also verify the failure path by re-running with `patch("gui.counts_worker.get_plan_member_counts", side_effect=RuntimeError("x"))` and asserting `w._roster_label.text() == "Member counts unavailable"` after the loop.

- [ ] **Step 4: Commit:**
```bash
git add gui/main_window.py
git commit -m "feat(gui): debounced background refresh of plan member counts"
```

---

### Task 6: Docs, full suite, rebuild

**Files:**
- Modify: `docs/scheduling-flow.md`

- [ ] **Step 1:** In `docs/scheduling-flow.md`, add a short note in the GUI section (match the doc's tone): the Entire Plan selector is a table showing, for the selected month, each plan's active members (an Enrollment row overlapping any day of the month) and inactive members (remaining Contacts of that plan); counts are informational only — eligibility still decides who is scheduled.

- [ ] **Step 2:** Run `python -m pytest -q`. Expected: all tests pass.

- [ ] **Step 3:** Commit docs:
```bash
git add docs/scheduling-flow.md
git commit -m "docs: plan member counts table"
```

- [ ] **Step 4: Rebuild the exe** (required — the user runs `dist\MonthlyScheduleGenerator.exe`): confirm the app isn't running (`Get-Process MonthlyScheduleGenerator` errors), then:

```bash
.venv/Scripts/pyinstaller --noconfirm MonthlyScheduleGenerator.spec
```

Expected: `Build complete!` and a fresh `dist/MonthlyScheduleGenerator.exe` timestamp. If the exe is locked, ask the user to close the app first.
