# "Run All Members" + Per-Plan Output Folders

**Date:** 2026-05-28
**Status:** Approved (pending spec review)
**Scope:** GUI feature: add a fourth "Who" radio that schedules every member in Contacts, with output workbooks automatically split into per-plan subfolders.

## Goal

One click to generate schedules for every member in the database, with output organized into `<base>/<PLAN>_<YYYY-MM>/` subfolders so a coordinator can hand each plan's results to the right people without sorting.

## Design Decisions (Recap From Brainstorming)

| Decision | Choice |
| --- | --- |
| Run-all placement in the GUI | Fourth radio button in the WHO group, alongside Single / Multiple / Entire Plan |
| Per-plan folder split | **Implicit** for All Members mode only — no UI knob. Other modes keep their existing output behavior. |
| Folder naming convention | `<PLAN>_<YYYY-MM>/` (same as Entire-Plan mode), with `_NoPlan_<YYYY-MM>/` for members with NULL/empty Health Plan |
| NULL plan handling | Visible bucket (`_NoPlan_<YYYY-MM>/`), not filtered out |
| CLI extension | Out of scope for v1 — GUI only. A `--all` flag is a clean follow-up. |

## Architecture

Three small additions and one tweak to the existing flow:

1. **New DB fetcher** `get_all_members(db_path)` mirrors `get_members_by_plan` without a parameter binding. Returns every Contacts row as a member dict.
2. **New worker mode** `"all"`. Dispatches to `get_all_members` and computes a per-member output dir inside the loop, based on the member's `health_plan`.
3. **GUI radio** `_radio_all` joins the existing WHO group as button id `3`. Its `QStackedWidget` panel is a single informational `QLabel` (no input control needed).
4. **`scope_data` payload** carried on the `finished` Qt signal grows a `mode` field so `main_window._build_summary` can pick the right `scope.*` i18n key.

`process_member` is **not** modified — it continues to take a single `out_dir` per call, and the worker resolves the per-plan dir before invoking it.

## File Inventory

| File | Action | Responsibility |
| --- | --- | --- |
| `monthly_schedule/db.py` | Modify | Add `ALL_MEMBERS_QUERY` + `get_all_members(db_path)`. Mirrors `get_members_by_plan` without the parameter. |
| `gui/worker.py` | Modify | Add `mode == "all"` branch to the member-fetch dispatch. Compute per-member `member_out_dir` inside the loop. Include `mode` in the scope payload. |
| `gui/main_window.py` | Modify | Add `self._radio_all` + a fourth `QStackedWidget` panel (single label). Wire it as button id 3. Extend the mode list to include `"all"`. Extend `_build_summary` to handle `scope.mode == "all"`. |
| `gui/i18n.py` | Modify | Add `who.all`, `who.all_hint`, `scope.all` (EN + ZH). Optionally `worker.no_members` if we want a distinct message for empty Contacts. |
| `tests/test_db.py` | Modify | Add tests for `ALL_MEMBERS_QUERY` columns and `get_all_members` missing-DB FileNotFoundError. |
| `tests/test_cli.py` | (no change) | CLI is not extended; existing tests keep passing. |

No changes to:
- `new_monthly_schedule.py` (`process_member` unchanged; CLI not extended).
- `monthly_schedule/eligibility_context.py`, `per_day.py`, `rules.py`, `rows.py`, `daily_schedule.py`, `workbook.py` — all untouched.
- `gui/settings_dialog.py`, `gui/errors.py` — untouched.

## Data Layer

In `monthly_schedule/db.py`:

```python
ALL_MEMBERS_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[Address], [Long Lat] FROM [Contacts] ORDER BY [Center ID]"
)


def get_all_members(db_path):
    """Return every Contacts row as a list of member dicts."""
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

Returns the same `member` dict shape every other fetcher returns
(`center_id`, `last_name`, `first_name`, `health_plan`, `address`, `long_lat`).

## Worker Changes

In `gui/worker.py` member-fetch dispatch:

```python
if self.mode == "plan":
    members = get_members_by_plan(self.plan_code, self.db_path)
    if not members:
        self._emit_error(
            tr("worker.no_members_for_plan", plan=self.plan_code.upper())
        )
        return
elif self.mode == "all":
    members = get_all_members(self.db_path)
    if not members:
        self._emit_error(tr("worker.no_members"))
        return
else:
    # single / multiple — existing per-id lookup
    ...
```

Per-member loop:

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
        member, ctx, self.year, self.month, member_out_dir,
        self.preview, api_key, cache,
    )
    # … existing log_line emission + progress + failure tracking …
```

Scope payload:

```python
payload = {
    "verb_key": "summary.verb.previewed" if self.preview else "summary.verb.wrote",
    "success": success,
    "total": total,
    "scope": {
        "mode": self.mode,                                          # NEW
        "plan_code": self.plan_code.upper() if self.mode == "plan" else None,
        "year": self.year,
        "month": self.month,
    },
    "out_dir": None if self.preview else self.out_dir,
    "failures": [...],
}
```

## GUI Changes

In `gui/main_window.py` WHO section:

```python
self._radio_single = QRadioButton()
self._radio_multiple = QRadioButton()
self._radio_plan = QRadioButton()
self._radio_all = QRadioButton()                       # NEW
...
self._who_group.addButton(self._radio_single, 0)
self._who_group.addButton(self._radio_multiple, 1)
self._who_group.addButton(self._radio_plan, 2)
self._who_group.addButton(self._radio_all, 3)          # NEW
```

Fourth panel for the `_who_stack`:

```python
p3 = QWidget()
p3_layout = QHBoxLayout(p3)
p3_layout.setContentsMargins(0, 0, 0, 0)
self._all_hint_label = QLabel()
self._all_hint_label.setWordWrap(True)
p3_layout.addWidget(self._all_hint_label)
self._who_stack.addWidget(p3)
```

Updates in `_retranslate`:

```python
self._radio_all.setText(tr("who.all"))
self._all_hint_label.setText(tr("who.all_hint"))
```

`_run` extends the mode list and skips the plan/id collection for All:

```python
mode_id = self._who_group.checkedId()
mode = ["single", "multiple", "plan", "all"][mode_id]
...
center_id = self._single_id.value() if mode == "single" else None
center_ids = (
    parse_center_ids(self._multi_ids.text()) if mode == "multiple" else None
)
plan_code = self._plan_combo.currentText() if mode == "plan" else None
```

Validation (`_validate`): the `mode_id == 3` (All) branch is a pass-through — no input to check.

`_build_summary` dispatches on the new `mode` field:

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

## i18n Additions

| Key | English | Simplified Chinese |
| --- | --- | --- |
| `who.all` | `All Members` | `全部成员` |
| `who.all_hint` | `All members in the database will be scheduled. Per-plan folders are created under your output path.` | `数据库中所有成员将被排班。将在输出路径下按计划创建子文件夹。` |
| `scope.all` | `all members {period}` | `所有成员 {period}` |
| `worker.no_members` | `No members found in the database.` | `数据库中找不到成员。` |

`tests/test_i18n.py::test_key_parity` auto-enforces parity.

## Folder Layout Examples

```
out/                              <-- base output path
├── HOF_2026-05/
│   ├── Schedule_24010_2026-05.xlsx
│   ├── Schedule_24011_2026-05.xlsx
│   └── ...
├── VCM_2026-05/
│   └── Schedule_24050_2026-05.xlsx
├── BCBS_2026-05/
│   └── ...
└── _NoPlan_2026-05/
    └── Schedule_24099_2026-05.xlsx   (member whose Health Plan was NULL)
```

## Edge Cases & Behavior

| Situation | Behavior |
| --- | --- |
| Empty Contacts (zero rows returned) | Worker emits a `worker.no_members` failure-text and the run ends with no workbook written. |
| Member's `Health Plan` is NULL or empty | Workbook lands in `<base>/_NoPlan_<YYYY-MM>/`. The sentinel folder is visible so the data-quality issue isn't hidden. |
| Members fail eligibility (no enrollment / no auth / absent month) before workbook write | Their per-plan dir gets created but stays empty for them. Cosmetic only; if a plan has zero successful members, you'll see one empty folder. Acceptable. |
| "Open Output Folder" button after an All-mode run | Opens the base output path (`self._last_out_dir == out_dir == base` because `plan_code` is None for All mode). User sees every per-plan subfolder side-by-side. |
| Performance — 454 members × travel resolution | Existing progress bar updates per member. Cache (`geo_cache.json`) makes repeat runs much faster. No new mitigation needed. |
| Validation when "All Members" is selected | No member-id / plan-code input is required; `_validate` returns True without prompting. DB path / Google config checks still run as today. |
| Preview mode + All Members | Same as preview today — no folders created, rows printed to log. The per-plan-dir `os.makedirs` is gated behind `not self.preview`. |
| Run summary headline | Reads `Wrote 415 of 454 member(s) for all members 2026-05 into <out>; 39 failed.` (English) or `已写入 所有成员 2026-05 的 454 名成员中的 415 名，至 <out>；39 名失败。` (Chinese). |

## Out of Scope (YAGNI)

- **CLI extension** for `--all`. Easy to add later by mirroring the worker's branch in `new_monthly_schedule.main`. Not required to ship this GUI feature.
- **A "Group by plan" checkbox** for Multiple Members mode. The user explicitly chose "implicit for All only" to avoid UI clutter.
- **Surfacing a `_NoPlan` count in the summary**. The folder makes it visible; we can add a callout key later if it becomes a frequent confusion.
- **Parallel/threaded member processing** to speed up large All runs. The existing per-member loop is sequential and that's fine for now.

## What Changes In Code

Modified:
- `monthly_schedule/db.py`
- `gui/worker.py`
- `gui/main_window.py`
- `gui/i18n.py`
- `tests/test_db.py`

No new files. No deletions.

## See Also

- [docs/database.md](../../database.md) — schema reference (per-day eligibility flow already accounts for the failure paths this feature will surface at scale).
- [docs/superpowers/specs/2026-05-26-schedule-data-model-design.md](2026-05-26-schedule-data-model-design.md) — the data-model redesign that introduced the per-day eligibility checks this feature exercises across every member.
