# Simple Debug Reasons + Full-Month Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The per-member debug CSV shows one row for every day of the selected month with a plain-English `reason` sentence, keeping the existing technical columns.

**Architecture:** All changes live in `build_debug_rows` (monthly_schedule/rows.py) plus a new sentence formatter beside it. The internal `REASON_DAY_*` constants and scheduling logic are untouched — the raw constant is still used internally (`_reason_detail` branches on it); only the CSV-facing `reason` string changes. Full-month coverage comes from deleting the two authorized-day skips; `compute_day_eligibility` already returns the right rejection for non-enrolled / no-auth / wrong-weekday days.

**Tech Stack:** Python 3.11, pytest. Spec: `docs/superpowers/specs/2026-09-01-simple-debug-reasons-design.md`.

---

### Task 1: Plain-English reason sentences

**Files:**
- Modify: `monthly_schedule/rows.py`
- Test: `tests/test_rows.py`

- [ ] **Step 1: Update existing tests to expect sentences**

In `tests/test_rows.py` make these exact edits:

1a. In `test_debug_rows_only_authorized_weekdays` (~line 193) replace the last two asserts:

```python
    # All days scheduled.
    assert all(r["scheduled"] is True for r in rows)
    assert all(r["reason"] == "Scheduled" for r in rows)
```

1b. In `test_debug_rows_records_absence_reason` (~line 223):

```python
    assert monday["reason"] == "Marked absent (Vacation)"
```

1c. In `test_debug_rows_records_window_too_narrow` (~line 304):

```python
    assert monday["reason"] == (
        "Available time (12:00-13:30) is too short to fit a session"
    )
```

1d. In `test_debug_rows_catches_one_off_conflict` (~line 419): the simple
sentence moves to `reason`, the old detailed sentence moves to
`reason_detail`:

```python
    assert monday["reason"] == (
        "2 conflicting one-off availability entries exist for this day"
    )
    assert monday["reason_detail"] == (
        "2 one-off rows for 2026-05-04: 09:00-12:00 (row 1) "
        "and 10:00-13:00 (row 2)"
    )
```

1e. Add a new test after `test_debug_rows_catches_one_off_conflict`
(the one-off + absence conflict sentence):

```python
def test_debug_rows_one_off_absence_conflict_sentence():
    one_off = {"id": 4, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "09:00", "avail_end": "12:00"}
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[{"id": 14, "center_id": 1, "leave_type": "Hospital",
                   "start_date": date(2026, 5, 4),
                   "end_date": date(2026, 5, 8)}],
        availabilities=[],
        one_offs=[one_off],
    )
    rows = build_debug_rows(2026, 5, ctx, PLAN_RULES)
    monday = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert monday["scheduled"] is False
    assert monday["reason"] == (
        "A one-off availability entry conflicts with an absence on this day"
    )
    # The detailed sentence (with the Access row IDs) is preserved.
    assert "OneOffAvailability row 4" in monday["reason_detail"]
    assert "Absences row 14" in monday["reason_detail"]
```

1f. The imports `REASON_DAY_ABSENT` / `REASON_DAY_WINDOW_TOO_NARROW`
(lines 7-10) become unused in this file after 1b/1c — delete that
import block.

- [ ] **Step 2: Run the debug-row tests to verify they fail**

Run: `python -m pytest tests/test_rows.py -k debug -v`
Expected: FAIL — the updated assertions see raw constants ("absent on this day", etc.) instead of sentences.

- [ ] **Step 3: Implement the sentence formatter in rows.py**

3a. Extend the per_day import (lines 7-10):

```python
from monthly_schedule.per_day import (
    compute_day_eligibility, OneOffConflict, REASON_DAY_ABSENT,
    REASON_DAY_NOT_ENROLLED, REASON_DAY_NO_AUTH,
    REASON_DAY_WRONG_WEEKDAY, REASON_DAY_WINDOW_TOO_NARROW,
)
```

3b. Under `DAY_ABBR` (line 15) add:

```python
DAY_NAME = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday",
            5: "Friday", 6: "Saturday", 7: "Sunday"}
```

3c. Add two module-level helpers above `build_debug_rows`:

```python
def _simple_reason(reason, day, authorized, absence, availability):
    """One plain-English sentence for the debug CSV `reason` column.

    `authorized` is the weekday set from the day's authorization (empty
    set when there is none), `absence` the Absences row covering the day
    (or None), `availability` the effective HH:MM-HH:MM window ('' when
    none applies)."""
    if reason == REASON_DAY_NOT_ENROLLED:
        return "Not enrolled at the center on this day"
    if reason == REASON_DAY_NO_AUTH:
        return "No authorization covers this day"
    if reason == REASON_DAY_WRONG_WEEKDAY:
        names = ", ".join(DAY_ABBR[d] for d in sorted(authorized))
        detail = (f"authorized: {names}" if names
                  else "no authorized days on file")
        return (f"{DAY_NAME[day.isoweekday()]} is not an authorized day "
                f"({detail})")
    if reason == REASON_DAY_ABSENT:
        leave = str(absence["leave_type"] or "").strip() if absence else ""
        return f"Marked absent ({leave})" if leave else "Marked absent"
    if reason == REASON_DAY_WINDOW_TOO_NARROW:
        if availability:
            return (f"Available time ({availability}) is too short "
                    "to fit a session")
        return "Available time is too short to fit a session"
    return reason


def _simple_conflict_reason(detail):
    """Plain-English sentence for a OneOffConflictDetail."""
    if detail.kind == "duplicate":
        return (f"{len(detail.one_offs)} conflicting one-off availability "
                "entries exist for this day")
    return ("A one-off availability entry conflicts with an absence "
            "on this day")
```

3d. In `build_debug_rows`, replace the try/except (lines 181-193). The
raw constant is kept in `raw_reason` because `_reason_detail` branches
on it; the CSV column gets the sentence. The conflict's detailed
sentence (with Access row IDs) moves to `reason_detail`:

```python
        conflict_detail = ""
        try:
            result = compute_day_eligibility(day, ctx, plan_rules)
            scheduled = result.eligible
            raw_reason = None if scheduled else (result.reason or "")
            reason = ("Scheduled" if scheduled
                      else _simple_reason(raw_reason, day, authorized,
                                          absence, availability))
            window = result.placement_window
            reserve = result.dropoff_reserve
            pickup_reserve = result.pickup_reserve
        except OneOffConflict as exc:
            scheduled = False
            raw_reason = ""
            reason = _simple_conflict_reason(exc.detail)
            conflict_detail = exc.reason
            window = None
            reserve = 0
            pickup_reserve = 0
```

3e. Just below, the `reason_detail` block (lines 202-215) changes in
two places — the default becomes `conflict_detail` and the
`_reason_detail` call receives `raw_reason` (not the sentence):

```python
        reason_detail = conflict_detail
        if window is not None:
            in_lo, out_hi = window
            placement = f"{format_minutes(in_lo)}-{format_minutes(out_hi)}"
            max_len = max(0, min(plan_rules["session_length_min"][1],
                                 out_hi - in_lo))
            max_length = format_minutes(max_len)
            reason_detail = _reason_detail(
                raw_reason, availability, reserve, in_lo, out_hi,
                plan_rules, avail_row, pickup_reserve,
            )
        else:
            placement = ""
            max_length = ""
```

3f. Update the `build_debug_rows` docstring: in the paragraph starting
"`scheduled` is True when..." replace the last two sentences with:

```
    `scheduled` is True when compute_day_eligibility accepted the day.
    `reason` is a plain-English sentence: "Scheduled" for accepted days,
    otherwise a one-line explanation of the rejection. A OneOffConflict
    is caught per-day — its simple sentence goes in `reason` and its
    detailed sentence (with the Access row IDs) in `reason_detail` — so
    the CSV always completes even when the schedule build itself fails.
```

- [ ] **Step 4: Run the rows tests to verify they pass**

Run: `python -m pytest tests/test_rows.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/rows.py tests/test_rows.py
git commit -m "feat(debug): plain-English reason sentences in debug CSV"
```

---

### Task 2: Full-month coverage

**Files:**
- Modify: `monthly_schedule/rows.py`
- Test: `tests/test_rows.py`, `tests/test_cli.py`

- [ ] **Step 1: Write/adjust the coverage tests**

1a. In `tests/test_rows.py`, replace
`test_debug_rows_only_authorized_weekdays` entirely with:

```python
def test_debug_rows_cover_every_day_of_month():
    # Every calendar day of May 2026 gets a row, weekends included.
    rows = build_debug_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES)
    assert len(rows) == 31
    # Authorized weekdays (Mon/Wed/Fri) are scheduled.
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["scheduled"] is True
    assert mon["reason"] == "Scheduled"
    # 2026-05-02 is a Saturday → plain sentence naming the day and the
    # authorized days.
    sat = next(r for r in rows if r["date"] == date(2026, 5, 2))
    assert sat["scheduled"] is False
    assert sat["reason"] == (
        "Saturday is not an authorized day (authorized: Mon, Wed, Fri)"
    )
    assert sat["auth_days"] == "1,3,5"


def test_debug_rows_no_auth_day_sentence():
    # Authorization ends 2026-05-15 → later days have no authorization.
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 5, 15),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 5, 15),
                         "auth_days": "1,3,5"}],
        absences=[], availabilities=[], one_offs=[],
    )
    rows = build_debug_rows(2026, 5, ctx, PLAN_RULES)
    assert len(rows) == 31
    # 2026-05-18 is a Monday after the authorization ended.
    mon = next(r for r in rows if r["date"] == date(2026, 5, 18))
    assert mon["scheduled"] is False
    assert mon["reason"] == "No authorization covers this day"
    assert mon["auth_days"] == ""


def test_debug_rows_not_enrolled_day_sentence():
    # Enrollment starts mid-month → earlier days are not enrolled.
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 5, 15), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[], availabilities=[], one_offs=[],
    )
    rows = build_debug_rows(2026, 5, ctx, PLAN_RULES)
    # 2026-05-04 is a Monday before enrollment started.
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["scheduled"] is False
    assert mon["reason"] == "Not enrolled at the center on this day"
```

1b. In `tests/test_cli.py`, `test_debug_flag_writes_per_member_debug_csvs`
(~line 731) — the CSV now has one row per calendar day:

```python
        # Every calendar day of May 2026 gets a row.
        assert len(lines) - 1 == 31
```

1c. In `tests/test_cli.py`, three tests index `rows[0]`, which is now
May 1 (a Friday, not authorized under `auth_days: "1"`) instead of the
first Monday. Point them at the first Monday (2026-05-04) instead:

- `test_collect_debug_rows_uses_travel_adjusted_offsets` (~line 796):

```python
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    # travel 25 + buffer max 5 + drift max 2 = 32 min reserve
    # → out_hi = 15:00 - 32m = 14:28 (default rules, flag on).
    assert mon["placement_window"] == "08:00-14:28"
    assert mon["reason_detail"] == (
        "drop-off reserve 32m before 15:00 avail end"
    )
```

- `test_collect_debug_rows_without_cache_uses_defaults` (~line 831):

```python
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    # Default offsets: drift max 2 + dropoff trail max 12 = 14 min.
    assert mon["placement_window"] == "08:00-14:46"
```

- `test_collect_debug_rows_marks_rows_when_travel_unresolved`
  (~line 866):

```python
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["placement_window"] == "08:00-14:46"
    assert mon["reason_detail"] == (
        "drop-off reserve 14m before 15:00 avail end; "
        "travel unresolved - default offsets shown"
    )
    # Rows without their own detail still get the stamp.
    assert rows[0]["reason_detail"] == (
        "travel unresolved - default offsets shown"
    )
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python -m pytest tests/test_rows.py -k debug tests/test_cli.py -k debug -v`
Expected: FAIL — row counts are still authorized-days-only (13/17), no rows exist for Saturdays / no-auth / pre-enrollment days.

- [ ] **Step 3: Remove the authorized-day skips**

In `monthly_schedule/rows.py`, `build_debug_rows`:

3a. Replace the loop head (lines 157-163):

```python
    for day in get_month_dates(year, month, start_day, end_day):
        auth = ctx.active_authorization(day)
        authorized = (get_authorized_weekdays(auth["auth_days"])
                      if auth else set())
```

(`format_auth_days(authorized)` in the row dict already renders the
empty set as `""`.)

3b. Replace the first docstring paragraph pair (lines 131-136):

```
    """Diagnostic rows for the debug CSV (one per calendar day).

    Every day of the requested range (defaults to the full month,
    weekends included) gets a row, so the CSV explains the whole month:
    days outside the authorization, wrong weekdays, and non-enrolled
    days each carry their plain-English rejection sentence. On days
    with no active authorization the `auth_days` column is ''.
```

(keep the rest of the docstring from "Each row is {date, ...}" onward,
as edited in Task 1.)

- [ ] **Step 4: Run rows + cli tests to verify they pass**

Run: `python -m pytest tests/test_rows.py tests/test_cli.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/rows.py tests/test_rows.py tests/test_cli.py
git commit -m "feat(debug): debug CSV covers every day of the month"
```

---

### Task 3: Docs + full-suite verification

**Files:**
- Modify: `docs/scheduling-flow.md:170-181`

- [ ] **Step 1: Update the debug paragraph in docs/scheduling-flow.md**

Replace the paragraph at lines 170-181 ("If you turn on the **Debug**
checkbox...") with:

```markdown
If you turn on the **Debug** checkbox in the GUI, every day of the
selected month (weekends included) gets a row in
`Debug_<center_id>_<YYYY-MM>.csv`. The `reason` column is a
plain-English sentence — `Scheduled`, or why not (e.g. "Saturday is not
an authorized day (authorized: Mon, Wed, Fri)", "Marked absent
(Vacation)", "Available time (08:00-11:00) is too short to fit a
session"). The technical columns follow for troubleshooting: a
`reason_detail` column with the arithmetic behind window rejections
(availability, drop-off reserve, usable width vs. required minimum) —
or, for one-off conflicts, the exact Access rows that disagree — along
with the availability used, absence/leave type, authorized weekdays,
the placement window, and the maximum session length that fit. A `band`
column carries the member's `morning`/`afternoon` assignment on every
row when the distribution feature is on (blank otherwise); it reflects
the member's current band, not necessarily where an already-cached
day's time actually landed.
```

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest`
Expected: all PASS. If anything outside test_rows/test_cli fails on the new reason text or row counts, fix the expectation to match the spec's sentences.

- [ ] **Step 3: Commit**

```bash
git add docs/scheduling-flow.md
git commit -m "docs: debug CSV spans the whole month with plain reasons"
```
