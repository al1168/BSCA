# Schedule Data Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the scheduler to read enrollment, authorization, absences, and availability from the four new Access tables instead of the legacy `Contacts.SADC` field. Add per-day eligibility checks and whole-member failure reasons that surface in the run summary.

**Architecture:** A new `MemberContext` value object holds the four supporting-table rows for one member. A pure-Python `compute_day_eligibility` function consults the context plus the plan's timing rules to decide if a date is schedulable and (optionally) narrows the arrival window. `process_member` fetches the four tables and threads the context through `build_rows`. CLI and GUI worker both gain a small wiring change; `gui/i18n.py` gets three new failure-reason keys.

**Tech Stack:** Python 3.13, PyQt6 6.11, pyodbc (Access ODBC), pytest 8.3. Access schema changes (creating the four tables, dropping `SADC` from being read) are done manually in the Access GUI and are NOT in this plan's scope.

**Spec:** [docs/superpowers/specs/2026-05-26-schedule-data-model-design.md](../specs/2026-05-26-schedule-data-model-design.md)
**Reference:** [docs/database.md](../../database.md)

---

## Preconditions

Before executing this plan:

1. The four new tables (`Enrollment`, `Authorization`, `Absences`, `Availability`) must exist in Access with the column names listed in the spec. Each must have a `Center ID` foreign key to `Contacts`.
2. The Authorization table must include `auth_days` (Short Text) and `notes` (Long Text).
3. The Availability table must include `effective_start_date`, `effective_end_date` (Date/Time, end nullable), and `Notes` (Long Text).
4. Every member who should be schedulable must have at least one Enrollment row and one Authorization row covering the target month. (Per the spec's migration section.)

If these aren't done yet, the code will still install cleanly, but every member will fail with `"not enrolled during {YYYY-MM}"` or `"no active authorization for {YYYY-MM}"` until rows are backfilled. That's the intended failure mode.

---

## File Inventory

| File | Action | Responsibility |
| --- | --- | --- |
| `monthly_schedule/db.py` | Modify | Add 4 query constants + 4 fetch functions for the new tables; drop `[SADC]` from `MEMBER_QUERY` / `MEMBERS_BY_PLAN_QUERY` |
| `monthly_schedule/eligibility_context.py` | Create | `MemberContext` class with most-recent-wins lookups |
| `monthly_schedule/per_day.py` | Create | `compute_day_eligibility` and `compute_month_failure` pure functions |
| `monthly_schedule/daily_schedule.py` | Modify | `build_daily_schedule` accepts an optional `arrival_window` override |
| `monthly_schedule/rows.py` | Modify | `build_rows` accepts a `ctx` and `plan_rules`; calls per-day eligibility |
| `new_monthly_schedule.py` | Modify | `process_member` accepts a `ctx`; defines `REASON_NOT_ENROLLED`, `REASON_NO_AUTH`, `REASON_ABSENT_MONTH` constants; CLI `main()` builds ctx per member |
| `gui/worker.py` | Modify | `run()` builds ctx per member before calling `process_member` |
| `gui/i18n.py` | Modify | Add `summary.stage.eligibility`, `summary.reason.not_enrolled`, `summary.reason.no_auth`, `summary.reason.absent_month` keys (en + zh) |
| `gui/main_window.py` | Modify | `_build_summary` translates the new reason constants |
| `tests/test_db.py` | Modify | Add tests for new query constants + functions; update existing for dropped SADC |
| `tests/test_eligibility_context.py` | Create | MemberContext unit tests |
| `tests/test_per_day.py` | Create | `compute_day_eligibility` + `compute_month_failure` unit tests |
| `tests/test_rows.py` | Modify | Update for new build_rows signature |
| `tests/test_cli.py` | Modify | Replace `auth_days` in `FAKE_MEMBER`; mock new DB calls |
| `tests/test_i18n.py` | (no change) | The autouse parity test catches new keys automatically |

No changes to: `monthly_schedule/auth_days.py`, `monthly_schedule/month_dates.py`, `monthly_schedule/rules.py`, `monthly_schedule/workbook.py`, `monthly_schedule/travel.py`.

---

## Task 1: Add 4 DB query functions for the new tables

**Files:**
- Modify: `monthly_schedule/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
import pytest

from monthly_schedule.db import (
    ENROLLMENTS_QUERY,
    AUTHORIZATIONS_QUERY,
    ABSENCES_QUERY,
    AVAILABILITY_QUERY,
    get_enrollments,
    get_authorizations,
    get_absences,
    get_availability,
    map_enrollment_row,
    map_authorization_row,
    map_absence_row,
    map_availability_row,
)


def test_enrollments_query_columns_and_filter():
    assert "[Center ID]" in ENROLLMENTS_QUERY
    assert "[start_date]" in ENROLLMENTS_QUERY
    assert "[end_date]" in ENROLLMENTS_QUERY
    assert "FROM [Enrollment]" in ENROLLMENTS_QUERY
    assert "WHERE [Center ID] = ?" in ENROLLMENTS_QUERY


def test_authorizations_query_columns_and_filter():
    for col in ("[Center ID]", "[auth_start]", "[auth_end]",
                "[effective_start]", "[effective_end]", "[auth_days]"):
        assert col in AUTHORIZATIONS_QUERY
    assert "FROM [Authorization]" in AUTHORIZATIONS_QUERY
    assert "WHERE [Center ID] = ?" in AUTHORIZATIONS_QUERY


def test_absences_query_columns_and_filter():
    for col in ("[Center ID]", "[Leave Type]", "[Start_Date]", "[End_Date]"):
        assert col in ABSENCES_QUERY
    assert "FROM [Absences]" in ABSENCES_QUERY
    assert "WHERE [Center ID] = ?" in ABSENCES_QUERY


def test_availability_query_columns_and_filter():
    for col in ("[Center ID]", "[effective_start_date]",
                "[effective_end_date]", "[Day Of Week]",
                "[avail_start]", "[avail_end]"):
        assert col in AVAILABILITY_QUERY
    assert "FROM [Availability]" in AVAILABILITY_QUERY
    assert "WHERE [Center ID] = ?" in AVAILABILITY_QUERY


def test_map_enrollment_row():
    from datetime import date
    row = (1, 24010.0, date(2026, 1, 1), None)
    assert map_enrollment_row(row) == {
        "id": 1,
        "center_id": 24010,
        "start_date": date(2026, 1, 1),
        "end_date": None,
    }


def test_map_authorization_row():
    from datetime import date
    row = (5, 24010.0, date(2026, 1, 1), date(2026, 12, 31),
           date(2026, 1, 1), date(2026, 6, 30), "1,3,5")
    assert map_authorization_row(row) == {
        "id": 5,
        "center_id": 24010,
        "auth_start": date(2026, 1, 1),
        "auth_end": date(2026, 12, 31),
        "effective_start": date(2026, 1, 1),
        "effective_end": date(2026, 6, 30),
        "auth_days": "1,3,5",
    }


def test_map_absence_row():
    from datetime import date
    row = (7, 24010.0, "Vacation", date(2026, 5, 10), date(2026, 5, 16))
    assert map_absence_row(row) == {
        "id": 7,
        "center_id": 24010,
        "leave_type": "Vacation",
        "start_date": date(2026, 5, 10),
        "end_date": date(2026, 5, 16),
    }


def test_map_availability_row():
    from datetime import date
    row = (3, 24010.0, date(2026, 1, 1), None, 2, "10:00", "15:00")
    assert map_availability_row(row) == {
        "id": 3,
        "center_id": 24010,
        "effective_start_date": date(2026, 1, 1),
        "effective_end_date": None,
        "day_of_week": 2,
        "avail_start": "10:00",
        "avail_end": "15:00",
    }


def test_get_enrollments_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_enrollments(24010, str(missing))


def test_get_authorizations_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_authorizations(24010, str(missing))


def test_get_absences_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_absences(24010, str(missing))


def test_get_availability_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_availability(24010, str(missing))
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.venv\Scripts\pytest tests/test_db.py -v
```

Expected: import errors for the new names.

- [ ] **Step 3: Add the new queries and functions to `monthly_schedule/db.py`**

Append to `monthly_schedule/db.py`:

```python
ENROLLMENTS_QUERY = (
    "SELECT [ID], [Center ID], [start_date], [end_date] "
    "FROM [Enrollment] "
    "WHERE [Center ID] = ?"
)


def map_enrollment_row(row):
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "start_date": row[2],
        "end_date": row[3],
    }


def get_enrollments(center_id, db_path):
    """Return all Enrollment rows for `center_id` as a list of dicts."""
    return _fetch_all(ENROLLMENTS_QUERY, center_id, db_path, map_enrollment_row)


AUTHORIZATIONS_QUERY = (
    "SELECT [ID], [Center ID], [auth_start], [auth_end], "
    "[effective_start], [effective_end], [auth_days] "
    "FROM [Authorization] "
    "WHERE [Center ID] = ?"
)


def map_authorization_row(row):
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "auth_start": row[2],
        "auth_end": row[3],
        "effective_start": row[4],
        "effective_end": row[5],
        "auth_days": row[6],
    }


def get_authorizations(center_id, db_path):
    """Return all Authorization rows for `center_id` as a list of dicts."""
    return _fetch_all(AUTHORIZATIONS_QUERY, center_id, db_path,
                      map_authorization_row)


ABSENCES_QUERY = (
    "SELECT [ID], [Center ID], [Leave Type], [Start_Date], [End_Date] "
    "FROM [Absences] "
    "WHERE [Center ID] = ?"
)


def map_absence_row(row):
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "leave_type": row[2],
        "start_date": row[3],
        "end_date": row[4],
    }


def get_absences(center_id, db_path):
    """Return all Absences rows for `center_id` as a list of dicts."""
    return _fetch_all(ABSENCES_QUERY, center_id, db_path, map_absence_row)


AVAILABILITY_QUERY = (
    "SELECT [ID], [Center ID], [effective_start_date], "
    "[effective_end_date], [Day Of Week], [avail_start], [avail_end] "
    "FROM [Availability] "
    "WHERE [Center ID] = ?"
)


def map_availability_row(row):
    return {
        "id": int(row[0]),
        "center_id": int(row[1]),
        "effective_start_date": row[2],
        "effective_end_date": row[3],
        "day_of_week": int(row[4]),
        "avail_start": row[5],
        "avail_end": row[6],
    }


def get_availability(center_id, db_path):
    """Return all Availability rows for `center_id` as a list of dicts."""
    return _fetch_all(AVAILABILITY_QUERY, center_id, db_path,
                      map_availability_row)


def _fetch_all(query, center_id, db_path, mapper):
    """Run a parameterized SELECT and map each row. Shared by the 4 new
    fetchers."""
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
        cursor.execute(query, center_id)
        return [mapper(row) for row in cursor.fetchall()]
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
.venv\Scripts\pytest tests/test_db.py -v
```

Expected: all tests pass including the existing ones.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/db.py tests/test_db.py
git commit -m "feat(db): add queries for Enrollment, Authorization, Absences, Availability"
```

---

## Task 2: MemberContext value object

**Files:**
- Create: `monthly_schedule/eligibility_context.py`
- Create: `tests/test_eligibility_context.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eligibility_context.py`:

```python
from datetime import date

from monthly_schedule.eligibility_context import MemberContext


def test_is_enrolled_true_open_ended():
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[], absences=[], availabilities=[],
    )
    assert ctx.is_enrolled(date(2026, 5, 15)) is True


def test_is_enrolled_true_inside_range():
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1),
                      "end_date": date(2026, 12, 31)}],
        authorizations=[], absences=[], availabilities=[],
    )
    assert ctx.is_enrolled(date(2026, 5, 15)) is True


def test_is_enrolled_false_before_start():
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 6, 1), "end_date": None}],
        authorizations=[], absences=[], availabilities=[],
    )
    assert ctx.is_enrolled(date(2026, 5, 15)) is False


def test_is_enrolled_false_after_end():
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1),
                      "end_date": date(2026, 4, 30)}],
        authorizations=[], absences=[], availabilities=[],
    )
    assert ctx.is_enrolled(date(2026, 5, 15)) is False


def test_is_enrolled_returning_member_multiple_rows():
    ctx = MemberContext(
        enrollments=[
            {"id": 1, "center_id": 1,
             "start_date": date(2025, 1, 1), "end_date": date(2025, 6, 30)},
            {"id": 2, "center_id": 1,
             "start_date": date(2026, 1, 1), "end_date": None},
        ],
        authorizations=[], absences=[], availabilities=[],
    )
    assert ctx.is_enrolled(date(2025, 3, 1)) is True
    assert ctx.is_enrolled(date(2025, 10, 1)) is False  # gap
    assert ctx.is_enrolled(date(2026, 5, 15)) is True


def test_active_authorization_picks_overlapping_row():
    auth_a = {"id": 1, "center_id": 1,
              "auth_start": date(2025, 1, 1), "auth_end": date(2025, 12, 31),
              "effective_start": date(2025, 1, 1),
              "effective_end": date(2025, 12, 31),
              "auth_days": "1,3,5"}
    auth_b = {"id": 2, "center_id": 1,
              "auth_start": date(2026, 1, 1), "auth_end": date(2026, 12, 31),
              "effective_start": date(2026, 1, 1),
              "effective_end": date(2026, 12, 31),
              "auth_days": "2,4"}
    ctx = MemberContext(
        enrollments=[], authorizations=[auth_a, auth_b],
        absences=[], availabilities=[],
    )
    assert ctx.active_authorization(date(2025, 6, 1)) == auth_a
    assert ctx.active_authorization(date(2026, 6, 1)) == auth_b


def test_active_authorization_most_recent_wins_on_overlap():
    a = {"id": 1, "center_id": 1,
         "auth_start": date(2026, 1, 1), "auth_end": date(2026, 12, 31),
         "effective_start": date(2026, 1, 1),
         "effective_end": date(2026, 12, 31),
         "auth_days": "1,3,5"}
    b = {"id": 2, "center_id": 1,
         "auth_start": date(2026, 7, 1), "auth_end": date(2026, 12, 31),
         "effective_start": date(2026, 7, 1),
         "effective_end": date(2026, 12, 31),
         "auth_days": "2,4"}
    ctx = MemberContext(
        enrollments=[], authorizations=[a, b],
        absences=[], availabilities=[],
    )
    # July 15 is covered by both; b has the later effective_start → wins
    assert ctx.active_authorization(date(2026, 7, 15)) == b


def test_active_authorization_none_when_no_match():
    ctx = MemberContext(
        enrollments=[], authorizations=[],
        absences=[], availabilities=[],
    )
    assert ctx.active_authorization(date(2026, 5, 1)) is None


def test_is_absent_inclusive_range():
    ctx = MemberContext(
        enrollments=[], authorizations=[],
        absences=[{"id": 1, "center_id": 1, "leave_type": "Vacation",
                   "start_date": date(2026, 5, 10),
                   "end_date": date(2026, 5, 16)}],
        availabilities=[],
    )
    assert ctx.is_absent(date(2026, 5, 9)) is False
    assert ctx.is_absent(date(2026, 5, 10)) is True
    assert ctx.is_absent(date(2026, 5, 16)) is True
    assert ctx.is_absent(date(2026, 5, 17)) is False


def test_availability_for_matches_weekday_and_period():
    rule = {"id": 1, "center_id": 1,
            "effective_start_date": date(2026, 1, 1),
            "effective_end_date": None,
            "day_of_week": 2,
            "avail_start": "10:00", "avail_end": "15:00"}
    ctx = MemberContext(
        enrollments=[], authorizations=[], absences=[],
        availabilities=[rule],
    )
    # 2026-05-05 is a Tuesday (isoweekday 2) → match
    assert ctx.availability_for(date(2026, 5, 5)) == rule
    # 2026-05-06 is a Wednesday → no match (rule is for Tuesday only)
    assert ctx.availability_for(date(2026, 5, 6)) is None


def test_availability_for_most_recent_wins():
    older = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": date(2026, 12, 31),
             "day_of_week": 2,
             "avail_start": "10:00", "avail_end": "15:00"}
    newer = {"id": 2, "center_id": 1,
             "effective_start_date": date(2026, 6, 1),
             "effective_end_date": None,
             "day_of_week": 2,
             "avail_start": "11:00", "avail_end": "14:00"}
    ctx = MemberContext(
        enrollments=[], authorizations=[], absences=[],
        availabilities=[older, newer],
    )
    # 2026-06-02 is a Tuesday; both match; newer wins
    assert ctx.availability_for(date(2026, 6, 2)) == newer
    # 2026-05-05 is a Tuesday; only older matches
    assert ctx.availability_for(date(2026, 5, 5)) == older
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.venv\Scripts\pytest tests/test_eligibility_context.py -v
```

Expected: `ModuleNotFoundError: No module named 'monthly_schedule.eligibility_context'`.

- [ ] **Step 3: Create `monthly_schedule/eligibility_context.py`**

```python
"""Per-member view of the four supporting tables, with most-recent-wins
date lookups."""

from datetime import date


class MemberContext:
    """Holds a member's enrollment / authorization / absence /
    availability rows (as dicts from db.py) and answers per-day queries.

    On overlapping rows the latest start-date wins; ties on start break
    to the largest `id` (deliberate, see spec section "Overlap Resolution").
    """

    def __init__(self, enrollments, authorizations, absences, availabilities):
        self._enrollments = list(enrollments)
        self._authorizations = list(authorizations)
        self._absences = list(absences)
        self._availabilities = list(availabilities)

    def is_enrolled(self, day: date) -> bool:
        for row in self._enrollments:
            start = row["start_date"]
            end = row["end_date"]
            if start <= day and (end is None or day <= end):
                return True
        return False

    def active_authorization(self, day: date):
        candidates = [
            row for row in self._authorizations
            if row["effective_start"] <= day <= row["effective_end"]
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: (r["effective_start"], r["id"]))

    def is_absent(self, day: date) -> bool:
        for row in self._absences:
            if row["start_date"] <= day <= row["end_date"]:
                return True
        return False

    def availability_for(self, day: date):
        weekday = day.isoweekday()
        candidates = []
        for row in self._availabilities:
            if row["day_of_week"] != weekday:
                continue
            start = row["effective_start_date"]
            end = row["effective_end_date"]
            if start <= day and (end is None or day <= end):
                candidates.append(row)
        if not candidates:
            return None
        return max(candidates, key=lambda r: (r["effective_start_date"], r["id"]))
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
.venv\Scripts\pytest tests/test_eligibility_context.py -v
```

Expected: all 11 tests pass.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/eligibility_context.py tests/test_eligibility_context.py
git commit -m "feat(eligibility): add MemberContext with most-recent-wins lookups"
```

---

## Task 3: Per-day eligibility + whole-month failure detection

**Files:**
- Create: `monthly_schedule/per_day.py`
- Create: `tests/test_per_day.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_per_day.py`:

```python
from datetime import date

from monthly_schedule.eligibility_context import MemberContext
from monthly_schedule.per_day import (
    DayEligibility,
    compute_day_eligibility,
    compute_month_failure,
)


PLAN_RULES = {
    "arrival_window": ("08:00", "11:00"),
    "session_span_min": (210, 245),
}


def _ctx(enrolled=True, authorized="1,3,5", absent=False, availability=None):
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
    return MemberContext(enrollments, authorizations, absences, availabilities)


def test_eligible_day_no_availability_rule():
    # 2026-05-04 is a Monday (isoweekday 1) → in auth_days "1,3,5"
    result = compute_day_eligibility(date(2026, 5, 4), _ctx(), PLAN_RULES)
    assert result.eligible is True
    assert result.arrival_window is None


def test_ineligible_not_enrolled():
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(enrolled=False), PLAN_RULES
    )
    assert result.eligible is False


def test_ineligible_no_authorization():
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(authorized=None), PLAN_RULES
    )
    assert result.eligible is False


def test_ineligible_wrong_weekday():
    # 2026-05-05 is a Tuesday (isoweekday 2) → NOT in "1,3,5"
    result = compute_day_eligibility(date(2026, 5, 5), _ctx(), PLAN_RULES)
    assert result.eligible is False


def test_ineligible_absent():
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(absent=True), PLAN_RULES
    )
    assert result.eligible is False


def test_availability_rule_narrows_window():
    # Plan default arrival is 08:00–11:00, session_span_min lower is 210.
    # Member is available 10:00–15:00 on Mondays.
    # Effective arrival window:
    #   lo = max(480 [08:00], 600 [10:00]) = 600
    #   hi = min(660 [11:00], 900 [15:00] - 210) = min(660, 690) = 660
    avail = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": None,
             "day_of_week": 1,
             "avail_start": "10:00", "avail_end": "15:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=avail), PLAN_RULES
    )
    assert result.eligible is True
    assert result.arrival_window == (600, 660)


def test_availability_window_too_narrow_makes_day_ineligible():
    # Member available only 12:00–13:30 on Monday: lo=720, hi=min(660, 810-210)=600;
    # lo > hi → ineligible.
    avail = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": None,
             "day_of_week": 1,
             "avail_start": "12:00", "avail_end": "13:30"}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=avail), PLAN_RULES
    )
    assert result.eligible is False


def test_month_failure_none_when_all_present():
    failure = compute_month_failure(2026, 5, _ctx())
    assert failure is None


def test_month_failure_not_enrolled():
    failure = compute_month_failure(2026, 5, _ctx(enrolled=False))
    from monthly_schedule.per_day import REASON_NOT_ENROLLED
    assert failure == REASON_NOT_ENROLLED


def test_month_failure_no_authorization():
    failure = compute_month_failure(2026, 5, _ctx(authorized=None))
    from monthly_schedule.per_day import REASON_NO_AUTH
    assert failure == REASON_NO_AUTH


def test_month_failure_absent_entire_month():
    # Authorized for Mon/Wed/Fri; absences cover all of May.
    failure = compute_month_failure(2026, 5, _ctx(absent=True))
    from monthly_schedule.per_day import REASON_ABSENT_MONTH
    assert failure == REASON_ABSENT_MONTH


def test_month_failure_partial_absence_is_not_whole_month():
    # Absent for only one day → not a whole-month failure.
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[{"id": 1, "center_id": 1, "leave_type": "Sick",
                   "start_date": date(2026, 5, 4),
                   "end_date": date(2026, 5, 4)}],
        availabilities=[],
    )
    assert compute_month_failure(2026, 5, ctx) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.venv\Scripts\pytest tests/test_per_day.py -v
```

Expected: `ModuleNotFoundError: No module named 'monthly_schedule.per_day'`.

- [ ] **Step 3: Create `monthly_schedule/per_day.py`**

```python
"""Per-day eligibility derived from a MemberContext, and the whole-month
failure check used to skip a member entirely from the run summary."""

from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

from monthly_schedule.auth_days import get_authorized_weekdays
from monthly_schedule.month_dates import get_month_dates
from monthly_schedule.rules import parse_hhmm


REASON_NOT_ENROLLED = "not enrolled during this month"
REASON_NO_AUTH = "no active authorization for this month"
REASON_ABSENT_MONTH = "absent for the entire month"


@dataclass(frozen=True)
class DayEligibility:
    """Result of a single-day eligibility check.

    `arrival_window` is None when the plan's default applies; a tuple of
    (lo_minutes, hi_minutes) when an Availability rule has narrowed it.
    """
    eligible: bool
    arrival_window: Optional[Tuple[int, int]] = None


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


def compute_month_failure(year: int, month: int, ctx):
    """Return a whole-member failure reason string for this month, or None
    if the member has at least one eligible day."""
    days = list(get_month_dates(year, month))

    if not any(ctx.is_enrolled(d) for d in days):
        return REASON_NOT_ENROLLED
    if not any(ctx.active_authorization(d) is not None for d in days):
        return REASON_NO_AUTH

    # Check whether the absences blanket every authorized day in the month.
    has_authorized_unblocked = False
    for d in days:
        auth = ctx.active_authorization(d)
        if auth is None:
            continue
        if d.isoweekday() not in get_authorized_weekdays(auth["auth_days"]):
            continue
        if ctx.is_absent(d):
            continue
        has_authorized_unblocked = True
        break

    if not has_authorized_unblocked:
        # Distinguish "absent for entire month" from "no authorized days at
        # all this month" (the latter is rare but possible). Both reduce to
        # the same surfaced reason: nothing to schedule.
        return REASON_ABSENT_MONTH

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
.venv\Scripts\pytest tests/test_per_day.py -v
```

Expected: all 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/per_day.py tests/test_per_day.py
git commit -m "feat(eligibility): compute_day_eligibility + compute_month_failure"
```

---

## Task 4: `build_daily_schedule` accepts a narrowed arrival window

**Files:**
- Modify: `monthly_schedule/daily_schedule.py`
- Modify: `tests/test_daily_schedule.py` (add 1 test; existing tests still pass)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_daily_schedule.py`:

```python
def test_build_daily_schedule_honors_arrival_window_override():
    import random
    from monthly_schedule.daily_schedule import build_daily_schedule
    rules = {
        "arrival_window": ("08:00", "11:00"),
        "session_span_min": (210, 245),
        "pickup_lead_min": (8, 12),
        "dropoff_trail_min": (8, 12),
        "time_in_drift_min": (2, 2),
        "time_out_drift_min": (2, 2),
        "round_to_minutes": 1,
        "travel_buffer_min": (1, 5),
    }
    # Force the schedule to fall inside a narrow 10:00–10:30 window.
    result = build_daily_schedule(rules, random.Random(0),
                                  arrival_window=(600, 630))
    h, m = result["arrival"].split(":")
    arrival_min = int(h) * 60 + int(m)
    assert 600 <= arrival_min <= 630
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
.venv\Scripts\pytest tests/test_daily_schedule.py::test_build_daily_schedule_honors_arrival_window_override -v
```

Expected: `TypeError: build_daily_schedule() got an unexpected keyword argument 'arrival_window'`.

- [ ] **Step 3: Update `monthly_schedule/daily_schedule.py`**

Find `build_daily_schedule` and replace its signature/body with:

```python
def build_daily_schedule(rules, rng, arrival_window=None):
    """Return a dict of 'HH:MM' strings for one eligible day's visit.

    `arrival_window` (optional) is a (lo_minutes, hi_minutes) tuple that
    overrides the plan's default arrival_window. Used by the per-day
    eligibility flow to honor Availability rules."""
    if arrival_window is None:
        a_lo, a_hi = (parse_hhmm(x) for x in rules["arrival_window"])
    else:
        a_lo, a_hi = arrival_window
    step = rules["round_to_minutes"]

    arrival = _round_to(rng.randint(a_lo, a_hi), step)
    span = rng.randint(*rules["session_span_min"])
    departure = arrival + span

    pickup = arrival - rng.randint(*rules["pickup_lead_min"])
    dropoff = departure + rng.randint(*rules["dropoff_trail_min"])
    time_in = arrival + rng.randint(*rules["time_in_drift_min"])
    time_out = departure - rng.randint(*rules["time_out_drift_min"])

    validate_schedule(
        pickup, arrival, time_in, time_out, departure, dropoff, rules
    )

    return {
        "pickup": format_minutes(pickup),
        "arrival": format_minutes(arrival),
        "time_in": format_minutes(time_in),
        "time_out": format_minutes(time_out),
        "departure": format_minutes(departure),
        "dropoff": format_minutes(dropoff),
    }
```

- [ ] **Step 4: Run all daily_schedule tests**

```powershell
.venv\Scripts\pytest tests/test_daily_schedule.py -v
```

Expected: all pre-existing tests pass plus the new one.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/daily_schedule.py tests/test_daily_schedule.py
git commit -m "feat(daily_schedule): accept optional arrival_window override"
```

---

## Task 5: `build_rows` accepts MemberContext and plan_rules

**Files:**
- Modify: `monthly_schedule/rows.py`
- Modify: `tests/test_rows.py`

This is the trickiest task — `build_rows` is currently called with `(year, month, authorized_weekdays, rules, rng, exclusions=None)` and we change it to `(year, month, ctx, plan_rules, rng)`. The old signature must be removed; callers (only `new_monthly_schedule.process_member`) get updated in Task 6.

- [ ] **Step 1: Read the existing test_rows.py to understand its expectations**

```powershell
Get-Content tests/test_rows.py | Select-Object -First 100
```

You'll see tests that pass `authorized_weekdays` as a set. Those tests are about which days get times vs blank, which is now MemberContext's job. We'll re-express them.

- [ ] **Step 2: Replace `tests/test_rows.py`**

Overwrite `tests/test_rows.py` with:

```python
import random
from datetime import date

from monthly_schedule.eligibility_context import MemberContext
from monthly_schedule.rows import build_rows


PLAN_RULES = {
    "arrival_window": ("08:00", "11:00"),
    "session_span_min": (210, 245),
    "pickup_lead_min": (8, 12),
    "dropoff_trail_min": (8, 12),
    "time_in_drift_min": (2, 2),
    "time_out_drift_min": (2, 2),
    "round_to_minutes": 1,
    "travel_buffer_min": (1, 5),
}


def _ctx_full_month(authorized="1,3,5"):
    return MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": authorized}],
        absences=[],
        availabilities=[],
    )


def test_build_rows_one_row_per_day():
    rows = build_rows(2026, 5, _ctx_full_month(), PLAN_RULES, random.Random(0))
    assert len(rows) == 31


def test_build_rows_row_shape():
    rows = build_rows(2026, 5, _ctx_full_month(), PLAN_RULES, random.Random(0))
    keys = set(rows[0].keys())
    assert keys == {"date", "day", "pickup", "arrival",
                    "time_in", "time_out", "departure", "dropoff"}


def test_unauthorized_days_have_blank_times():
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"),
                      PLAN_RULES, random.Random(0))
    # 2026-05-02 is Saturday (isoweekday 6) → not in "1,3,5"
    sat = next(r for r in rows if r["date"] == date(2026, 5, 2))
    assert sat["pickup"] == "" and sat["arrival"] == ""


def test_authorized_days_have_times():
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"),
                      PLAN_RULES, random.Random(0))
    # 2026-05-04 is Monday (isoweekday 1) → in "1,3,5"
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["pickup"] != "" and mon["arrival"] != ""


def test_absence_blocks_an_authorized_day():
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[{"id": 1, "center_id": 1, "leave_type": "Vacation",
                   "start_date": date(2026, 5, 4),
                   "end_date": date(2026, 5, 4)}],
        availabilities=[],
    )
    rows = build_rows(2026, 5, ctx, PLAN_RULES, random.Random(0))
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["pickup"] == ""  # blocked by absence


def test_availability_window_honored():
    avail = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": None,
             "day_of_week": 1,
             "avail_start": "10:00", "avail_end": "15:00"}
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[],
        availabilities=[avail],
    )
    rows = build_rows(2026, 5, ctx, PLAN_RULES, random.Random(0))
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    # Arrival should fall within the narrowed 10:00–10:30 window
    h, m = mon["arrival"].split(":")
    arrival_min = int(h) * 60 + int(m)
    assert 600 <= arrival_min <= 660
```

- [ ] **Step 3: Replace `monthly_schedule/rows.py`**

Overwrite with:

```python
"""Assemble the per-day rows that feed both workbook tables."""

from monthly_schedule.month_dates import get_month_dates
from monthly_schedule.per_day import compute_day_eligibility
from monthly_schedule.daily_schedule import build_daily_schedule

DAY_ABBR = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
TIME_KEYS = ("pickup", "arrival", "time_in", "time_out", "departure", "dropoff")


def build_rows(year, month, ctx, plan_rules, rng):
    """Return a list of row dicts (one per calendar day).

    `ctx` is a MemberContext from monthly_schedule.eligibility_context.
    `plan_rules` is the dict returned by get_rules_for_plan().

    Ineligible days have '' for every time key. Eligible days are filled
    via build_daily_schedule, honoring any narrowed arrival window the
    member's Availability rule imposes."""
    rows = []
    for day in get_month_dates(year, month):
        row = {"date": day, "day": DAY_ABBR[day.isoweekday()]}
        result = compute_day_eligibility(day, ctx, plan_rules)
        if result.eligible:
            row.update(build_daily_schedule(
                plan_rules, rng, arrival_window=result.arrival_window
            ))
        else:
            for key in TIME_KEYS:
                row[key] = ""
        rows.append(row)
    return rows
```

- [ ] **Step 4: Run rows tests**

```powershell
.venv\Scripts\pytest tests/test_rows.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/rows.py tests/test_rows.py
git commit -m "feat(rows): build_rows uses MemberContext + per-day eligibility"
```

---

## Task 6: Refactor `process_member` to use MemberContext

**Files:**
- Modify: `new_monthly_schedule.py`
- Modify: `tests/test_cli.py`

`process_member`'s contract changes. New signature:

```python
def process_member(member, ctx, year, month, out_dir, preview, api_key, cache)
```

The new `ctx` parameter is a MemberContext. The caller (CLI `main()` and worker.py) is responsible for building it via the new DB queries. The old `member["auth_days"]` is no longer consulted.

- [ ] **Step 1: Update `tests/test_cli.py` fixtures and add a MemberContext factory**

In `tests/test_cli.py`, change `FAKE_MEMBER` and `FAKE_MEMBER_2`:

```python
FAKE_MEMBER = {
    "center_id": 24010,
    "last_name": "Cheng",
    "first_name": "Lizhu",
    "health_plan": "HOF",
    "address": "1 Main St, NY",
    "long_lat": None,
}

FAKE_MEMBER_2 = {
    "center_id": 24011,
    "last_name": "Smith",
    "first_name": "John",
    "health_plan": "HOF",
    "address": "2 Main St, NY",
    "long_lat": None,
}
```

(Removed the `auth_days` key.)

Add this helper at the top of the file (after the imports, before fixtures):

```python
from datetime import date


def _fake_enrollments(cid=24010):
    return [{"id": 1, "center_id": cid,
             "start_date": date(2026, 1, 1), "end_date": None}]


def _fake_authorizations(cid=24010, auth_days="1.3.4.5"):
    return [{"id": 1, "center_id": cid,
             "auth_start": date(2026, 1, 1),
             "auth_end": date(2026, 12, 31),
             "effective_start": date(2026, 1, 1),
             "effective_end": date(2026, 12, 31),
             "auth_days": auth_days}]
```

Update the `_stub_travel` autouse fixture to also stub the four new DB calls:

```python
@pytest.fixture(autouse=True)
def _stub_travel(monkeypatch):
    """Neutralize travel + new DB lookups for legacy tests."""
    monkeypatch.setattr(cli, "load_api_key", lambda path: "K")
    monkeypatch.setattr(cli, "load_cache", lambda path: {})
    monkeypatch.setattr(cli, "save_cache", lambda path, cache: None)
    monkeypatch.setattr(
        cli, "resolve_travel_minutes",
        lambda member, api_key, cache: 10,
    )
    monkeypatch.setattr(
        cli, "get_enrollments",
        lambda cid, db: _fake_enrollments(cid),
    )
    monkeypatch.setattr(
        cli, "get_authorizations",
        lambda cid, db: _fake_authorizations(cid),
    )
    monkeypatch.setattr(cli, "get_absences", lambda cid, db: [])
    monkeypatch.setattr(cli, "get_availability", lambda cid, db: [])
```

- [ ] **Step 2: Add a new test for the whole-member failure path**

Append to `tests/test_cli.py`:

```python
def test_no_enrollment_yields_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    monkeypatch.setattr(cli, "get_enrollments", lambda cid, db: [])
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "eligibility — not enrolled during this month" in err


def test_no_authorization_yields_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    monkeypatch.setattr(cli, "get_authorizations", lambda cid, db: [])
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "eligibility — no active authorization for this month" in err
```

- [ ] **Step 3: Run the CLI tests to verify they fail**

```powershell
.venv\Scripts\pytest tests/test_cli.py -v
```

Expected: many failures because (a) `cli.get_enrollments` etc. don't exist yet as attributes of the module, (b) `process_member` doesn't yet take `ctx`. That's expected — implementation comes next.

- [ ] **Step 4: Update `new_monthly_schedule.py`**

Replace the existing imports block (top of file) — add the new functions:

```python
from monthly_schedule.db import (
    get_member, get_members_by_plan,
    get_enrollments, get_authorizations, get_absences, get_availability,
)
```

Remove this line if present:
```python
from monthly_schedule.auth_days import get_authorized_weekdays
```

Add (near the top, after the import block and before `DEFAULT_DB`):

```python
from monthly_schedule.eligibility_context import MemberContext
from monthly_schedule.per_day import compute_month_failure
```

Replace the `process_member` function with:

```python
def process_member(member, ctx, year, month, out_dir, preview,
                   api_key, cache):
    """Run the per-member pipeline. Returns (ok, stage, reason).
    On success ok is True and stage/reason are None. On failure
    stage is one of 'eligibility'/'geocode'/'route'/'generate'/'write'
    with the reason."""
    failure = compute_month_failure(year, month, ctx)
    if failure is not None:
        return (False, "eligibility", failure)

    try:
        travel_minutes = resolve_travel_minutes(member, api_key, cache)
    except TravelError as exc:
        return (False, exc.stage, exc.reason)

    rng = random.Random()
    try:
        rules = dict(get_rules_for_plan(member["health_plan"]))
        buf_lo, buf_hi = rules.get("travel_buffer_min", (5, 15))
        rules["pickup_lead_min"] = (travel_minutes + buf_lo,
                                    travel_minutes + buf_hi)
        rules["dropoff_trail_min"] = (travel_minutes + buf_lo,
                                      travel_minutes + buf_hi)
        rows = build_rows(year, month, ctx, rules, rng)
    except Exception as exc:  # reported in the run summary
        return (False, "generate", f"{type(exc).__name__} — {exc}")

    if preview:
        print(
            f"=== ID {member['center_id']} "
            f"({member['last_name']}, {member['first_name']}) ==="
        )
        for row in rows:
            print({**row, "date": str(row["date"])})
        return (True, None, None)

    path = os.path.join(
        out_dir, schedule_filename(member["center_id"], year, month)
    )
    try:
        build_workbook(member, rows, path)
    except Exception as exc:  # reported in the run summary
        return (False, "write", f"{type(exc).__name__} — {exc}")
    print(f"Wrote {path}")
    return (True, None, None)
```

The previous code's call to `get_authorized_weekdays(member["auth_days"])` is gone — eligibility now flows through `ctx`.

Also delete the line that used to read `member["auth_days"]`. Update `main()` to build the ctx and pass it:

Locate the per-member loop inside `main()` (currently around `for member in members:`) and replace it with:

```python
    success = 0
    for member in members:
        ctx = MemberContext(
            enrollments=get_enrollments(member["center_id"], args.db_path),
            authorizations=get_authorizations(member["center_id"], args.db_path),
            absences=get_absences(member["center_id"], args.db_path),
            availabilities=get_availability(member["center_id"], args.db_path),
        )
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

- [ ] **Step 5: Run CLI tests**

```powershell
.venv\Scripts\pytest tests/test_cli.py -v
```

Expected: all CLI tests pass including the two new failure-path tests.

- [ ] **Step 6: Commit**

```bash
git add new_monthly_schedule.py tests/test_cli.py
git commit -m "feat(scheduler): process_member uses MemberContext

Each member's ctx is built from the four new tables before process_member
runs. compute_month_failure surfaces whole-member failures (not enrolled
/ no auth / absent for entire month) under the new 'eligibility' stage."
```

---

## Task 7: GUI worker builds MemberContext per member

**Files:**
- Modify: `gui/worker.py`

The worker mirrors the CLI's per-member loop. Same change.

- [ ] **Step 1: Update `gui/worker.py` imports**

Find the existing import block. Replace:

```python
from monthly_schedule.db import get_member, get_members_by_plan
```

with:

```python
from monthly_schedule.db import (
    get_member, get_members_by_plan,
    get_enrollments, get_authorizations, get_absences, get_availability,
)
from monthly_schedule.eligibility_context import MemberContext
```

- [ ] **Step 2: Update the per-member loop**

Find the `for i, member in enumerate(members):` loop in `ScheduleWorker.run` and replace its ENTIRE body with:

```python
        for i, member in enumerate(members):
            ctx = MemberContext(
                enrollments=get_enrollments(member["center_id"], self.db_path),
                authorizations=get_authorizations(member["center_id"], self.db_path),
                absences=get_absences(member["center_id"], self.db_path),
                availabilities=get_availability(member["center_id"], self.db_path),
            )
            ok, stage, reason = process_member(
                member, ctx,
                self.year, self.month, self.out_dir,
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

(The only changes from the existing loop are the new `ctx = ...` build and the additional `ctx` positional arg in the `process_member` call.)

- [ ] **Step 3: Verify the worker imports cleanly + tests still pass**

```powershell
.venv\Scripts\python.exe -c "from PyQt6.QtWidgets import QApplication; import sys; app = QApplication(sys.argv); from gui.worker import ScheduleWorker; print('OK')"
.venv\Scripts\pytest -v
```

Expected: import prints `OK`; all tests pass.

- [ ] **Step 4: Commit**

```bash
git add gui/worker.py
git commit -m "feat(gui): worker builds MemberContext per member"
```

---

## Task 8: Drop `[SADC]` from `MEMBER_QUERY` and `MEMBERS_BY_PLAN_QUERY`

**Files:**
- Modify: `monthly_schedule/db.py`
- Modify: `tests/test_db.py`

The Contacts column `SADC` stays in Access, but the scheduler no longer reads it. `auth_days` disappears from the member dict.

- [ ] **Step 1: Update `tests/test_db.py`**

In the existing `test_member_query_columns_and_filter` test, replace:

```python
    assert "[SADC]" in MEMBER_QUERY
```

with:

```python
    assert "[SADC]" not in MEMBER_QUERY
```

Same change in `test_members_by_plan_query_columns_and_filter` — replace the `[SADC]` assertion with the `not in` variant.

In `test_map_member_row`, replace the test body with:

```python
def test_map_member_row():
    # Access returns [Center ID] as a float; normalize to int.
    row = (24010.0, "Cheng", "Lizhu", "Elderplan Homefirst",
           "1 Main St, NY", "40.71,-73.99")
    result = map_member_row(row)
    assert result == {
        "center_id": 24010,
        "last_name": "Cheng",
        "first_name": "Lizhu",
        "health_plan": "Elderplan Homefirst",
        "address": "1 Main St, NY",
        "long_lat": "40.71,-73.99",
    }
```

(Removed `"1.3.4.5"` from the row tuple and `auth_days` from the expected dict.)

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
.venv\Scripts\pytest tests/test_db.py -v
```

Expected: the three updated tests fail because `MEMBER_QUERY` still includes `[SADC]`.

- [ ] **Step 3: Update `monthly_schedule/db.py`**

Replace `MEMBER_QUERY`:

```python
MEMBER_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[Address], [Long Lat] FROM [Contacts] "
    "WHERE [Center ID] = ?"
)
```

Replace `MEMBERS_BY_PLAN_QUERY`:

```python
MEMBERS_BY_PLAN_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[Address], [Long Lat] FROM [Contacts] "
    "WHERE [Health Plan] = ? ORDER BY [Center ID]"
)
```

Replace `map_member_row`:

```python
def map_member_row(row):
    return {
        # Access returns [Center ID] as a float; normalize to int.
        "center_id": int(row[0]),
        "last_name": row[1],
        "first_name": row[2],
        "health_plan": row[3],
        "address": row[4],
        "long_lat": row[5],
    }
```

- [ ] **Step 4: Run all tests**

```powershell
.venv\Scripts\pytest -v
```

Expected: full suite passes.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/db.py tests/test_db.py
git commit -m "refactor(db): stop selecting Contacts.SADC; auth_days lives on Authorization rows"
```

---

## Task 9: Translate the new failure reasons in the GUI

**Files:**
- Modify: `gui/i18n.py`
- Modify: `gui/main_window.py`

The worker emits failures with stage `"eligibility"` and one of three reason constants. The GUI's `_build_summary` already translates known reasons; we add the new ones.

- [ ] **Step 1: Add 4 new keys to both language tables**

In `gui/i18n.py`, find `STRINGS["en"]` and add (near the existing `summary.stage.*` and `summary.reason.*` entries):

```python
        "summary.stage.eligibility": "eligibility",
        "summary.reason.not_enrolled": "not enrolled during this month",
        "summary.reason.no_auth": "no active authorization for this month",
        "summary.reason.absent_month": "absent for the entire month",
```

In `STRINGS["zh"]`, add the matching keys (with the same order is fine):

```python
        "summary.stage.eligibility": "资格",
        "summary.reason.not_enrolled": "本月未入册",
        "summary.reason.no_auth": "本月无有效授权",
        "summary.reason.absent_month": "整月缺席",
```

- [ ] **Step 2: Run the i18n parity test to confirm both tables match**

```powershell
.venv\Scripts\pytest tests/test_i18n.py -v
```

Expected: all 7 tests still pass (parity holds).

- [ ] **Step 3: Update `gui/main_window.py` `_build_summary`**

Find `_build_summary`. Locate the block that maps `f["reason"] == REASON_NOT_FOUND` to a translation. Replace it with the multi-reason version:

```python
            stage = tr(f"summary.stage.{f['stage']}")
            reason = _translate_reason(f["reason"])
```

And add this helper at module scope (top of file, after the imports — and add `from monthly_schedule.per_day import REASON_NOT_ENROLLED, REASON_NO_AUTH, REASON_ABSENT_MONTH` to the imports):

```python
def _translate_reason(reason: str) -> str:
    if reason == REASON_NOT_FOUND:
        return tr("summary.reason.not_found")
    if reason == REASON_NOT_ENROLLED:
        return tr("summary.reason.not_enrolled")
    if reason == REASON_NO_AUTH:
        return tr("summary.reason.no_auth")
    if reason == REASON_ABSENT_MONTH:
        return tr("summary.reason.absent_month")
    return reason
```

- [ ] **Step 4: Verify imports + run tests + smoke-launch**

```powershell
.venv\Scripts\python.exe -c "from PyQt6.QtWidgets import QApplication; import sys; app = QApplication(sys.argv); from gui.main_window import MainWindow; w = MainWindow(); print('OK')"
.venv\Scripts\pytest -v
```

Expected: import prints `OK`; full suite passes.

- [ ] **Step 5: Commit**

```bash
git add gui/i18n.py gui/main_window.py
git commit -m "feat(gui): translate eligibility-stage failure reasons (EN/ZH)"
```

---

## Self-Review Checklist (for the implementer)

Before declaring complete:

- [ ] `pytest -v` is green (target: 127+ tests including the new ones).
- [ ] `new_monthly_schedule.py` no longer imports `get_authorized_weekdays` directly (it's only used inside `per_day.py` now).
- [ ] No remaining references to `member["auth_days"]` in `gui/*` or `new_monthly_schedule.py`. Grep to confirm.
- [ ] `MEMBER_QUERY` and `MEMBERS_BY_PLAN_QUERY` don't contain `[SADC]`. Grep to confirm.
- [ ] `STRINGS["en"]` and `STRINGS["zh"]` have identical key sets (the parity test enforces this).
- [ ] Manual smoke: launch the GUI in Chinese, deliberately blank out a member's enrollment in Access, run a schedule, and confirm the failure row reads in Chinese with `资格 — 本月未入册` (or equivalent).
- [ ] Rebuild the exe via `.venv\Scripts\pyinstaller.exe MonthlyScheduleGenerator.spec --noconfirm` and confirm the new build launches and a schedule run still works end-to-end (with a real Access DB).
