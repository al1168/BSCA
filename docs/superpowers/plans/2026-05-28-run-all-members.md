# "Run All Members" + Per-Plan Output Folders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fourth "Who" radio button ("All Members") to the GUI that schedules every Contacts row, with workbooks automatically split into `<PLAN>_<YYYY-MM>/` subfolders under the output path.

**Architecture:** Four small, independent pieces. (1) Four new i18n keys (EN + ZH). (2) New `get_all_members(db_path)` DB fetcher mirroring `get_members_by_plan` without the filter. (3) New `"all"` worker mode that calls `get_all_members` and computes a per-member output dir inside the loop. (4) GUI changes — fourth radio, fourth `QStackedWidget` panel (informational label only), `_build_summary` dispatch on a new `scope.mode` field.

**Tech Stack:** Python 3.13, PyQt6 6.11, pyodbc (Access ODBC), pytest 8.3.

**Spec:** [docs/superpowers/specs/2026-05-28-run-all-members-design.md](../specs/2026-05-28-run-all-members-design.md)

---

## Preconditions

- The `feat/schedule-data-model` branch was already merged to `main`; the `scope_data` payload mechanism is in place. All other infrastructure this feature needs (the new DB layer, MemberContext, per-day eligibility, i18n parity test) already exists.
- The four supporting tables (`Enrollment`, `Authorization`, `Absences`, `Availability`) exist in any DB this feature runs against.

---

## File Inventory

| File | Action | Responsibility |
| --- | --- | --- |
| `gui/i18n.py` | Modify | Add 4 new translation keys (EN + ZH): `who.all`, `who.all_hint`, `scope.all`, `worker.no_members`. |
| `monthly_schedule/db.py` | Modify | Add `ALL_MEMBERS_QUERY` constant and `get_all_members(db_path)` function. |
| `tests/test_db.py` | Modify | Add tests for the new query and the missing-DB error. |
| `gui/worker.py` | Modify | Import `get_all_members`. Add `mode == "all"` branch. Compute per-member output dir inside the loop. Include `mode` in the scope payload. |
| `gui/main_window.py` | Modify | Add `_radio_all` and `_all_hint_label`. Extend `_who_stack` with a fourth panel. Extend the mode list in `_run` to include `"all"`. Extend `_build_summary` to handle `mode == "all"`. |

No new files. No deletions. CLI (`new_monthly_schedule.py`) is intentionally not modified.

---

## Task 1: Add the four new i18n keys

**Files:**
- Modify: `gui/i18n.py`

Smallest change first — once the keys exist, every subsequent task can reference them via `tr(...)` without worrying about missing-key fallback noise.

- [ ] **Step 1: Add the four keys to `STRINGS["en"]`**

Open `gui/i18n.py` and find the `STRINGS["en"]` dict. Locate the existing `who.*` block (`who.title`, `who.single`, `who.multiple`, `who.plan`, `who.member_id_label`, etc.) and add `who.all` near them. Then add `who.all_hint` in the same neighborhood. Add `scope.all` next to the existing `scope.plan` / `scope.period` keys. Add `worker.no_members` next to the existing `worker.no_members_for_plan` key.

Use these exact values:

```python
        "who.all": "All Members",
        "who.all_hint": "All members in the database will be scheduled. Per-plan folders are created under your output path.",
        "scope.all": "all members {period}",
        "worker.no_members": "No members found in the database.",
```

- [ ] **Step 2: Add the four matching keys to `STRINGS["zh"]`**

In the `STRINGS["zh"]` dict, add the same keys with the Chinese values:

```python
        "who.all": "全部成员",
        "who.all_hint": "数据库中所有成员将被排班。将在输出路径下按计划创建子文件夹。",
        "scope.all": "所有成员 {period}",
        "worker.no_members": "数据库中找不到成员。",
```

- [ ] **Step 3: Run the i18n test suite (parity test will catch missing keys)**

```powershell
.venv\Scripts\pytest tests/test_i18n.py -v
```

Expected: 7 passed. The `test_key_parity` test confirms both language tables have the same keys.

- [ ] **Step 4: Commit**

```bash
git add gui/i18n.py
git commit -m "feat(i18n): add who.all, who.all_hint, scope.all, worker.no_members (EN+ZH)"
```

---

## Task 2: Add `get_all_members` DB fetcher + tests

**Files:**
- Modify: `monthly_schedule/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_all_members_query_columns_and_no_filter():
    from monthly_schedule.db import ALL_MEMBERS_QUERY
    for col in ("[Center ID]", "[Last Name]", "[First Name]",
                "[Health Plan]", "[Address]", "[Long Lat]"):
        assert col in ALL_MEMBERS_QUERY
    assert "FROM [Contacts]" in ALL_MEMBERS_QUERY
    assert "ORDER BY [Center ID]" in ALL_MEMBERS_QUERY
    # No WHERE clause — fetches every row.
    assert "WHERE" not in ALL_MEMBERS_QUERY


def test_get_all_members_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_all_members
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_all_members(str(missing))
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
.venv\Scripts\pytest tests/test_db.py::test_all_members_query_columns_and_no_filter tests/test_db.py::test_get_all_members_missing_db_raises -v
```

Expected: both fail with `ImportError` for `ALL_MEMBERS_QUERY` / `get_all_members`.

- [ ] **Step 3: Add the query and function to `monthly_schedule/db.py`**

Open `monthly_schedule/db.py`. Find the existing `MEMBERS_BY_PLAN_QUERY` block (with `get_members_by_plan`). Add the new constant and function directly after it:

```python
ALL_MEMBERS_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[Address], [Long Lat] FROM [Contacts] ORDER BY [Center ID]"
)


def get_all_members(db_path):
    """Return every Contacts row as a list of member dicts. Same dict
    shape as get_member and get_members_by_plan."""
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
        cursor.execute(ALL_MEMBERS_QUERY)
        return [map_member_row(row) for row in cursor.fetchall()]
    finally:
        conn.close()
```

- [ ] **Step 4: Run all DB tests to verify they pass**

```powershell
.venv\Scripts\pytest tests/test_db.py -v
```

Expected: every test passes, including the two new ones.

- [ ] **Step 5: Run the full suite as a regression check**

```powershell
.venv\Scripts\pytest -v
```

Expected: all tests pass (target ≥ 160).

- [ ] **Step 6: Commit**

```bash
git add monthly_schedule/db.py tests/test_db.py
git commit -m "feat(db): add get_all_members query + fetcher"
```

---

## Task 3: Worker `mode == \"all\"` branch + per-member output dir + scope mode

**Files:**
- Modify: `gui/worker.py`

After this task the worker is fully feature-complete; the GUI still doesn't surface the new mode yet (that's Task 4).

- [ ] **Step 1: Update the imports**

Find the existing `from monthly_schedule.db import (...)` block in `gui/worker.py` and add `get_all_members`. The block becomes:

```python
from monthly_schedule.db import (
    get_member, get_members_by_plan,
    get_enrollments, get_authorizations, get_absences, get_availability,
    get_all_members,
)
```

- [ ] **Step 2: Add the `all` branch to the member-fetch dispatch**

Find this block in `ScheduleWorker.run` (the part that decides which set of members to schedule, currently a two-branch if-else for `"plan"` vs id-list):

```python
        try:
            if self.mode == "plan":
                members = get_members_by_plan(self.plan_code, self.db_path)
                if not members:
                    self._emit_error(
                        tr(
                            "worker.no_members_for_plan",
                            plan=self.plan_code.upper(),
                        )
                    )
                    return
            else:
                id_list = (
                    [self.center_id]
                    if self.mode == "single"
                    else self.center_ids
                )
                for cid in id_list:
                    member = get_member(cid, self.db_path)
                    if member is None:
                        failures.append(
                            Failure(cid, "", "lookup", REASON_NOT_FOUND)
                        )
                    else:
                        members.append(member)
```

Replace with this three-branch version:

```python
        try:
            if self.mode == "plan":
                members = get_members_by_plan(self.plan_code, self.db_path)
                if not members:
                    self._emit_error(
                        tr(
                            "worker.no_members_for_plan",
                            plan=self.plan_code.upper(),
                        )
                    )
                    return
            elif self.mode == "all":
                members = get_all_members(self.db_path)
                if not members:
                    self._emit_error(tr("worker.no_members"))
                    return
            else:
                id_list = (
                    [self.center_id]
                    if self.mode == "single"
                    else self.center_ids
                )
                for cid in id_list:
                    member = get_member(cid, self.db_path)
                    if member is None:
                        failures.append(
                            Failure(cid, "", "lookup", REASON_NOT_FOUND)
                        )
                    else:
                        members.append(member)
```

- [ ] **Step 3: Compute the per-member output dir inside the loop**

Find the `for i, member in enumerate(members):` loop. Currently it builds `ctx` and immediately calls `process_member` with `self.out_dir`. Insert the per-member output-dir calculation between the ctx build and the `process_member` call.

The full updated loop should read:

```python
        for i, member in enumerate(members):
            ctx = MemberContext(
                enrollments=get_enrollments(member["center_id"], self.db_path),
                authorizations=get_authorizations(member["center_id"], self.db_path),
                absences=get_absences(member["center_id"], self.db_path),
                availabilities=get_availability(member["center_id"], self.db_path),
            )
            if self.mode == "all":
                plan = (member.get("health_plan") or "").strip().upper() or "_NoPlan"
                member_out_dir = os.path.join(
                    self.out_dir, f"{plan}_{self.year:04d}-{self.month:02d}"
                )
                if not self.preview:
                    os.makedirs(member_out_dir, exist_ok=True)
            else:
                member_out_dir = self.out_dir
            ok, stage, reason = process_member(
                member, ctx,
                self.year, self.month, member_out_dir,
                self.preview, api_key, cache,
            )
            if ok:
                success += 1
                if self.preview:
                    self.log_line.emit(
                        "worker.preview",
                        {
                            "id": member["center_id"],
                            "last": member["last_name"],
                            "first": member["first_name"],
                        },
                    )
                else:
                    fname = schedule_filename(
                        member["center_id"], self.year, self.month
                    )
                    self.log_line.emit("worker.wrote", {"filename": fname})
            else:
                failures.append(
                    Failure(
                        member["center_id"],
                        f"{member['last_name']}, {member['first_name']}",
                        stage,
                        reason,
                    )
                )
            self.progress.emit(i + 1, len(members))
```

(The only changes from the existing loop body are the new `if self.mode == "all": ...` block and the `member_out_dir` argument in the `process_member` call.)

- [ ] **Step 4: Add `mode` to the scope payload**

Find the `payload = {...}` dict near the end of `run()`:

```python
        payload = {
            "verb_key": "summary.verb.previewed" if self.preview else "summary.verb.wrote",
            "success": success,
            "total": total,
            "scope": {
                "plan_code": self.plan_code.upper() if self.mode == "plan" else None,
                "year": self.year,
                "month": self.month,
            },
            "out_dir": None if self.preview else self.out_dir,
            "failures": [...],
        }
```

Replace the `"scope"` value with the version that includes `mode`:

```python
            "scope": {
                "mode": self.mode,
                "plan_code": self.plan_code.upper() if self.mode == "plan" else None,
                "year": self.year,
                "month": self.month,
            },
```

- [ ] **Step 5: Verify the worker imports cleanly**

```powershell
.venv\Scripts\python.exe -c "from PyQt6.QtWidgets import QApplication; import sys; app = QApplication(sys.argv); from gui.worker import ScheduleWorker; print('OK')"
```

Expected: `OK`.

- [ ] **Step 6: Run the full test suite**

```powershell
.venv\Scripts\pytest -v
```

Expected: all tests pass (still ≥ 160).

- [ ] **Step 7: Commit**

```bash
git add gui/worker.py
git commit -m "feat(worker): add 'all' mode + per-plan output dir + scope.mode

Worker now supports a fourth mode that fetches every Contacts row.
For all-mode, each member's workbook is routed to a per-plan
subfolder (<PLAN>_<YYYY-MM>/, or _NoPlan_<YYYY-MM>/ when Health Plan
is NULL/empty). The scope payload now carries the mode so the GUI
summary can pick the right scope.* i18n key."
```

---

## Task 4: GUI radio + panel + `_build_summary` dispatch

**Files:**
- Modify: `gui/main_window.py`

After this task the feature is end-to-end usable.

- [ ] **Step 1: Add the `_radio_all` widget to the radio row**

Find this block in `MainWindow.__init__`:

```python
        radio_row = QHBoxLayout()
        self._radio_single = QRadioButton()
        self._radio_multiple = QRadioButton()
        self._radio_plan = QRadioButton()
        self._radio_single.setChecked(True)
        radio_row.addWidget(self._radio_single)
        radio_row.addWidget(self._radio_multiple)
        radio_row.addWidget(self._radio_plan)
        radio_row.addStretch()
```

Replace with:

```python
        radio_row = QHBoxLayout()
        self._radio_single = QRadioButton()
        self._radio_multiple = QRadioButton()
        self._radio_plan = QRadioButton()
        self._radio_all = QRadioButton()
        self._radio_single.setChecked(True)
        radio_row.addWidget(self._radio_single)
        radio_row.addWidget(self._radio_multiple)
        radio_row.addWidget(self._radio_plan)
        radio_row.addWidget(self._radio_all)
        radio_row.addStretch()
```

- [ ] **Step 2: Register the new radio with the button group**

Find this block:

```python
        self._who_group = QButtonGroup(self)
        self._who_group.addButton(self._radio_single, 0)
        self._who_group.addButton(self._radio_multiple, 1)
        self._who_group.addButton(self._radio_plan, 2)
        self._who_group.idToggled.connect(self._on_who_changed)
```

Replace with:

```python
        self._who_group = QButtonGroup(self)
        self._who_group.addButton(self._radio_single, 0)
        self._who_group.addButton(self._radio_multiple, 1)
        self._who_group.addButton(self._radio_plan, 2)
        self._who_group.addButton(self._radio_all, 3)
        self._who_group.idToggled.connect(self._on_who_changed)
```

- [ ] **Step 3: Add the fourth `_who_stack` panel**

Find the existing panels (`p0`, `p1`, `p2`) and the lines that add them to `_who_stack`:

```python
        self._who_stack.addWidget(p0)
        self._who_stack.addWidget(p1)
        self._who_stack.addWidget(p2)
```

Insert a new panel `p3` *before* those three lines (so the variable is defined when added), with the informational label, and add it to the stack:

```python
        # Panel 3 — all members (informational only, no input)
        p3 = QWidget()
        p3_layout = QHBoxLayout(p3)
        p3_layout.setContentsMargins(0, 0, 0, 0)
        self._all_hint_label = QLabel()
        self._all_hint_label.setWordWrap(True)
        p3_layout.addWidget(self._all_hint_label, 1)

        self._who_stack.addWidget(p0)
        self._who_stack.addWidget(p1)
        self._who_stack.addWidget(p2)
        self._who_stack.addWidget(p3)
```

- [ ] **Step 4: Update `_retranslate` to apply the new strings**

Find the existing `who.*` block inside `_retranslate`:

```python
        self._who_box.setTitle(tr("who.title"))
        self._radio_single.setText(tr("who.single"))
        self._radio_multiple.setText(tr("who.multiple"))
        self._radio_plan.setText(tr("who.plan"))
        self._single_label.setText(tr("who.member_id_label"))
        self._multi_label.setText(tr("who.member_ids_label"))
        self._multi_ids.setPlaceholderText(tr("who.placeholder"))
        self._plan_label_widget.setText(tr("who.plan_label"))
```

Replace with (adds two lines for the new radio and hint):

```python
        self._who_box.setTitle(tr("who.title"))
        self._radio_single.setText(tr("who.single"))
        self._radio_multiple.setText(tr("who.multiple"))
        self._radio_plan.setText(tr("who.plan"))
        self._radio_all.setText(tr("who.all"))
        self._single_label.setText(tr("who.member_id_label"))
        self._multi_label.setText(tr("who.member_ids_label"))
        self._multi_ids.setPlaceholderText(tr("who.placeholder"))
        self._plan_label_widget.setText(tr("who.plan_label"))
        self._all_hint_label.setText(tr("who.all_hint"))
```

- [ ] **Step 5: Extend `_run` to recognise the new mode**

Find this block at the top of `_run`:

```python
        mode_id = self._who_group.checkedId()
        mode = ["single", "multiple", "plan"][mode_id]
```

Replace with:

```python
        mode_id = self._who_group.checkedId()
        mode = ["single", "multiple", "plan", "all"][mode_id]
```

`center_id`, `center_ids`, and `plan_code` calculations a few lines below already use `if mode == "single"` / `"multiple"` / `"plan"` style conditionals, so they correctly become `None` for `"all"`. No further change needed in `_run`.

- [ ] **Step 6: Extend `_build_summary` to handle `mode == "all"`**

Find this block inside `_build_summary`:

```python
        scope = data["scope"]
        period = f"{scope['year']:04d}-{scope['month']:02d}"
        if scope["plan_code"] is not None:
            scope_text = tr("scope.plan", code=scope["plan_code"], period=period)
        else:
            scope_text = tr("scope.period", period=period)
```

Replace with the three-branch version:

```python
        scope = data["scope"]
        period = f"{scope['year']:04d}-{scope['month']:02d}"
        mode = scope.get("mode")
        if mode == "plan":
            scope_text = tr("scope.plan", code=scope["plan_code"], period=period)
        elif mode == "all":
            scope_text = tr("scope.all", period=period)
        else:
            scope_text = tr("scope.period", period=period)
```

- [ ] **Step 7: Verify the GUI imports cleanly and the new widget exists**

```powershell
.venv\Scripts\python.exe -c "from PyQt6.QtWidgets import QApplication; import sys; app = QApplication(sys.argv); from gui.main_window import MainWindow; w = MainWindow(); print('radio_all text:', w._radio_all.text()); print('hint visible widget:', type(w._all_hint_label).__name__); print('who.all stack count:', w._who_stack.count())"
```

Expected:
- `radio_all text: All Members` (or `全部成员` if Chinese is the persisted language)
- `hint visible widget: QLabel`
- `who.all stack count: 4`

- [ ] **Step 8: Run the full test suite**

```powershell
.venv\Scripts\pytest -v
```

Expected: all tests pass (still ≥ 160). No new GUI tests were added — coverage stays where it is.

- [ ] **Step 9: Manual smoke test against a test DB**

The plan-full test scenario covers a variety of plan codes already (HOF only, but it exercises the per-plan dir behavior). To test against more plans, use the `populate_real_members` scenario which seeds against all real Contacts and their real plan codes:

```powershell
python scripts\make_test_db.py --scenario populate_real_members --use
.venv\Scripts\python.exe gui.py
```

In the GUI:
1. Select the "All Members" radio.
2. Confirm the hint panel appears below the radios.
3. Pick the current month/year.
4. Enable "Preview only" first to avoid creating ~450 files, click "Generate Schedule", confirm the log shows preview lines and the summary headline reads `Previewed X of Y member(s) for all members <YYYY-MM>; Z failed.`
5. Uncheck preview. Pick a fresh output path (e.g. `out\all_test`). Click "Generate Schedule". Confirm:
   - The output path contains multiple `<PLAN>_<YYYY-MM>` subfolders.
   - Members with a Health Plan land in their plan's folder.
   - Members with NULL/empty Health Plan land in `_NoPlan_<YYYY-MM>/`.
   - The summary headline is the all-members variant.
6. Switch to 中文 via the top-bar combo. Confirm the radio reads `全部成员` and the hint reads in Chinese.

- [ ] **Step 10: Commit**

```bash
git add gui/main_window.py
git commit -m "feat(gui): add 'All Members' Who radio + per-plan summary scope

Fourth radio in the Who group with an informational panel.
_build_summary now dispatches on scope.mode to render the right
i18n key (scope.plan / scope.all / scope.period)."
```

---

## Self-Review Checklist (for the implementer)

Before declaring complete:

- [ ] `pytest -v` is green.
- [ ] `--scenario populate_real_members --use` smoke test produces multiple `<PLAN>_<YYYY-MM>/` folders under the output path.
- [ ] Members with no Health Plan land in `_NoPlan_<YYYY-MM>/`.
- [ ] English UI reads `All Members` and the hint paragraph; Chinese UI reads `全部成员` and the Chinese hint.
- [ ] Run-summary headline reads `... for all members <YYYY-MM> ...` (EN) or `所有成员 <YYYY-MM>` (ZH).
- [ ] No code outside `gui/i18n.py`, `gui/worker.py`, `gui/main_window.py`, `monthly_schedule/db.py`, `tests/test_db.py` was modified.
- [ ] CLI (`new_monthly_schedule.py`) is unchanged.

## Optional Follow-up (not in this plan)

- CLI `--all` flag mirroring the worker's branch.
- Surfacing the count of `_NoPlan` bucket members directly in the run summary.
- Parallelising the per-member loop for All-mode runs (could meaningfully cut wall-clock time for 454-member runs).
