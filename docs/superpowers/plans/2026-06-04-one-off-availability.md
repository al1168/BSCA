# One-off availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `OneOffAvailability` Access table and the read/write/scheduler code paths so staff can record single-day exceptions to a member's recurring availability (e.g. doctor appointment 8–12 → schedule the visit 12–16 on that day) and have the scheduler honor them, while flagging duplicate-row and absence collisions to a dated CSV.

**Architecture:** New table parallels the existing `Availability` table but is keyed by a single `date` column instead of `Day Of Week` + effective range. The eligibility pipeline (`compute_day_eligibility`) keeps enrollment / authorization / weekday as hard silent gates; only after they pass does it consult one-offs. Two conflict checks (duplicate rows; absence on the same date) raise a new `OneOffConflict` exception which the per-member runner catches and accumulates into a `one_off_conflicts_<YYYY-MM-DD>.csv` written next to the workbook output.

**Tech Stack:** Python 3.11, pyodbc (Microsoft Access ODBC driver), pytest, PyQt6 (GUI worker).

**Spec:** [docs/superpowers/specs/2026-06-04-one-off-availability-design.md](../specs/2026-06-04-one-off-availability-design.md)

---

## File Structure

### Files to create

- `scripts/add_one_off_availability_table.py` — idempotent migration that adds just the new table to an existing `.accdb`.

### Files to modify

| File | Responsibility |
| --- | --- |
| `monthly_schedule/per_day.py` | New `OneOffConflict` exception. New one-off branch in `compute_day_eligibility` between the weekday gate and the absence/availability path. |
| `monthly_schedule/db.py` | New `ONE_OFFS_QUERY`, `ALL_ONE_OFFS_QUERY`, `map_one_off_row`, `get_one_offs`, `get_all_one_offs` (mirrors the existing `availability` pattern). |
| `monthly_schedule/eligibility_context.py` | `MemberContext` gains a `one_offs` constructor argument and an `one_offs_for(day)` method. |
| `new_monthly_schedule.py` | Fetch one-offs and pass to `MemberContext`. Extend the `Failure` namedtuple with a `day` field. Catch `OneOffConflict` inside `process_member` and emit a `one_off_conflict` Failure carrying the conflict date. Main loop writes `one_off_conflicts_<DATE>.csv` after the run if any conflict failures exist. |
| `gui/worker.py` | Add the eager-fetch for one-offs, pass to `MemberContext`, the same `OneOffConflict` handling, and CSV write. |
| `scripts/create_supporting_tables.py` | Add `_CREATE_ONE_OFF_AVAILABILITY` constant and append to `_DDLS`. |
| `scripts/make_test_db.py` | Truncate the new table in `SUPPORTING_TABLES`. Add `_seed_one_off_conflict_scenario` and register it in the scenario map. |
| `scripts/README.md` | List the new migration script and mention `OneOffAvailability` in the migration steps. |
| `tests/test_per_day.py` | Add tests for the one-off branch: valid one-off narrows window, two conflict reasons, first-match-wins ordering, silent-skip cases. |
| `tests/test_eligibility_context.py` | Add tests for `one_offs_for`. Update existing test helpers to pass `[]` for the new `one_offs` constructor arg. |
| `tests/test_rows.py` | Update existing test helpers to pass `[]` for the new `one_offs` constructor arg. |
| `tests/test_smoke.py` | Add an end-to-end test that drives the `one_off_conflict` test-DB scenario and asserts the conflict CSV is written. |

---

## Phase 1: Exception type and MemberContext extension

### Task 1: Add `OneOffConflict` exception

**Files:**
- Modify: `monthly_schedule/per_day.py`
- Test: `tests/test_per_day.py`

- [ ] **Step 1.1: Write the failing test**

Append to `tests/test_per_day.py`:

```python
def test_one_off_conflict_exception_carries_fields():
    from datetime import date
    from monthly_schedule.per_day import OneOffConflict
    exc = OneOffConflict(123, date(2026, 6, 5), "duplicate one-off rows for 2026-06-05")
    assert exc.center_id == 123
    assert exc.day == date(2026, 6, 5)
    assert exc.reason == "duplicate one-off rows for 2026-06-05"
    assert "123" in str(exc)
    assert "2026-06-05" in str(exc)
    assert "duplicate" in str(exc)
```

- [ ] **Step 1.2: Run the test and confirm it fails**

```
.venv\Scripts\python.exe -m pytest tests/test_per_day.py::test_one_off_conflict_exception_carries_fields -v
```
Expected: `ImportError` / `AttributeError` — `OneOffConflict` does not exist.

- [ ] **Step 1.3: Add the exception in `monthly_schedule/per_day.py`**

Add this class definition just below the existing `REASON_*` constants (around line 16, before `@dataclass` for `DayEligibility`):

```python
class OneOffConflict(Exception):
    """Raised by compute_day_eligibility when a one-off availability row
    exists for a day but conflicts with an absence or a duplicate one-off
    row. The per-member runner catches this to write the conflict CSV."""

    def __init__(self, center_id, day, reason):
        self.center_id = center_id
        self.day = day
        self.reason = reason
        super().__init__(f"{center_id} {day}: {reason}")
```

- [ ] **Step 1.4: Run the test and confirm it passes**

```
.venv\Scripts\python.exe -m pytest tests/test_per_day.py::test_one_off_conflict_exception_carries_fields -v
```
Expected: PASS.

- [ ] **Step 1.5: Commit**

```bash
git add monthly_schedule/per_day.py tests/test_per_day.py
git commit -m "feat(per_day): add OneOffConflict exception"
```

---

### Task 2: Extend `MemberContext` with `one_offs` and `one_offs_for`

**Files:**
- Modify: `monthly_schedule/eligibility_context.py`
- Test: `tests/test_eligibility_context.py`

- [ ] **Step 2.1: Write the failing test**

Append to `tests/test_eligibility_context.py`:

```python
def test_one_offs_for_returns_matching_rows():
    from datetime import date
    from monthly_schedule.eligibility_context import MemberContext

    rows = [
        {"id": 1, "center_id": 1, "date": date(2026, 6, 5),
         "avail_start": "12:00", "avail_end": "16:00"},
        {"id": 2, "center_id": 1, "date": date(2026, 6, 6),
         "avail_start": "09:00", "avail_end": "11:00"},
    ]
    ctx = MemberContext(
        enrollments=[], authorizations=[], absences=[],
        availabilities=[], one_offs=rows,
    )
    assert ctx.one_offs_for(date(2026, 6, 5)) == [rows[0]]
    assert ctx.one_offs_for(date(2026, 6, 6)) == [rows[1]]
    assert ctx.one_offs_for(date(2026, 6, 7)) == []


def test_one_offs_for_returns_all_duplicates():
    from datetime import date
    from monthly_schedule.eligibility_context import MemberContext

    rows = [
        {"id": 1, "center_id": 1, "date": date(2026, 6, 5),
         "avail_start": "12:00", "avail_end": "16:00"},
        {"id": 2, "center_id": 1, "date": date(2026, 6, 5),
         "avail_start": "13:00", "avail_end": "15:00"},
    ]
    ctx = MemberContext(
        enrollments=[], authorizations=[], absences=[],
        availabilities=[], one_offs=rows,
    )
    out = ctx.one_offs_for(date(2026, 6, 5))
    assert len(out) == 2
    assert {r["id"] for r in out} == {1, 2}


def test_one_offs_defaults_to_empty_list_when_none_passed():
    from monthly_schedule.eligibility_context import MemberContext
    ctx = MemberContext(
        enrollments=[], authorizations=[], absences=[],
        availabilities=[], one_offs=[],
    )
    from datetime import date
    assert ctx.one_offs_for(date(2026, 6, 5)) == []
```

- [ ] **Step 2.2: Run the tests and confirm they fail**

```
.venv\Scripts\python.exe -m pytest tests/test_eligibility_context.py -v -k one_off
```
Expected: `TypeError: __init__() got an unexpected keyword argument 'one_offs'` or similar.

- [ ] **Step 2.3: Update `MemberContext.__init__` and add `one_offs_for`**

Edit `monthly_schedule/eligibility_context.py`. Change the constructor signature and add the new attribute and method:

```python
class MemberContext:
    def __init__(self, enrollments, authorizations, absences,
                 availabilities, one_offs):
        self._enrollments = list(enrollments)
        self._authorizations = list(authorizations)
        self._absences = list(absences)
        self._availabilities = list(availabilities)
        self._one_offs = list(one_offs)

    # ... existing methods unchanged ...

    def one_offs_for(self, day):
        """Return list of one-off rows whose date equals `day`.

        Empty list if none. May contain more than one row — the caller
        (compute_day_eligibility) flags the duplicate as a conflict."""
        return [r for r in self._one_offs if r["date"] == day]
```

The argument is **required, not defaulted**, so every existing call site is forced to pass it (Task 3 below). Defaults hide breakage.

- [ ] **Step 2.4: Run the new tests and confirm they pass**

```
.venv\Scripts\python.exe -m pytest tests/test_eligibility_context.py -v -k one_off
```
Expected: 3 PASS.

- [ ] **Step 2.5: Existing tests now fail because they don't pass `one_offs` — fix them**

Run the full file to see which existing tests broke:

```
.venv\Scripts\python.exe -m pytest tests/test_eligibility_context.py -v
```

For each failing test that constructs a `MemberContext`, add `one_offs=[]` to the call. Example before:

```python
ctx = MemberContext(
    enrollments=[...], authorizations=[...],
    absences=[], availabilities=[],
)
```

After:

```python
ctx = MemberContext(
    enrollments=[...], authorizations=[...],
    absences=[], availabilities=[], one_offs=[],
)
```

Apply the same change to every `MemberContext(...)` call in `tests/test_eligibility_context.py`.

- [ ] **Step 2.6: Run the full file and confirm everything passes**

```
.venv\Scripts\python.exe -m pytest tests/test_eligibility_context.py -v
```
Expected: ALL PASS.

- [ ] **Step 2.7: Commit**

```bash
git add monthly_schedule/eligibility_context.py tests/test_eligibility_context.py
git commit -m "feat(member_context): add one_offs argument and one_offs_for lookup"
```

---

### Task 3: Update existing `MemberContext` callers in `tests/test_per_day.py`, `tests/test_rows.py`, `new_monthly_schedule.py`, `gui/worker.py`

The constructor signature changed in Task 2; the rest of the codebase still passes 4 args.

**Files:**
- Modify: `tests/test_per_day.py`
- Modify: `tests/test_rows.py`
- Modify: `new_monthly_schedule.py`
- Modify: `gui/worker.py`

- [ ] **Step 3.1: Run the full test suite to enumerate breakage**

```
.venv\Scripts\python.exe -m pytest -v
```
Expected: failures in any test that builds a `MemberContext`. Note the file/line list.

- [ ] **Step 3.2: Fix `tests/test_per_day.py`**

Edit the `_ctx()` helper around line 38:

```python
    availabilities = [availability] if availability else []
    return MemberContext(enrollments, authorizations, absences, availabilities, [])
```

Edit the `test_month_failure_partial_absence_is_not_whole_month` test around line 133 — add `one_offs=[]` to that `MemberContext(...)` call too.

- [ ] **Step 3.3: Fix `tests/test_rows.py`**

For each `MemberContext(...)` call in this file (lines 21, 64, 89 per the codebase grep), add `one_offs=[]` (or `[]` as the 5th positional arg, matching the file's existing style).

- [ ] **Step 3.4: Fix `new_monthly_schedule.py` (line 214)**

```python
        ctx = MemberContext(
            enrollments=get_enrollments(member["center_id"], args.db_path),
            authorizations=get_authorizations(member["center_id"], args.db_path),
            absences=get_absences(member["center_id"], args.db_path),
            availabilities=get_availability(member["center_id"], args.db_path),
            one_offs=[],   # populated in Task 7 once get_one_offs exists
        )
```

The temporary `one_offs=[]` is intentional: this task only restores the build. Task 7 wires the real fetcher.

- [ ] **Step 3.5: Fix `gui/worker.py` (line 156)**

```python
                ctx = MemberContext(
                    enrollments=enroll_idx.get(cid, []),
                    authorizations=auth_idx.get(cid, []),
                    absences=absence_idx.get(cid, []),
                    availabilities=avail_idx.get(cid, []),
                    one_offs=[],
                )
```

Same intent: real wiring comes in Task 8.

- [ ] **Step 3.6: Run the full test suite and confirm everything passes**

```
.venv\Scripts\python.exe -m pytest -v
```
Expected: ALL PASS (excluding any pre-existing skipped tests).

- [ ] **Step 3.7: Commit**

```bash
git add tests/test_per_day.py tests/test_rows.py new_monthly_schedule.py gui/worker.py
git commit -m "refactor: pass empty one_offs to existing MemberContext callers"
```

---

## Phase 2: Scheduler integration (the core feature)

### Task 4: Valid one-off narrows the arrival window

This is the happy path. We start here because it locks in where the new branch sits in `compute_day_eligibility`.

**Files:**
- Modify: `monthly_schedule/per_day.py`
- Test: `tests/test_per_day.py`

- [ ] **Step 4.1: Extend the `_ctx()` helper in `tests/test_per_day.py` to accept `one_offs`**

Replace the existing helper:

```python
def _ctx(enrolled=True, authorized="1,3,5", absent=False,
        availability=None, one_offs=None):
    enrollments = (
        [{"id": 1, "center_id": 1,
          "start_date": date(2026, 1, 1), "end_date": None}]
        if enrolled else []
    )
    authorizations = (
        [{"id": 1, "center_id": 1,
          "auth_start": date(2026, 1, 1), "auth_end": date(2026, 12, 31),
          "effective_start": date(2026, 1, 1),
          "effective_end": date(2026, 12, 31),
          "auth_days": authorized}]
        if authorized else []
    )
    absences = (
        [{"id": 1, "center_id": 1, "leave_type": "Vacation",
          "start_date": date(2026, 5, 1),
          "end_date": date(2026, 5, 31)}]
        if absent else []
    )
    availabilities = [availability] if availability else []
    return MemberContext(
        enrollments, authorizations, absences, availabilities,
        list(one_offs or []),
    )
```

- [ ] **Step 4.2: Write the failing test**

Append to `tests/test_per_day.py`:

```python
def test_one_off_narrows_window_and_ignores_recurring_availability():
    # Plan default arrival 08:00-11:00, session_span_min lower bound 210.
    # Recurring availability (Mon 10:00-15:00) would narrow to (600, 660).
    # A one-off for the same Monday says 12:00-16:00.
    # The one-off must win and the recurring rule must be IGNORED.
    # Intersect (12:00-16:00) with plan (08:00-11:00) - session lower 210:
    #   lo = max(480, 720) = 720
    #   hi = min(660, 960 - 210) = min(660, 750) = 660
    # lo > hi → ineligible (silent skip — non-intersecting), no flag.
    avail = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": None,
             "day_of_week": 1,
             "avail_start": "10:00", "avail_end": "15:00"}
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "12:00", "avail_end": "16:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4),
        _ctx(availability=avail, one_offs=[one_off]),
        PLAN_RULES,
    )
    # No flag, no raise; just silent skip (non-intersecting window).
    assert result.eligible is False


def test_one_off_inside_plan_window_narrows_arrival():
    # Plan default arrival 08:00-11:00 = (480, 660).
    # session_span_min lower bound is 210.
    # One-off says 09:00-14:00.
    # Recurring rule does NOT apply (Mon 12:00-13:00 would on its own
    # be ineligible). The one-off must replace it entirely.
    #   lo = max(480 [08:00], 540 [09:00]) = 540
    #   hi = min(660 [11:00], 840 [14:00] - 210) = min(660, 630) = 630
    # Arrival window: (540, 630).
    narrow_recurring = {"id": 1, "center_id": 1,
                        "effective_start_date": date(2026, 1, 1),
                        "effective_end_date": None,
                        "day_of_week": 1,
                        "avail_start": "12:00", "avail_end": "13:00"}
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "09:00", "avail_end": "14:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4),
        _ctx(availability=narrow_recurring, one_offs=[one_off]),
        PLAN_RULES,
    )
    assert result.eligible is True
    assert result.arrival_window == (540, 630)
```

- [ ] **Step 4.3: Run the tests and confirm they fail**

```
.venv\Scripts\python.exe -m pytest tests/test_per_day.py::test_one_off_inside_plan_window_narrows_arrival -v
```
Expected: FAIL — the existing logic returns the recurring-rule narrowing, not the one-off.

- [ ] **Step 4.4: Modify `compute_day_eligibility` in `monthly_schedule/per_day.py`**

Replace the body of `compute_day_eligibility` so the one-off lookup runs after the weekday gate but before the absence/availability path:

```python
def compute_day_eligibility(day: date, ctx, plan_rules) -> DayEligibility:
    """Run the ordered eligibility checks for one calendar day."""
    if not ctx.is_enrolled(day):
        return DayEligibility(eligible=False)

    auth = ctx.active_authorization(day)
    if auth is None:
        return DayEligibility(eligible=False)

    authorized = get_authorized_weekdays(auth["auth_days"])
    if day.isoweekday() not in authorized:
        return DayEligibility(eligible=False)

    one_offs = ctx.one_offs_for(day)
    if one_offs:
        if len(one_offs) > 1:
            raise OneOffConflict(
                ctx_center_id(ctx, one_offs),
                day,
                f"duplicate one-off rows for {day.isoformat()}",
            )
        if ctx.is_absent(day):
            raise OneOffConflict(
                one_offs[0]["center_id"],
                day,
                f"one-off on {day.isoformat()} conflicts with absence",
            )
        avail = one_offs[0]
    else:
        if ctx.is_absent(day):
            return DayEligibility(eligible=False)
        avail = ctx.availability_for(day)
        if avail is None:
            return DayEligibility(eligible=True)

    plan_lo = parse_hhmm(plan_rules["arrival_window"][0])
    plan_hi = parse_hhmm(plan_rules["arrival_window"][1])
    avail_lo = parse_hhmm(avail["avail_start"])
    avail_hi = parse_hhmm(avail["avail_end"])
    session_min_lower = plan_rules["session_span_min"][0]

    lo = max(plan_lo, avail_lo)
    hi = min(plan_hi, avail_hi - session_min_lower)
    if lo > hi:
        return DayEligibility(eligible=False)
    return DayEligibility(eligible=True, arrival_window=(lo, hi))
```

Add the helper next to it (or inline — see below). The simplest inline form: pull `center_id` from `one_offs[0]` (always non-empty in the duplicate branch by construction). So drop the helper and use `one_offs[0]["center_id"]` in both raise sites:

```python
    one_offs = ctx.one_offs_for(day)
    if one_offs:
        center_id = one_offs[0]["center_id"]
        if len(one_offs) > 1:
            raise OneOffConflict(
                center_id, day,
                f"duplicate one-off rows for {day.isoformat()}",
            )
        if ctx.is_absent(day):
            raise OneOffConflict(
                center_id, day,
                f"one-off on {day.isoformat()} conflicts with absence",
            )
        avail = one_offs[0]
    else:
        if ctx.is_absent(day):
            return DayEligibility(eligible=False)
        avail = ctx.availability_for(day)
        if avail is None:
            return DayEligibility(eligible=True)
```

Use the inline form. Delete the `ctx_center_id(...)` helper if you typed it.

- [ ] **Step 4.5: Run the two new tests and confirm they pass**

```
.venv\Scripts\python.exe -m pytest tests/test_per_day.py -v -k one_off
```
Expected: PASS for both `test_one_off_narrows_window_and_ignores_recurring_availability` and `test_one_off_inside_plan_window_narrows_arrival`. (Earlier `test_one_off_conflict_exception_carries_fields` also passes.)

- [ ] **Step 4.6: Run the full test file to confirm no regression**

```
.venv\Scripts\python.exe -m pytest tests/test_per_day.py -v
```
Expected: ALL PASS.

- [ ] **Step 4.7: Commit**

```bash
git add monthly_schedule/per_day.py tests/test_per_day.py
git commit -m "feat(per_day): one-off availability replaces recurring rule for matched day"
```

---

### Task 5: Two conflict checks + first-match-wins ordering

**Files:**
- Test: `tests/test_per_day.py`

The implementation already exists from Task 4. This task only adds tests to lock the behavior.

- [ ] **Step 5.1: Write the conflict tests**

Append to `tests/test_per_day.py`:

```python
def test_duplicate_one_off_rows_raise_conflict():
    from monthly_schedule.per_day import OneOffConflict
    one_offs = [
        {"id": 1, "center_id": 1, "date": date(2026, 5, 4),
         "avail_start": "09:00", "avail_end": "12:00"},
        {"id": 2, "center_id": 1, "date": date(2026, 5, 4),
         "avail_start": "10:00", "avail_end": "13:00"},
    ]
    import pytest
    with pytest.raises(OneOffConflict) as info:
        compute_day_eligibility(
            date(2026, 5, 4), _ctx(one_offs=one_offs), PLAN_RULES
        )
    assert info.value.center_id == 1
    assert info.value.day == date(2026, 5, 4)
    assert info.value.reason == "duplicate one-off rows for 2026-05-04"


def test_one_off_with_absence_raises_conflict():
    from monthly_schedule.per_day import OneOffConflict
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "09:00", "avail_end": "12:00"}
    import pytest
    with pytest.raises(OneOffConflict) as info:
        # `absent=True` covers the entire month of May 2026.
        compute_day_eligibility(
            date(2026, 5, 4),
            _ctx(absent=True, one_offs=[one_off]),
            PLAN_RULES,
        )
    assert info.value.reason == "one-off on 2026-05-04 conflicts with absence"


def test_duplicate_one_off_beats_absence_conflict():
    # Two one-offs AND an absence: first-match wins; duplicate is checked first.
    from monthly_schedule.per_day import OneOffConflict
    one_offs = [
        {"id": 1, "center_id": 1, "date": date(2026, 5, 4),
         "avail_start": "09:00", "avail_end": "12:00"},
        {"id": 2, "center_id": 1, "date": date(2026, 5, 4),
         "avail_start": "10:00", "avail_end": "13:00"},
    ]
    import pytest
    with pytest.raises(OneOffConflict) as info:
        compute_day_eligibility(
            date(2026, 5, 4),
            _ctx(absent=True, one_offs=one_offs),
            PLAN_RULES,
        )
    assert "duplicate" in info.value.reason
```

- [ ] **Step 5.2: Run the conflict tests**

```
.venv\Scripts\python.exe -m pytest tests/test_per_day.py -v -k "conflict or duplicate"
```
Expected: ALL PASS.

- [ ] **Step 5.3: Commit**

```bash
git add tests/test_per_day.py
git commit -m "test(per_day): cover OneOffConflict reasons and first-match-wins ordering"
```

---

### Task 6: Silent-skip cases (regression tests)

**Files:**
- Test: `tests/test_per_day.py`

- [ ] **Step 6.1: Write the silent-skip tests**

Append to `tests/test_per_day.py`:

```python
def test_one_off_on_unenrolled_day_silently_skipped():
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "12:00", "avail_end": "14:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4),
        _ctx(enrolled=False, one_offs=[one_off]),
        PLAN_RULES,
    )
    assert result.eligible is False  # silent — no raise


def test_one_off_with_no_active_auth_silently_skipped():
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "12:00", "avail_end": "14:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4),
        _ctx(authorized=None, one_offs=[one_off]),
        PLAN_RULES,
    )
    assert result.eligible is False


def test_one_off_on_unauthorized_weekday_silently_skipped():
    # 2026-05-05 is Tuesday (weekday 2); _ctx default auth_days "1,3,5"
    # excludes it. A one-off must not override the weekday gate.
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 5),
               "avail_start": "12:00", "avail_end": "14:00"}
    result = compute_day_eligibility(
        date(2026, 5, 5),
        _ctx(one_offs=[one_off]),
        PLAN_RULES,
    )
    assert result.eligible is False


def test_one_off_window_outside_plan_silently_skipped():
    # Plan arrival 08:00-11:00, session_min_lower 210.
    # One-off window 14:00-17:00 cannot intersect → silent skip, no raise.
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "14:00", "avail_end": "17:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4),
        _ctx(one_offs=[one_off]),
        PLAN_RULES,
    )
    assert result.eligible is False
```

- [ ] **Step 6.2: Run the silent-skip tests**

```
.venv\Scripts\python.exe -m pytest tests/test_per_day.py -v -k silent
```
Expected: ALL PASS (the existing implementation already supports this; these are guard-rails against future regressions).

- [ ] **Step 6.3: Commit**

```bash
git add tests/test_per_day.py
git commit -m "test(per_day): lock silent-skip behavior for non-conflict one-off cases"
```

---

## Phase 3: Database layer

### Task 7: Add ODBC fetchers `get_one_offs` and `get_all_one_offs`

**Files:**
- Modify: `monthly_schedule/db.py`

These are thin wrappers around existing helpers (`_fetch_all`, `_fetch_all_unfiltered`, `_index_by_center_id`). They cannot be unit-tested without ODBC, so we verify by import-and-smoke instead. The end-to-end test in Task 14 actually exercises them.

- [ ] **Step 7.1: Add the query constants, mapper, and fetchers to `monthly_schedule/db.py`**

Insert just after the `ALL_AVAILABILITY_QUERY` / `get_all_availability` block (around line 313, before the `_index_by_center_id` helper):

```python
ONE_OFFS_QUERY = (
    "SELECT [ID], [Center ID], [date], [avail_start], [avail_end] "
    "FROM [OneOffAvailability] "
    "WHERE [Center ID] = ?"
)


def map_one_off_row(row):
    """Map a raw OneOffAvailability row. `date` is stored as DATETIME
    in Access; the mapper truncates to date. `avail_start`/`avail_end`
    are stored as the 1899-12-30 placeholder DATETIME and extracted as
    'HH:MM' (same convention as Availability)."""
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "date": _to_date(row[2]),
        "avail_start": _datetime_to_hhmm(row[3]),
        "avail_end": _datetime_to_hhmm(row[4]),
    }


def get_one_offs(center_id, db_path):
    """Return all OneOffAvailability rows for `center_id` as a list of dicts."""
    return _fetch_all(ONE_OFFS_QUERY, center_id, db_path, map_one_off_row)


ALL_ONE_OFFS_QUERY = (
    "SELECT [ID], [Center ID], [date], [avail_start], [avail_end] "
    "FROM [OneOffAvailability]"
)


def get_all_one_offs(db_path):
    """Return {center_id: [one_off dicts]} for every OneOffAvailability
    row. One ODBC round-trip vs N when used by the batch worker modes."""
    rows = _fetch_all_unfiltered(ALL_ONE_OFFS_QUERY, db_path, map_one_off_row)
    return _index_by_center_id(rows)
```

- [ ] **Step 7.2: Smoke-test the import**

```
.venv\Scripts\python.exe -c "from monthly_schedule.db import get_one_offs, get_all_one_offs, map_one_off_row, ONE_OFFS_QUERY, ALL_ONE_OFFS_QUERY; print('ok')"
```
Expected: `ok`.

- [ ] **Step 7.3: Smoke-test the mapper with a fake row**

```
.venv\Scripts\python.exe -c "from monthly_schedule.db import map_one_off_row; import datetime as d; print(map_one_off_row((7, 123.0, d.datetime(2026, 6, 5), d.datetime(1899, 12, 30, 12, 0), d.datetime(1899, 12, 30, 16, 0))))"
```
Expected: `{'id': 7, 'center_id': 123, 'date': datetime.date(2026, 6, 5), 'avail_start': '12:00', 'avail_end': '16:00'}`.

- [ ] **Step 7.4: Commit**

```bash
git add monthly_schedule/db.py
git commit -m "feat(db): get_one_offs / get_all_one_offs fetchers"
```

---

## Phase 4: Runner integration (CLI + GUI) and CSV output

### Task 8: Wire one-off fetcher and conflict CSV into the CLI runner

**Files:**
- Modify: `new_monthly_schedule.py`

- [ ] **Step 8.1: Update imports**

In `new_monthly_schedule.py`, extend the `from monthly_schedule.db import (...)` block to include `get_one_offs`:

```python
from monthly_schedule.db import (
    get_member, get_members_by_plan,
    get_enrollments, get_authorizations, get_absences, get_availability,
    get_one_offs,
)
```

And add to the `monthly_schedule.per_day` import:

```python
from monthly_schedule.per_day import compute_month_failure, OneOffConflict
```

- [ ] **Step 8.2: Extend the `Failure` namedtuple with a `day` field**

Replace line 61:

```python
Failure = namedtuple("Failure", "center_id name stage reason day")
```

- [ ] **Step 8.3: Patch every `Failure(...)` construction in `new_monthly_schedule.py` to pass `day=None`**

There are two existing call sites:

Around line 186 (`REASON_NOT_FOUND` branch):

```python
                    failures.append(
                        Failure(cid, "", "lookup", REASON_NOT_FOUND, None)
                    )
```

Around line 228 (per-member failure branch):

```python
                failures.append(
                    Failure(
                        member["center_id"],
                        f"{member['last_name']}, {member['first_name']}",
                        stage, reason, None,
                    )
                )
```

- [ ] **Step 8.4: Wire `get_one_offs` into the per-member context (line 214)**

Replace the `ctx = MemberContext(...)` block:

```python
        ctx = MemberContext(
            enrollments=get_enrollments(member["center_id"], args.db_path),
            authorizations=get_authorizations(member["center_id"], args.db_path),
            absences=get_absences(member["center_id"], args.db_path),
            availabilities=get_availability(member["center_id"], args.db_path),
            one_offs=get_one_offs(member["center_id"], args.db_path),
        )
```

- [ ] **Step 8.5: Catch `OneOffConflict` inside `process_member`**

Replace the `try: ... rows = build_rows(...) except Exception` block in `process_member` (around line 122-131). We need a *specific* catch for `OneOffConflict` so we can extract `exc.day` for the CSV, **before** the broad catch:

```python
    rng = random.Random()
    try:
        rules = dict(get_rules_for_plan(member["health_plan"]))
        buf_lo, buf_hi = rules.get("travel_buffer_min", (5, 15))
        rules["pickup_lead_min"] = (travel_minutes + buf_lo,
                                    travel_minutes + buf_hi)
        rules["dropoff_trail_min"] = (travel_minutes + buf_lo,
                                      travel_minutes + buf_hi)
        rows = build_rows(year, month, ctx, rules, rng)
    except OneOffConflict as exc:
        return (False, "one_off_conflict", exc.reason, exc.day)
    except Exception as exc:  # reported in the run summary
        return (False, "generate", f"{type(exc).__name__} — {exc}", None)
```

The return signature for `process_member` now has 4 elements on failure: `(ok, stage, reason, day)`. Update the two success returns and the early-return failures too:

- Line 113-114 — `compute_month_failure` branch:

```python
    failure = compute_month_failure(year, month, ctx)
    if failure is not None:
        return (False, "eligibility", failure, None)
```

- Line 118-119 — `TravelError` branch:

```python
    try:
        travel_minutes = resolve_travel_minutes(member, api_key, cache)
    except TravelError as exc:
        return (False, exc.stage, exc.reason, None)
```

- Line 140 — preview success:

```python
        return (True, None, None, None)
```

- Line 148 — `build_workbook` failure:

```python
    try:
        build_workbook(member, rows, path)
    except Exception as exc:  # reported in the run summary
        return (False, "write", f"{type(exc).__name__} — {exc}", None)
    print(f"Wrote {path}")
    return (True, None, None, None)
```

- [ ] **Step 8.6: Unpack the new 4-tuple in `main()` (around line 220)**

Replace:

```python
        ok, stage, reason = process_member(
            member, ctx, args.year, args.month, out_dir,
            args.preview_data, api_key, cache,
        )
        if ok:
            success += 1
        else:
            failures.append(
                Failure(
                    member["center_id"],
                    f"{member['last_name']}, {member['first_name']}",
                    stage, reason,
                )
            )
```

with:

```python
        ok, stage, reason, day = process_member(
            member, ctx, args.year, args.month, out_dir,
            args.preview_data, api_key, cache,
        )
        if ok:
            success += 1
        else:
            failures.append(
                Failure(
                    member["center_id"],
                    f"{member['last_name']}, {member['first_name']}",
                    stage, reason, day,
                )
            )
```

- [ ] **Step 8.7: Add a CSV writer for one-off conflicts**

Add a top-level function `write_one_off_conflict_csv` near `format_summary`:

```python
import csv
from datetime import date as _date


def write_one_off_conflict_csv(failures, out_dir, today=None):
    """If any failures carry stage='one_off_conflict', write
    `one_off_conflicts_<YYYY-MM-DD>.csv` into `out_dir` with one row
    per conflict. Return the path written, or None when there are no
    conflict failures (the file is not created in that case)."""
    conflict_failures = [f for f in failures if f.stage == "one_off_conflict"]
    if not conflict_failures:
        return None
    today = today or _date.today()
    path = os.path.join(out_dir, f"one_off_conflicts_{today.isoformat()}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["center_id", "name", "date", "reason"])
        for f in conflict_failures:
            writer.writerow([
                f.center_id,
                f.name,
                f.day.isoformat() if f.day else "",
                f.reason,
            ])
    return path
```

`name` is the existing `"Last, First"` string already built into the Failure. Splitting it back into last_name/first_name would require carrying both through `Failure`; one combined `name` column is enough for the operator-facing CSV.

- [ ] **Step 8.8: Call the CSV writer after the per-member loop**

Insert just before the `print(format_summary(...)...)` call (around line 239) in `main()`:

```python
    if not args.preview_data:
        conflict_csv = write_one_off_conflict_csv(failures, out_dir)
        if conflict_csv is not None:
            print(f"Wrote conflict report: {conflict_csv}", file=sys.stderr)
```

The CSV is suppressed in preview mode (no `out_dir` is created in preview).

- [ ] **Step 8.9: Run the full test suite to confirm nothing regressed**

```
.venv\Scripts\python.exe -m pytest -v
```
Expected: ALL PASS. The CLI integration changes are exercised by `tests/test_smoke.py` later (Task 14); the unit-level tests should be unaffected.

- [ ] **Step 8.10: Commit**

```bash
git add new_monthly_schedule.py
git commit -m "feat(cli): wire OneOffAvailability fetch and conflict CSV writer"
```

---

### Task 9: Wire one-off fetcher and conflict CSV into the GUI worker

**Files:**
- Modify: `gui/worker.py`

The GUI worker uses the eager-fetch pattern (one query, indexed by `center_id`). Mirror Task 8's choices but use `get_all_one_offs`.

- [ ] **Step 9.1: Import the new fetcher and exception**

In `gui/worker.py`, find the `from monthly_schedule.db import (...)` block and add `get_all_one_offs`:

```python
from monthly_schedule.db import (
    ...,
    get_all_availability, get_all_one_offs,
)
```

Find the `from monthly_schedule.per_day` import and add `OneOffConflict`:

```python
from monthly_schedule.per_day import compute_month_failure, OneOffConflict
```

(If the existing import doesn't already pull `compute_month_failure`, leave the rest unchanged and just import `OneOffConflict`.)

- [ ] **Step 9.2: Eager-fetch one-offs alongside the four supporting tables (around line 148-151)**

Add a fifth index right after `avail_idx`:

```python
        enroll_idx = get_all_enrollments(self.db_path)
        auth_idx = get_all_authorizations(self.db_path)
        absence_idx = get_all_absences(self.db_path)
        avail_idx = get_all_availability(self.db_path)
        one_off_idx = get_all_one_offs(self.db_path)
```

- [ ] **Step 9.3: Pass `one_offs` into the `MemberContext` (line 156)**

```python
                ctx = MemberContext(
                    enrollments=enroll_idx.get(cid, []),
                    authorizations=auth_idx.get(cid, []),
                    absences=absence_idx.get(cid, []),
                    availabilities=avail_idx.get(cid, []),
                    one_offs=one_off_idx.get(cid, []),
                )
```

- [ ] **Step 9.4: Find and update the `Failure` construction(s) in `gui/worker.py`**

The worker uses the same `Failure` namedtuple imported from `new_monthly_schedule` (or defines its own — check). Run:

```
.venv\Scripts\python.exe -c "import ast, pathlib; print(pathlib.Path('gui/worker.py').read_text())" | findstr /N "Failure"
```

If `Failure` is imported from `new_monthly_schedule`, the namedtuple change from Task 8 already applies — just patch each `Failure(...)` construction to pass `day=None` (or `day=exc.day` in the `OneOffConflict` branch from Step 9.5).

If `Failure` is defined locally in `gui/worker.py`, update its definition the same way:

```python
Failure = namedtuple("Failure", "center_id name stage reason day")
```

- [ ] **Step 9.5: Catch `OneOffConflict` in the worker's per-member try block**

The worker has a broad `except Exception` around `process_member` (around line 177). Insert a more specific catch before it:

```python
                ok, stage, reason = process_member(
                    member, ctx,
                    self.year, self.month, member_out_dir,
                    self.preview, api_key, cache,
                )
```

becomes (matching the new 4-tuple signature from Task 8):

```python
                ok, stage, reason, day = process_member(
                    member, ctx,
                    self.year, self.month, member_out_dir,
                    self.preview, api_key, cache,
                )
            except OneOffConflict as exc:
                # process_member already catches OneOffConflict internally
                # (Task 8 step 8.5) and returns it as a Failure. This
                # outer catch guards against any direct OneOffConflict
                # propagation in future refactors.
                ok = False
                stage = "one_off_conflict"
                reason = exc.reason
                day = exc.day
            except Exception as exc:  # noqa: BLE001
                ok = False
                stage = "worker"
                reason = f"{type(exc).__name__}: {exc}"
                day = None
```

Then patch the `failures.append(Failure(...))` call in the same loop to include `day`:

```python
                failures.append(
                    Failure(
                        member["center_id"],
                        f"{member['last_name']}, {member['first_name']}",
                        stage, reason, day,
                    )
                )
```

- [ ] **Step 9.6: Write the conflict CSV after the per-member loop**

Find the end of the for-loop and the worker's existing finalization block. Add:

```python
        from new_monthly_schedule import write_one_off_conflict_csv
        if not self.preview:
            csv_path = write_one_off_conflict_csv(failures, self.out_dir)
            if csv_path is not None:
                self.log_line.emit(
                    "worker.wrote",
                    {"filename": os.path.basename(csv_path)},
                )
```

If the GUI worker has a localizable string convention (e.g. `tr("worker.wrote_conflict_csv", ...)`), prefer that — check `gui/i18n.py` for available keys and use the closest match.

- [ ] **Step 9.7: Smoke-import the worker**

```
.venv\Scripts\python.exe -c "from gui.worker import *; print('ok')"
```
Expected: `ok` (no import errors). The GUI itself is harder to exercise from the command line — leave end-to-end coverage to Task 14.

- [ ] **Step 9.8: Run the full test suite**

```
.venv\Scripts\python.exe -m pytest -v
```
Expected: ALL PASS.

- [ ] **Step 9.9: Commit**

```bash
git add gui/worker.py
git commit -m "feat(gui-worker): eager-fetch one-offs and emit conflict CSV"
```

---

## Phase 5: Schema migration

### Task 10: Add the 5th DDL to `create_supporting_tables.py`

**Files:**
- Modify: `scripts/create_supporting_tables.py`

- [ ] **Step 10.1: Add the DDL constant**

In `scripts/create_supporting_tables.py`, add after `_CREATE_AVAILABILITY` (around line 73):

```python
_CREATE_ONE_OFF_AVAILABILITY = (
    "CREATE TABLE [OneOffAvailability] ("
    "[ID] AUTOINCREMENT PRIMARY KEY, "
    "[Center ID] DOUBLE, "
    "[date] DATETIME, "
    "[avail_start] DATETIME, "
    "[avail_end] DATETIME, "
    "[Notes] MEMO"
    ")"
)
```

- [ ] **Step 10.2: Append to `_DDLS`**

Update the `_DDLS` list (around line 75):

```python
_DDLS = [
    ("Enrollment", _CREATE_ENROLLMENT),
    ("Authorization", _CREATE_AUTHORIZATION),
    ("Absences", _CREATE_ABSENCES),
    ("Availability", _CREATE_AVAILABILITY),
    ("OneOffAvailability", _CREATE_ONE_OFF_AVAILABILITY),
]
```

- [ ] **Step 10.3: Update the script's module docstring**

Edit the existing docstring at the top of the file. Replace "four CREATE TABLE statements" with "five CREATE TABLE statements" and add `OneOffAvailability` to the bullet list of tables created.

- [ ] **Step 10.4: Smoke-import**

```
.venv\Scripts\python.exe -c "from scripts.create_supporting_tables import _DDLS; print([name for name, _ in _DDLS])"
```
Expected: `['Enrollment', 'Authorization', 'Absences', 'Availability', 'OneOffAvailability']`.

- [ ] **Step 10.5: Commit**

```bash
git add scripts/create_supporting_tables.py
git commit -m "feat(scripts): create_supporting_tables emits OneOffAvailability DDL"
```

---

### Task 11: Idempotent migration script for existing DBs

**Files:**
- Create: `scripts/add_one_off_availability_table.py`

- [ ] **Step 11.1: Write the script**

Create `scripts/add_one_off_availability_table.py` with this content:

```python
"""Add the OneOffAvailability table to an existing BSCA .accdb.

This is an idempotent migration for databases that were already
bootstrapped with the original four supporting tables (Enrollment,
Authorization, Absences, Availability) before OneOffAvailability
existed. Safe to run repeatedly: if the table already exists, the
script exits cleanly with an "already exists" message instead of
raising.

See docs/superpowers/specs/2026-06-04-one-off-availability-design.md.
"""
import argparse
import os
import sys


_CREATE_ONE_OFF_AVAILABILITY = (
    "CREATE TABLE [OneOffAvailability] ("
    "[ID] AUTOINCREMENT PRIMARY KEY, "
    "[Center ID] DOUBLE, "
    "[date] DATETIME, "
    "[avail_start] DATETIME, "
    "[avail_end] DATETIME, "
    "[Notes] MEMO"
    ")"
)


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _table_exists(cursor, name):
    """Return True if `name` is an existing user table.

    Uses the pyodbc tables() metadata accessor (Access exposes its
    schema through ODBC). Filtering by table_type='TABLE' excludes
    system tables and queries."""
    try:
        rows = cursor.tables(table=name, tableType="TABLE").fetchall()
        return any(r.table_name == name for r in rows)
    except Exception:
        # Fall back to a SELECT TOP 0 — if the table is absent, Access
        # raises; treat the raise as "absent".
        try:
            cursor.execute(f"SELECT TOP 0 * FROM [{name}]")
            return True
        except Exception:
            return False


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Add the OneOffAvailability table to an existing BSCA .accdb."
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-table stdout; print only the summary.")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if not os.path.exists(args.db):
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)
        return 2

    import pyodbc
    try:
        conn = pyodbc.connect(_build_connection_string(args.db))
    except pyodbc.Error as exc:
        print(
            "ERROR: could not open the Access database. Verify the "
            "Microsoft Access ODBC driver is installed and its "
            "bitness matches this Python interpreter. "
            f"Original error: {exc}",
            file=sys.stderr,
        )
        return 2

    try:
        cur = conn.cursor()
        if _table_exists(cur, "OneOffAvailability"):
            print("OneOffAvailability already exists; nothing to do.")
            return 0
        cur.execute(_CREATE_ONE_OFF_AVAILABILITY)
        conn.commit()
        if not args.quiet:
            print("  CREATED  OneOffAvailability")
        print("Created: OneOffAvailability")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 11.2: Smoke-import**

```
.venv\Scripts\python.exe -c "from scripts.add_one_off_availability_table import main, _CREATE_ONE_OFF_AVAILABILITY; print('ok')"
```
Expected: `ok`.

- [ ] **Step 11.3: Verify the script exits with 2 on a missing DB path (no ODBC needed)**

```
.venv\Scripts\python.exe scripts\add_one_off_availability_table.py --db C:\does\not\exist.accdb
```
Expected exit code 2 with the "database not found" message on stderr.

- [ ] **Step 11.4: Commit**

```bash
git add scripts/add_one_off_availability_table.py
git commit -m "feat(scripts): add idempotent OneOffAvailability migration"
```

---

### Task 12: Update `scripts/README.md`

**Files:**
- Modify: `scripts/README.md`

- [ ] **Step 12.1: Add a row to the script table**

Insert below the row for `audit_sadc.py`:

```markdown
| [`add_one_off_availability_table.py`](add_one_off_availability_table.py) | Idempotent DDL migration. Adds the `OneOffAvailability` table to an existing `.accdb` that already has the original four supporting tables. Safe to run repeatedly: skips with a friendly message if the table already exists. |
```

- [ ] **Step 12.2: Update the "Migration steps for a new DB" section**

Where the README currently says "the four supporting tables", change to "the five supporting tables". In the numbered command list, no change is needed — `create_supporting_tables.py` already creates `OneOffAvailability` after Task 10. Add a note at the end:

```markdown
After step 3, you have a fully migrated database. The
`OneOffAvailability` table starts empty; there is no backfill
script for it (no legacy source).

If your `.accdb` was created **before** the `OneOffAvailability`
table existed, run the standalone migration to add it without
re-creating the other tables:

    python scripts\add_one_off_availability_table.py --db <PATH>

The script is idempotent — running it on a DB that already has the
table prints "already exists" and exits 0.
```

- [ ] **Step 12.3: Commit**

```bash
git add scripts/README.md
git commit -m "docs(scripts): document OneOffAvailability migration"
```

---

## Phase 6: Test database scenario

### Task 13: Add `one_off_conflict` scenario to `make_test_db.py`

**Files:**
- Modify: `scripts/make_test_db.py`

- [ ] **Step 13.1: Add `OneOffAvailability` to the table-truncation order**

Edit `SUPPORTING_TABLES` (around line 25). Children-before-parents order; `OneOffAvailability` references `Contacts.[Center ID]` the same way the others do, so put it first:

```python
SUPPORTING_TABLES = ("OneOffAvailability", "Availability", "Absences",
                     "Authorization", "Enrollment")
```

- [ ] **Step 13.2: Add a helper to seed a one-off row**

Add near `_seed_member`:

```python
def _seed_one_off(conn, center_id: int, when: date,
                  start_hm: tuple, end_hm: tuple,
                  notes: str = "") -> None:
    """Insert one OneOffAvailability row.

    `when` is the date the exception applies to. `start_hm` / `end_hm`
    are (hour, minute) tuples, which become the 1899-12-30 placeholder
    DATETIMEs Access uses for time-only fields."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO [OneOffAvailability] "
        "([Center ID], [date], [avail_start], [avail_end], [Notes]) "
        "VALUES (?, ?, ?, ?, ?)",
        center_id, _dt(when), _hhmm(*start_hm), _hhmm(*end_hm), notes,
    )
```

- [ ] **Step 13.3: Add the scenario function**

Add a new scenario after the existing ones, e.g.:

```python
def _seed_one_off_conflict(conn, today: date) -> None:
    """Seed: a single member with a one-off on a day they're also
    absent on. Exercises the OneOffConflict path end-to-end.

    Layout:
      - Enrollment: this month + next month.
      - Authorization: this month + next month, Mon/Wed/Fri (1,3,5).
      - Availability: Mon 09:00-15:00 (recurring), Wed 09:00-15:00,
        Fri 09:00-15:00.
      - Absence: a single day = first Monday of this month.
      - OneOffAvailability: the SAME first Monday, 12:00-16:00 →
        conflict reason: 'one-off on YYYY-MM-DD conflicts with absence'.
    """
    m1, _, mlast, mnext_last = _month_bounds(today)
    cid = 100100

    _seed_member(conn, cid, "Conflict", "Sample")

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO [Enrollment] ([Center ID], [start_date], [end_date]) "
        "VALUES (?, ?, ?)",
        cid, _dt(m1), _dt(mnext_last),
    )
    cur.execute(
        "INSERT INTO [Authorization] ([Center ID], [auth_start], [auth_end], "
        "[effective_start], [effective_end], [auth_days], [Health Plan]) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        cid, _dt(m1), _dt(mnext_last), _dt(m1), _dt(mnext_last),
        "1,3,5", "HOF",
    )
    for dow in (1, 3, 5):
        cur.execute(
            "INSERT INTO [Availability] ([Center ID], "
            "[effective_start_date], [effective_end_date], [Day Of Week], "
            "[avail_start], [avail_end]) VALUES (?, ?, ?, ?, ?, ?)",
            cid, _dt(m1), None, dow, _hhmm(9, 0), _hhmm(15, 0),
        )

    # First Monday of this month is the conflict day.
    first_monday = m1
    while first_monday.isoweekday() != 1:
        first_monday = first_monday + timedelta(days=1)

    cur.execute(
        "INSERT INTO [Absences] ([Center ID], [Leave Type], "
        "[Start_Date], [End_Date], [Notes]) VALUES (?, ?, ?, ?, ?)",
        cid, "Sick", _dt(first_monday), _dt(first_monday), "",
    )

    _seed_one_off(
        conn, cid, first_monday,
        start_hm=(12, 0), end_hm=(16, 0),
        notes="doctor appt 8-12",
    )
```

- [ ] **Step 13.4: Register the scenario**

Find the scenario dispatch in `main()` (look for `if args.scenario == "happy_path"` or a scenario dict). Add a branch / entry for `"one_off_conflict"` that calls `_seed_one_off_conflict(conn, today)`. The argparse `--scenario` choices list also needs the new name added.

- [ ] **Step 13.5: Smoke-import**

```
.venv\Scripts\python.exe -c "from scripts.make_test_db import _seed_one_off_conflict, _seed_one_off, SUPPORTING_TABLES; print(SUPPORTING_TABLES)"
```
Expected: `('OneOffAvailability', 'Availability', 'Absences', 'Authorization', 'Enrollment')`.

- [ ] **Step 13.6: Commit**

```bash
git add scripts/make_test_db.py
git commit -m "feat(test-db): one_off_conflict scenario"
```

---

## Phase 7: End-to-end smoke coverage

### Task 14: Extend the smoke test for the one-off conflict path

**Files:**
- Modify: `tests/test_smoke.py`

`tests/test_smoke.py` is currently a one-liner ("imports the package"). The end-to-end conflict test needs an Access DB, so we mark it as **conditionally skipped** when the ODBC driver isn't available. This keeps the suite portable while still verifying the wiring on the dev box.

- [ ] **Step 14.1: Replace `tests/test_smoke.py` with the extended version**

```python
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_package_imports():
    import monthly_schedule  # noqa: F401


def _odbc_available() -> bool:
    try:
        import pyodbc
    except ImportError:
        return False
    return any(
        "Microsoft Access Driver" in name for name in pyodbc.drivers()
    )


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(
    not _odbc_available(),
    reason="Microsoft Access ODBC driver not available in this environment",
)
def test_one_off_conflict_writes_conflict_csv(tmp_path):
    """End-to-end: seed the one_off_conflict scenario, run the CLI,
    confirm `one_off_conflicts_<DATE>.csv` lands in the output dir
    with the expected single row."""
    test_db = tmp_path / "test.accdb"
    # The repository's reference template — adjust if your local
    # workflow uses a different source.
    src = Path(os.environ.get(
        "BSCA_TEST_DB_SRC",
        REPO_ROOT / "scripts" / "test_dbs" / "populate_real_members.accdb",
    ))
    if not src.exists():
        pytest.skip(f"Source DB template not found: {src}")
    shutil.copy(src, test_db)

    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "create_supporting_tables.py"),
         "--db", str(test_db), "--quiet"],
        check=False,  # may report "already exists" — that's fine
    )

    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "make_test_db.py"),
         "--scenario", "one_off_conflict", "--output", str(test_db)],
        check=True,
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "new_monthly_schedule.py"),
         "--center-id", "100100",
         "--year", "2026", "--month", "6",
         "--db-path", str(test_db),
         "--output-path", str(out_dir),
         "--google-config", str(REPO_ROOT / "google_maps.config"),
         "--geo-cache", str(tmp_path / "geo_cache.json"),
        ],
        capture_output=True, text=True,
    )

    # The CLI returns 2 when there are any failures — the conflict counts.
    assert result.returncode == 2, result.stderr

    csv_files = list(out_dir.glob("one_off_conflicts_*.csv"))
    assert len(csv_files) == 1, (
        f"Expected exactly one conflict CSV, got: {csv_files}\n"
        f"stderr: {result.stderr}"
    )
    body = csv_files[0].read_text(encoding="utf-8")
    assert "100100" in body
    assert "conflicts with absence" in body
```

The `google_maps.config` path and the source DB template path may need adjusting for the local workflow; the spec accepts this as a hand-off detail (the test skips when the source template is missing).

- [ ] **Step 14.2: Run the smoke test**

```
.venv\Scripts\python.exe -m pytest tests/test_smoke.py -v
```
Expected on a dev machine with ODBC + source DB: PASS. Otherwise: SKIPPED with a clear reason.

- [ ] **Step 14.3: Run the full suite**

```
.venv\Scripts\python.exe -m pytest -v
```
Expected: ALL PASS or SKIP — no failures.

- [ ] **Step 14.4: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test(smoke): cover one-off conflict CSV emission end-to-end"
```

---

## Phase 8: Final verification

### Task 15: Full-suite verification and manual GUI smoke

**Files:** none modified

- [ ] **Step 15.1: Run the full pytest suite**

```
.venv\Scripts\python.exe -m pytest -v
```
Expected: ALL PASS (or skip), 0 failures.

- [ ] **Step 15.2: Confirm the CLI shows the conflict in its summary**

If you have a real Access DB available:

```
.venv\Scripts\python.exe scripts\make_test_db.py --scenario one_off_conflict --output test.accdb --use
.venv\Scripts\python.exe new_monthly_schedule.py --center-id 100100 --year 2026 --month 6 --db-path test.accdb --output-path out
```

Expected stderr summary includes the line:

```
  - ID 100100 (Conflict, Sample): one_off_conflict — one-off on 2026-06-01 conflicts with absence
```

And `out/one_off_conflicts_2026-06-04.csv` (today's date) contains one row for that center.

- [ ] **Step 15.3: Launch the GUI on the same test DB and confirm a parallel result**

```
.venv\Scripts\python.exe -m gui
```

Pick "Single member" mode, enter `100100`, month June 2026, run. Expect the result panel to show 1 failure with reason "one-off on … conflicts with absence" and the same CSV under the output folder.

This step is **manual**; record the outcome in the task tracker but do not block on it for CI.

---

## Self-Review

(Performed by the plan author before handing off; not a task for the implementer.)

**1. Spec coverage check.** Mapped each spec section to its task(s):

- **Data model** (spec §"Data model") → Tasks 10, 11 (DDL).
- **Reading the table** (spec §"Reading the table") → Task 7 (`get_one_offs` / `get_all_one_offs`).
- **MemberContext** (spec §"MemberContext") → Task 2 (constructor + lookup), Task 3 (call-site updates).
- **Scheduler integration** (spec §"Scheduler integration") → Task 4 (one-off branch placement), Task 6 (silent-skip cases).
- **Conflict checks** (spec §"Conflict checks") → Task 5 (raise + reason strings + first-match ordering).
- **New exception type** (spec §"New exception type") → Task 1.
- **CSV output** (spec §"CSV output") → Task 8 (CLI writer), Task 9 (GUI worker).
- **Migration** (spec §"Migration") → Task 10 (bootstrap), Task 11 (idempotent migration), Task 12 (README).
- **Testing** (spec §"Testing") → Tasks 4, 5, 6 (unit), Task 14 (smoke), Task 13 (test-DB scenario).

No gaps.

**2. Placeholder scan.** No "TBD", "TODO", "implement later", or "similar to Task N" references. Each step contains the full content (test bodies, exact imports, exact replacements). The two `one_offs=[]` placeholders in Task 3 are explicit interim wiring with the follow-up task (7/8) named — that's a deliberate sequencing aid, not an open question.

**3. Type / signature consistency.**
- `OneOffConflict(center_id, day, reason)` — same shape in Task 1, Task 4, Task 5, Task 8, Task 9.
- `MemberContext(..., one_offs)` — required positional/keyword param everywhere (Tasks 2, 3, 8, 9).
- `Failure(center_id, name, stage, reason, day)` — 5 fields after Task 8; Task 9 follows the same shape.
- `process_member` return signature is `(ok, stage, reason, day)` consistently after Task 8.

No mismatches.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-04-one-off-availability.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
