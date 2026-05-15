# Monthly Schedule Workbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI that reads one SADC member from the Access DB and writes a printable two-table Excel workbook (attendance + transportation) for one month, with placeholder time generation behind extendable rule and day-eligibility seams.

**Architecture:** Pure logic lives in small focused modules under a `monthly_schedule/` package (auth-day parsing, month dates, eligibility, rules, daily schedule, row assembly, DB access, workbook rendering). A thin root script `new_monthly_schedule.py` wires them together via argparse. Every pure module is unit-tested with pytest; DB and Excel I/O are factored so their pure parts are testable and the thin I/O shell is verified by round-trip/manual checks.

**Tech Stack:** Python 3, `pyodbc` (Access ODBC), `openpyxl` (`.xlsx`), `pytest`.

**Spec:** `docs/superpowers/specs/2026-05-15-monthly-schedule-design.md`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `requirements.txt` | Pin `pyodbc`, `openpyxl`, `pytest` |
| `conftest.py` | Empty — anchors pytest rootdir at repo root |
| `monthly_schedule/__init__.py` | Package marker |
| `monthly_schedule/auth_days.py` | Parse `SADC Auth` string → set of weekday ints (1=Mon..7=Sun) |
| `monthly_schedule/month_dates.py` | All `date`s in a given year/month |
| `monthly_schedule/eligibility.py` | `Exclusions` dataclass + `is_day_eligible` seam |
| `monthly_schedule/rules.py` | `SCHEDULE_RULES`, per-plan resolver, HH:MM helpers |
| `monthly_schedule/daily_schedule.py` | Generate one coherent day's times + post-gen assertion |
| `monthly_schedule/rows.py` | Combine month dates + eligibility + daily schedule into rows |
| `monthly_schedule/db.py` | pyodbc connection string, query, row mapping, `get_member` |
| `monthly_schedule/workbook.py` | openpyxl rendering of the two-table workbook |
| `new_monthly_schedule.py` | argparse CLI entry / orchestration |
| `tests/test_*.py` | One test module per pure module |

**All test commands are run from the repo root as `python -m pytest ...`** so the repo root is on `sys.path` (both the `monthly_schedule` package and the root `new_monthly_schedule` module import cleanly).

---

## Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `conftest.py`
- Create: `monthly_schedule/__init__.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

`tests/test_smoke.py`:

```python
def test_package_imports():
    import monthly_schedule  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monthly_schedule'`

- [ ] **Step 3: Create the scaffolding**

`requirements.txt`:

```
pyodbc==5.2.0
openpyxl==3.1.5
pytest==8.3.3
```

(Pin corrected from 5.1.0 → 5.2.0 during execution: 5.1.0 has no
Python 3.13 wheel; 5.2.0 ships `cp313` wheels and installs without a
compiler.)

`conftest.py`:

```python
# Empty: anchors the pytest rootdir at the repository root so that
# `monthly_schedule` (package) and `new_monthly_schedule` (module) import.
```

`monthly_schedule/__init__.py`:

```python
"""Monthly schedule workbook generator."""
```

- [ ] **Step 4: Install dependencies and run the test to verify it passes**

Run: `python -m pip install -r requirements.txt`
Then: `python -m pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt conftest.py monthly_schedule/__init__.py tests/test_smoke.py
git commit -m "chore: scaffold monthly_schedule package and test setup"
```

---

## Task 2: Auth-day parsing

**Files:**
- Create: `monthly_schedule/auth_days.py`
- Test: `tests/test_auth_days.py`

Encoding (from spec §3): 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat, 7=Sun — matches Python `date.isoweekday()`. Any non-digit is a separator; values outside 1–7 are discarded; empty/None → empty set.

- [ ] **Step 1: Write the failing test**

`tests/test_auth_days.py`:

```python
import pytest

from monthly_schedule.auth_days import get_authorized_weekdays


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.3.4.5", {1, 3, 4, 5}),
        ("1,3,4,5", {1, 3, 4, 5}),
        ("1 3 4 5", {1, 3, 4, 5}),
        ("", set()),
        (None, set()),
        ("0.8.9", set()),          # all out of range -> discarded
        ("1.2.3.4.5.6.7", {1, 2, 3, 4, 5, 6, 7}),
        ("garbage", set()),
        ("3", {3}),
    ],
)
def test_get_authorized_weekdays(raw, expected):
    assert get_authorized_weekdays(raw) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auth_days.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monthly_schedule.auth_days'`

- [ ] **Step 3: Write minimal implementation**

`monthly_schedule/auth_days.py`:

```python
"""Parse the Access `SADC Auth` field into a set of weekday numbers.

Encoding: 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat, 7=Sun
(matches datetime.date.isoweekday()).
"""

import re


def get_authorized_weekdays(sadc_auth):
    """Return the set of authorized weekday ints (1-7) parsed from the
    raw `SADC Auth` value. Non-digits are separators; values outside
    1-7 are discarded; None/empty/unparseable -> empty set."""
    if not sadc_auth:
        return set()
    found = re.findall(r"\d+", str(sadc_auth))
    return {n for n in (int(x) for x in found) if 1 <= n <= 7}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_auth_days.py -v`
Expected: PASS (9 cases)

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/auth_days.py tests/test_auth_days.py
git commit -m "feat: parse SADC Auth into authorized weekday set"
```

---

## Task 3: Month dates

**Files:**
- Create: `monthly_schedule/month_dates.py`
- Test: `tests/test_month_dates.py`

- [ ] **Step 1: Write the failing test**

`tests/test_month_dates.py`:

```python
from datetime import date

from monthly_schedule.month_dates import get_month_dates


def test_31_day_month():
    days = get_month_dates(2026, 5)
    assert days[0] == date(2026, 5, 1)
    assert days[-1] == date(2026, 5, 31)
    assert len(days) == 31


def test_30_day_month():
    days = get_month_dates(2026, 4)
    assert days[-1] == date(2026, 4, 30)
    assert len(days) == 30


def test_february_non_leap():
    days = get_month_dates(2026, 2)
    assert days[-1] == date(2026, 2, 28)
    assert len(days) == 28


def test_february_leap():
    days = get_month_dates(2024, 2)
    assert days[-1] == date(2024, 2, 29)
    assert len(days) == 29
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_month_dates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monthly_schedule.month_dates'`

- [ ] **Step 3: Write minimal implementation**

`monthly_schedule/month_dates.py`:

```python
"""Produce every calendar date in a given year/month."""

import calendar
from datetime import date


def get_month_dates(year, month):
    """Return a list of date objects from the 1st through the last
    day of the given year/month, inclusive."""
    last_day = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, last_day + 1)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_month_dates.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/month_dates.py tests/test_month_dates.py
git commit -m "feat: enumerate all dates in a month"
```

---

## Task 4: Day eligibility seam

**Files:**
- Create: `monthly_schedule/eligibility.py`
- Test: `tests/test_eligibility.py`

Implements spec §4a. `exclusions=None` (default) → weekday check only. Termination semantics (spec): a termination date makes that date **and every later date** ineligible. Vacation ranges are inclusive on both ends.

- [ ] **Step 1: Write the failing test**

`tests/test_eligibility.py`:

```python
from datetime import date

from monthly_schedule.eligibility import Exclusions, is_day_eligible

AUTH = {1, 3, 4, 5}  # Mon, Wed, Thu, Fri


def test_authorized_weekday_no_exclusions():
    # 2026-05-01 is a Friday (isoweekday 5)
    assert is_day_eligible(date(2026, 5, 1), AUTH) is True


def test_unauthorized_weekday():
    # 2026-05-02 is a Saturday (isoweekday 6) -> not in AUTH
    assert is_day_eligible(date(2026, 5, 2), AUTH) is False


def test_none_exclusions_equivalent_to_empty():
    assert is_day_eligible(date(2026, 5, 1), AUTH, None) is True


def test_vacation_range_blocks_authorized_day():
    exc = Exclusions(ranges=((date(2026, 5, 10), date(2026, 5, 16)),))
    # 2026-05-11 is a Monday (authorized) but inside the vacation range
    assert is_day_eligible(date(2026, 5, 11), AUTH, exc) is False
    # boundary days are inclusive
    assert is_day_eligible(date(2026, 5, 16), {6}, Exclusions(
        ranges=((date(2026, 5, 10), date(2026, 5, 16)),))) is False


def test_termination_blocks_date_and_after():
    exc = Exclusions(termination_date=date(2026, 5, 10))
    # 2026-05-08 is a Friday (authorized), before termination -> eligible
    assert is_day_eligible(date(2026, 5, 8), AUTH, exc) is True
    # 2026-05-11 Monday (authorized) on/after termination -> ineligible
    assert is_day_eligible(date(2026, 5, 11), AUTH, exc) is False
    # the termination day itself is ineligible (2026-05-11 is Mon; pick
    # an authorized termination day): 2026-05-13 is a Wednesday
    exc2 = Exclusions(termination_date=date(2026, 5, 13))
    assert is_day_eligible(date(2026, 5, 13), AUTH, exc2) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_eligibility.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monthly_schedule.eligibility'`

- [ ] **Step 3: Write minimal implementation**

`monthly_schedule/eligibility.py`:

```python
"""The single seam deciding whether a date should get generated times.

Today it checks only the authorized-weekday rule. The optional
`exclusions` argument is the future plug-in point for vacation ranges,
termination dates, auth-period limits, and other visit types
(spec §4a). With the default empty exclusions, behavior is unchanged.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Tuple


@dataclass(frozen=True)
class Exclusions:
    """ranges: tuple of (start_date, end_date) inclusive vacation ranges.
    termination_date: if set, this date and all later dates are ineligible."""

    ranges: Tuple[Tuple[date, date], ...] = field(default_factory=tuple)
    termination_date: Optional[date] = None


def is_day_eligible(day, authorized_weekdays, exclusions=None):
    """Return True if `day` should get generated times."""
    if day.isoweekday() not in authorized_weekdays:
        return False
    if exclusions is None:
        return True
    if (
        exclusions.termination_date is not None
        and day >= exclusions.termination_date
    ):
        return False
    for start, end in exclusions.ranges:
        if start <= day <= end:
            return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_eligibility.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/eligibility.py tests/test_eligibility.py
git commit -m "feat: day-eligibility seam with exclusions default"
```

---

## Task 5: Schedule rules + HH:MM helpers

**Files:**
- Create: `monthly_schedule/rules.py`
- Test: `tests/test_rules.py`

Implements spec §4b: rules object keyed by `Health Plan` with a `"Default"`, plus `parse_hhmm`/`format_minutes` helpers used by the daily-schedule generator.

- [ ] **Step 1: Write the failing test**

`tests/test_rules.py`:

```python
from monthly_schedule.rules import (
    SCHEDULE_RULES,
    get_rules_for_plan,
    parse_hhmm,
    format_minutes,
)


def test_parse_hhmm():
    assert parse_hhmm("08:05") == 8 * 60 + 5
    assert parse_hhmm("00:00") == 0
    assert parse_hhmm("12:25") == 745


def test_format_minutes():
    assert format_minutes(0) == "00:00"
    assert format_minutes(8 * 60 + 5) == "08:05"
    assert format_minutes(745) == "12:25"
    assert format_minutes(24 * 60) == "00:00"  # wraps within a day


def test_default_rules_present_and_shaped():
    d = SCHEDULE_RULES["Default"]
    assert d["arrival_window"] == ("08:05", "08:25")
    assert d["departure_window"] == ("12:05", "12:25")
    assert d["min_session_hours"] == 3
    assert d["max_session_hours"] == 6
    assert d["round_to_minutes"] == 1


def test_get_rules_for_plan_falls_back_to_default():
    assert get_rules_for_plan("Elderplan Homefirst") is SCHEDULE_RULES["Default"]
    assert get_rules_for_plan(None) is SCHEDULE_RULES["Default"]
    assert get_rules_for_plan("") is SCHEDULE_RULES["Default"]


def test_get_rules_for_plan_uses_specific_entry(monkeypatch):
    monkeypatch.setitem(SCHEDULE_RULES, "SpecialPlan", {"marker": True})
    assert get_rules_for_plan("SpecialPlan") == {"marker": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monthly_schedule.rules'`

- [ ] **Step 3: Write minimal implementation**

`monthly_schedule/rules.py`:

```python
"""Tunable, per-plan time-generation rules (spec §4b).

Adding a restriction = change a number here, or add a key and one
clamp/validation line in daily_schedule.validate_schedule.
"""

SCHEDULE_RULES = {
    "Default": {
        "arrival_window": ("08:05", "08:25"),
        "departure_window": ("12:05", "12:25"),
        "min_session_hours": 3,
        "max_session_hours": 6,
        "pickup_lead_min": (8, 12),     # minutes before Arrival
        "dropoff_trail_min": (8, 12),   # minutes after Departure
        "time_in_drift_min": (0, 3),    # Time-In after Arrival
        "time_out_drift_min": (0, 3),   # Time-Out before Departure
        "round_to_minutes": 1,          # 1 = no snap; 5 = snap to :05
    },
}


def get_rules_for_plan(health_plan):
    """Return the rules dict for the member's plan, falling back to
    'Default' when the plan has no specific entry."""
    if health_plan and health_plan in SCHEDULE_RULES:
        return SCHEDULE_RULES[health_plan]
    return SCHEDULE_RULES["Default"]


def parse_hhmm(text):
    """'HH:MM' -> minutes since midnight."""
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def format_minutes(total):
    """Minutes since midnight -> 'HH:MM' (wraps within a 24h day)."""
    total %= 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_rules.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/rules.py tests/test_rules.py
git commit -m "feat: per-plan schedule rules and HH:MM helpers"
```

---

## Task 6: Daily schedule generation + post-generation assertion

**Files:**
- Create: `monthly_schedule/daily_schedule.py`
- Test: `tests/test_daily_schedule.py`

Implements spec §4b. A `random.Random` instance is injected for deterministic tests. Only the anchor times (Arrival, Departure) are snapped by `round_to_minutes`; the derived offsets stay exact so the ordering invariant cannot be broken by rounding.

- [ ] **Step 1: Write the failing test**

`tests/test_daily_schedule.py`:

```python
import random

import pytest

from monthly_schedule.rules import SCHEDULE_RULES, parse_hhmm
from monthly_schedule.daily_schedule import build_daily_schedule, validate_schedule


def _to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def test_default_rules_produce_valid_ordering():
    rng = random.Random(42)
    for _ in range(200):
        s = build_daily_schedule(SCHEDULE_RULES["Default"], rng)
        pu, ar, ti = _to_min(s["pickup"]), _to_min(s["arrival"]), _to_min(s["time_in"])
        to, de, do = _to_min(s["time_out"]), _to_min(s["departure"]), _to_min(s["dropoff"])
        assert pu < ar <= ti
        assert to <= de < do
        session_h = (de - ar) / 60
        assert 3 <= session_h <= 6


def test_keys_present():
    rng = random.Random(1)
    s = build_daily_schedule(SCHEDULE_RULES["Default"], rng)
    assert set(s) == {
        "pickup", "arrival", "time_in", "time_out", "departure", "dropoff"
    }


def test_tight_window_with_5_minute_snap():
    rng = random.Random(7)
    rules = {
        "arrival_window": ("08:02", "08:08"),
        "departure_window": ("12:01", "12:09"),
        "min_session_hours": 3,
        "max_session_hours": 6,
        "pickup_lead_min": (8, 12),
        "dropoff_trail_min": (8, 12),
        "time_in_drift_min": (0, 3),
        "time_out_drift_min": (0, 3),
        "round_to_minutes": 5,
    }
    for _ in range(100):
        s = build_daily_schedule(rules, rng)
        ar, de = _to_min(s["arrival"]), _to_min(s["departure"])
        assert ar % 5 == 0
        assert de % 5 == 0
        assert _to_min(s["pickup"]) < ar
        assert de < _to_min(s["dropoff"])


def test_validate_schedule_raises_on_bad_ordering():
    rules = SCHEDULE_RULES["Default"]
    with pytest.raises(ValueError):
        # pickup not before arrival
        validate_schedule(500, 480, 481, 700, 720, 730, rules)


def test_validate_schedule_raises_on_session_length():
    rules = SCHEDULE_RULES["Default"]
    with pytest.raises(ValueError):
        # 30-minute session, below min_session_hours
        validate_schedule(470, 480, 480, 510, 510, 520, rules)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_daily_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monthly_schedule.daily_schedule'`

- [ ] **Step 3: Write minimal implementation**

`monthly_schedule/daily_schedule.py`:

```python
"""Generate one coherent daily schedule and assert its invariants.

The two output tables (attendance + transportation) are both derived
from the same Arrival/Departure anchors so they stay mutually
consistent (spec §4b). Only the anchors are snapped by
`round_to_minutes`; derived offsets stay exact so the ordering
invariant cannot be broken by rounding.
"""

from monthly_schedule.rules import parse_hhmm, format_minutes


def _round_to(value, step):
    if step <= 1:
        return value
    return int(round(value / step)) * step


def validate_schedule(pickup, arrival, time_in, time_out, departure, dropoff, rules):
    """Raise ValueError if the generated minutes violate ordering or
    the configured session-length bounds (spec §4b)."""
    if not (pickup < arrival <= time_in):
        raise ValueError(
            f"Start ordering violated: pickup={pickup} arrival={arrival} "
            f"time_in={time_in}"
        )
    if not (time_out <= departure < dropoff):
        raise ValueError(
            f"End ordering violated: time_out={time_out} "
            f"departure={departure} dropoff={dropoff}"
        )
    session_hours = (departure - arrival) / 60
    lo = rules["min_session_hours"]
    hi = rules["max_session_hours"]
    if not (lo <= session_hours <= hi):
        raise ValueError(
            f"Session length {session_hours}h outside [{lo}, {hi}]"
        )


def build_daily_schedule(rules, rng):
    """Return a dict of 'HH:MM' strings for one eligible day's visit."""
    a_lo, a_hi = (parse_hhmm(x) for x in rules["arrival_window"])
    d_lo, d_hi = (parse_hhmm(x) for x in rules["departure_window"])
    step = rules["round_to_minutes"]

    arrival = _round_to(rng.randint(a_lo, a_hi), step)
    departure = _round_to(rng.randint(d_lo, d_hi), step)

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

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_daily_schedule.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/daily_schedule.py tests/test_daily_schedule.py
git commit -m "feat: coherent daily schedule generation with invariant check"
```

---

## Task 7: Row assembly

**Files:**
- Create: `monthly_schedule/rows.py`
- Test: `tests/test_rows.py`

Combines month dates + eligibility + daily schedule. Eligible rows get times; ineligible rows get empty strings for every time field (spec §4c). 3-letter day abbreviations match the reference image (`Fri`, `Sat`).

- [ ] **Step 1: Write the failing test**

`tests/test_rows.py`:

```python
import random
from datetime import date

from monthly_schedule.rules import SCHEDULE_RULES
from monthly_schedule.eligibility import Exclusions
from monthly_schedule.rows import build_rows, TIME_KEYS

AUTH = {1, 3, 4, 5}  # Mon, Wed, Thu, Fri


def test_row_count_and_shape():
    rng = random.Random(0)
    rows = build_rows(2026, 5, AUTH, SCHEDULE_RULES["Default"], rng)
    assert len(rows) == 31
    assert rows[0]["date"] == date(2026, 5, 1)
    assert rows[0]["day"] == "Fri"
    assert rows[1]["day"] == "Sat"


def test_eligible_day_has_times_unauthorized_day_blank():
    rng = random.Random(0)
    rows = build_rows(2026, 5, AUTH, SCHEDULE_RULES["Default"], rng)
    fri = rows[0]   # 2026-05-01 Friday -> authorized
    sat = rows[1]   # 2026-05-02 Saturday -> not authorized
    assert all(fri[k] != "" for k in TIME_KEYS)
    assert all(sat[k] == "" for k in TIME_KEYS)


def test_exclusions_blank_out_authorized_day():
    rng = random.Random(0)
    exc = Exclusions(ranges=((date(2026, 5, 11), date(2026, 5, 16)),))
    rows = build_rows(2026, 5, AUTH, SCHEDULE_RULES["Default"], rng, exc)
    # 2026-05-11 is Monday (authorized) but excluded
    may11 = next(r for r in rows if r["date"] == date(2026, 5, 11))
    assert all(may11[k] == "" for k in TIME_KEYS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_rows.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monthly_schedule.rows'`

- [ ] **Step 3: Write minimal implementation**

`monthly_schedule/rows.py`:

```python
"""Assemble the per-day rows that feed both workbook tables."""

from monthly_schedule.month_dates import get_month_dates
from monthly_schedule.eligibility import is_day_eligible
from monthly_schedule.daily_schedule import build_daily_schedule

DAY_ABBR = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
TIME_KEYS = ("pickup", "arrival", "time_in", "time_out", "departure", "dropoff")


def build_rows(year, month, authorized_weekdays, rules, rng, exclusions=None):
    """Return a list of row dicts (one per calendar day). Each row has
    'date', 'day', and the six TIME_KEYS. Ineligible days have ''
    for every time key."""
    rows = []
    for day in get_month_dates(year, month):
        row = {"date": day, "day": DAY_ABBR[day.isoweekday()]}
        if is_day_eligible(day, authorized_weekdays, exclusions):
            row.update(build_daily_schedule(rules, rng))
        else:
            for key in TIME_KEYS:
                row[key] = ""
        rows.append(row)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_rows.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/rows.py tests/test_rows.py
git commit -m "feat: assemble per-day rows for both tables"
```

---

## Task 8: Access DB access

**Files:**
- Create: `monthly_schedule/db.py`
- Test: `tests/test_db.py`

Implements spec §3/§6. The pure parts (`build_connection_string`, `map_member_row`) are unit-tested; `pyodbc` is imported lazily inside `get_member` so the tests need no driver. `get_member` itself is verified by the manual end-to-end run in Task 11.

- [ ] **Step 1: Write the failing test**

`tests/test_db.py`:

```python
import pytest

from monthly_schedule.db import (
    build_connection_string,
    map_member_row,
    MEMBER_QUERY,
    get_member,
)


def test_build_connection_string():
    cs = build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


def test_member_query_columns_and_filter():
    assert "[Center ID]" in MEMBER_QUERY
    assert "[Last Name]" in MEMBER_QUERY
    assert "[First Name]" in MEMBER_QUERY
    assert "[Health Plan]" in MEMBER_QUERY
    assert "[SADC Auth]" in MEMBER_QUERY
    assert "WHERE [Center ID] = ?" in MEMBER_QUERY


def test_map_member_row():
    row = (24010, "Cheng", "Lizhu", "Elderplan Homefirst", "1.3.4.5")
    assert map_member_row(row) == {
        "center_id": 24010,
        "last_name": "Cheng",
        "first_name": "Lizhu",
        "health_plan": "Elderplan Homefirst",
        "sadc_auth": "1.3.4.5",
    }


def test_get_member_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_member(24010, str(missing))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monthly_schedule.db'`

- [ ] **Step 3: Write minimal implementation**

`monthly_schedule/db.py`:

```python
"""Read one member record from the Access database via pyodbc.

`pyodbc` is imported lazily so the pure helpers are testable without
the ODBC driver. Bitness note (spec §8): the installed Microsoft
Access ODBC driver must match this Python interpreter's bitness.
"""

import os

MEMBER_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[SADC Auth] FROM [Contacts] WHERE [Center ID] = ?"
)


def build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def map_member_row(row):
    return {
        "center_id": row[0],
        "last_name": row[1],
        "first_name": row[2],
        "health_plan": row[3],
        "sadc_auth": row[4],
    }


def get_member(center_id, db_path):
    """Return the member dict for `center_id`, or None if no row.
    Raises FileNotFoundError if the DB path is absent, RuntimeError if
    the ODBC driver cannot open it."""
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
        cursor.execute(MEMBER_QUERY, center_id)
        row = cursor.fetchone()
        return map_member_row(row) if row else None
    finally:
        conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_db.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/db.py tests/test_db.py
git commit -m "feat: Access DB member lookup via pyodbc"
```

---

## Task 9: Workbook rendering

**Files:**
- Create: `monthly_schedule/workbook.py`
- Test: `tests/test_workbook.py`

Implements spec §5. Two tables stacked on one sheet with a manual row page break between them; header block repeated above each table; bordered, centered cells; dates as real date cells formatted `m/d/yyyy`; times as `HH:MM` text strings (editable in place). Verified by writing to a temp file and re-reading with `openpyxl`.

- [ ] **Step 1: Write the failing test**

`tests/test_workbook.py`:

```python
from datetime import date, datetime

from openpyxl import load_workbook

from monthly_schedule.workbook import build_workbook, COMPANY_NAME

MEMBER = {
    "center_id": 24010,
    "last_name": "Cheng",
    "first_name": "Lizhu",
    "health_plan": "Elderplan Homefirst",
    "sadc_auth": "1.3.4.5",
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


def test_workbook_structure(tmp_path):
    out = tmp_path / "sched.xlsx"
    build_workbook(MEMBER, ROWS, str(out))
    assert out.exists()

    wb = load_workbook(str(out))
    ws = wb["Schedule"]

    # header block
    assert ws["A1"].value == COMPANY_NAME
    assert ws["A2"].value == "MLTC: Elderplan Homefirst"
    assert ws["A3"].value == "ID: 24010"
    assert ws["B3"].value == "Name: Cheng, Lizhu"
    assert ws["D3"].value == "Auth Days: 1.3.4.5"

    # table 1 header on row 4
    assert [ws.cell(row=4, column=c).value for c in range(1, 5)] == [
        "Date", "Day", "Time-In", "Time-Out"
    ]
    # table 1 first data row
    # openpyxl reads date-serial cells back as datetime.datetime, not date
    assert ws.cell(row=5, column=1).value == datetime(2026, 5, 1)
    assert ws.cell(row=5, column=1).number_format == "m/d/yyyy"
    assert ws.cell(row=5, column=3).value == "08:17"
    assert ws.cell(row=5, column=4).value == "12:13"
    # ineligible row blank
    assert ws.cell(row=6, column=3).value in (None, "")

    # exactly one manual page break
    assert ws.row_breaks.count == 1

    # table 2 appears later with its own header block + 6-col header
    found_t2 = False
    for r in range(1, ws.max_row + 1):
        if ws.cell(row=r, column=1).value == "Date" and ws.cell(
            row=r, column=3
        ).value == "Pick-Up Time":
            assert ws.cell(row=r, column=6).value == "Drop-Off Time"
            found_t2 = True
            break
    assert found_t2

    # print area set and spans to column F
    assert ws.print_area is not None
    assert "F" in ws.print_area
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_workbook.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monthly_schedule.workbook'`

- [ ] **Step 3: Write minimal implementation**

`monthly_schedule/workbook.py`:

```python
"""Render the two-table printable workbook with openpyxl (spec §5)."""

from openpyxl import Workbook
from openpyxl.styles import Border, Side, Alignment, Font
from openpyxl.worksheet.pagebreak import Break

COMPANY_NAME = "Bowery Senior Care Inc"

_THIN = Side(style="thin")
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center")
_BOLD = Font(bold=True)

TABLE1_HEADERS = ["Date", "Day", "Time-In", "Time-Out"]
TABLE1_KEYS = ["time_in", "time_out"]
TABLE2_HEADERS = [
    "Date", "Day", "Pick-Up Time", "Arrival Time",
    "Departure Time", "Drop-Off Time",
]
TABLE2_KEYS = ["pickup", "arrival", "departure", "dropoff"]


def _member_name(member):
    return f"{member['last_name']}, {member['first_name']}"


def _write_header_block(ws, start_row, member):
    ws.cell(row=start_row, column=1, value=COMPANY_NAME).font = _BOLD
    ws.cell(row=start_row + 1, column=1,
            value=f"MLTC: {member['health_plan']}")
    ws.cell(row=start_row + 2, column=1,
            value=f"ID: {member['center_id']}")
    ws.cell(row=start_row + 2, column=2,
            value=f"Name: {_member_name(member)}")
    ws.cell(row=start_row + 2, column=4,
            value=f"Auth Days: {member['sadc_auth']}")
    return start_row + 3  # first free row after the block


def _write_table(ws, start_row, headers, keys, rows):
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=col, value=text)
        cell.font = _BOLD
        cell.alignment = _CENTER
        cell.border = _BOX
    r = start_row + 1
    for row in rows:
        date_cell = ws.cell(row=r, column=1, value=row["date"])
        date_cell.number_format = "m/d/yyyy"
        ws.cell(row=r, column=2, value=row["day"])
        for offset, key in enumerate(keys, start=3):
            ws.cell(row=r, column=offset, value=row[key])
        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=r, column=col)
            cell.alignment = _CENTER
            cell.border = _BOX
        r += 1
    return r  # first free row after the table


def build_workbook(member, rows, output_path):
    """Write the workbook to output_path and return that path."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Schedule"

    after_h1 = _write_header_block(ws, 1, member)
    after_t1 = _write_table(ws, after_h1, TABLE1_HEADERS, TABLE1_KEYS, rows)
    last_t1_row = after_t1 - 1

    # manual page break AFTER the last table-1 row -> table 2 on next page
    ws.row_breaks.append(Break(id=last_t1_row))

    after_h2 = _write_header_block(ws, after_t1, member)
    after_t2 = _write_table(ws, after_h2, TABLE2_HEADERS, TABLE2_KEYS, rows)

    ws.print_area = f"A1:F{after_t2 - 1}"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    wb.save(output_path)
    return output_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_workbook.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/workbook.py tests/test_workbook.py
git commit -m "feat: render two-table printable workbook with openpyxl"
```

---

## Task 10: CLI entry / orchestration

**Files:**
- Create: `new_monthly_schedule.py`
- Test: `tests/test_cli.py`

Implements spec §2/§6. `main(argv)` is importable and testable; `get_member` is monkeypatched in tests so no DB is needed. `--preview-data` prints rows and skips the workbook. Exit codes: 0 success; 2 no member.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
import new_monthly_schedule as cli

FAKE_MEMBER = {
    "center_id": 24010,
    "last_name": "Cheng",
    "first_name": "Lizhu",
    "health_plan": "Elderplan Homefirst",
    "sadc_auth": "1.3.4.5",
}


def test_preview_data_returns_zero_and_prints(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--preview-data"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "2026-05-01" in out
    assert out.count("\n") >= 31  # one line per day


def test_no_member_returns_2(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: None)
    rc = cli.main(
        ["--center-id", "999", "--year", "2026", "--month", "5",
         "--preview-data"]
    )
    assert rc == 2
    assert "No member found" in capsys.readouterr().err


def test_writes_workbook(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    out = tmp_path / "out.xlsx"
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(out)]
    )
    assert rc == 0
    assert out.exists()


def test_invalid_month_rejected(monkeypatch):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    import pytest
    with pytest.raises(SystemExit):
        cli.main(
            ["--center-id", "24010", "--year", "2026", "--month", "13",
             "--preview-data"]
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'new_monthly_schedule'`

- [ ] **Step 3: Write minimal implementation**

`new_monthly_schedule.py`:

```python
"""CLI: generate a monthly schedule workbook for one SADC member."""

import argparse
import random
import sys

from monthly_schedule.db import get_member
from monthly_schedule.auth_days import get_authorized_weekdays
from monthly_schedule.rules import get_rules_for_plan
from monthly_schedule.rows import build_rows
from monthly_schedule.workbook import build_workbook

DEFAULT_DB = r"\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb"


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Generate a printable monthly schedule workbook."
    )
    parser.add_argument("--center-id", type=int, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--month", type=int, required=True,
        choices=range(1, 13), metavar="{1-12}",
    )
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--preview-data", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    member = get_member(args.center_id, args.db_path)
    if member is None:
        print(
            f"No member found with Center ID {args.center_id}",
            file=sys.stderr,
        )
        return 2

    authorized = get_authorized_weekdays(member["sadc_auth"])
    if not authorized:
        print(
            f"Warning: no authorized weekdays parsed from SADC Auth "
            f"{member['sadc_auth']!r}; all time cells will be blank.",
            file=sys.stderr,
        )

    rules = get_rules_for_plan(member["health_plan"])
    rng = random.Random()
    rows = build_rows(args.year, args.month, authorized, rules, rng)

    if args.preview_data:
        for row in rows:
            print(row)
        return 0

    output_path = args.output_path or (
        f"./Schedule_{args.center_id}_"
        f"{args.year:04d}-{args.month:02d}.xlsx"
    )
    build_workbook(member, rows, output_path)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS (4 tests)

Note: `test_preview_data_returns_zero_and_prints` asserts `"2026-05-01"` appears because each printed row dict contains `'date': datetime.date(2026, 5, 1)` whose `str()` is `2026-05-01`.

- [ ] **Step 5: Commit**

```bash
git add new_monthly_schedule.py tests/test_cli.py
git commit -m "feat: CLI orchestration with preview and workbook output"
```

---

## Task 11: Full test run, README usage, manual end-to-end

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -v`
Expected: ALL tests pass (smoke, auth_days, month_dates, eligibility, rules, daily_schedule, rows, db, workbook, cli).

- [ ] **Step 2: Manual end-to-end against the live DB**

Run:
```
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5 --preview-data
```
Expected: 31 printed row dicts; authorized weekdays (Mon/Wed/Thu/Fri per `1.3.4.5`) have `HH:MM` times, Sat/Sun blank. If a `RuntimeError` about the ODBC driver appears, the Access driver bitness does not match the Python interpreter (spec §8) — install the matching-bitness Access Database Engine redistributable.

Then generate the workbook:
```
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5
```
Expected: `Wrote ./Schedule_24010_2026-05.xlsx`. Open it; confirm against the reference image — header block, Table 1 (Date/Day/Time-In/Time-Out), page break, repeated header, Table 2 (Date/Day/Pick-Up/Arrival/Departure/Drop-Off). Print preview shows the two tables on separate pages.

- [ ] **Step 3: Update README**

Replace `README.md` contents with:

```markdown
# BSCA

Tools for Bowery Senior Care Inc member data.

## Get-Contact.ps1

Interactive PowerShell lookup of a member by Center ID:

```
pwsh ./Get-Contact.ps1 -CenterID 24010
```

## new_monthly_schedule.py

Generates a printable monthly schedule workbook (attendance +
transportation tables) for one member.

Setup:

```
python -m pip install -r requirements.txt
```

Usage:

```
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5
```

Options:

- `--output-path PATH` — workbook path (default
  `./Schedule_<id>_<YYYY-MM>.xlsx`)
- `--db-path PATH` — Access DB path (default the BOWERY3 share)
- `--preview-data` — print computed rows, skip the workbook

Times are placeholder values (see
`docs/superpowers/specs/2026-05-15-monthly-schedule-design.md`,
section 4). The Microsoft Access ODBC driver must match the Python
interpreter's bitness (spec section 8).

Run tests: `python -m pytest`
```

- [ ] **Step 4: Run the full suite once more**

Run: `python -m pytest`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: usage for new_monthly_schedule.py and test run"
```

---

## Self-Review

**1. Spec coverage:**

- §1 purpose / coexistence with `Get-Contact.ps1` → Task 1 + Task 11 README; no refactor of existing PS.
- §2 CLI args (center-id, year, month 1-12, db-path, output-path, preview-data; exit codes) → Task 10.
- §3 pyodbc connect, parameterized query, column mapping, no-member/missing-DB handling, SADC Auth parse (1=Mon..7=Sun) → Tasks 8, 2.
- §4a eligibility seam with empty `exclusions` default; vacation range + termination semantics → Task 4 (seam built; reader deferred per §4d/§9).
- §4b `SCHEDULE_RULES`, per-plan keying + Default, coherent schedule, post-gen ordering + session assertion → Tasks 5, 6.
- §4c ineligible days render blank time cells → Tasks 7, 9.
- §4d / §9 out-of-scope items (no exclusion-source code, no plug-in engine) → respected; none implemented.
- §5 openpyxl single sheet, two stacked tables, repeated header block, page break, borders, centered, date `m/d/yyyy`, times text `HH:MM`, print area → Task 9.
- §6 error table (missing DB, driver/bitness, no member, bad month, unparseable SADC Auth warning, rule violation) → Tasks 8, 10, 2, 6.
- §7 pytest for each pure function + `--preview-data` + manual e2e → Tasks 2-10, 11.
- §8 dependencies pinned; bitness surfaced in error + README → Tasks 1, 8, 11.

No gaps.

**2. Placeholder scan:** No "TBD/TODO/handle edge cases/similar to Task N". Every code step contains complete code; every test step contains complete test code; every run step states the exact command and expected result.

**3. Type consistency:** Verified across tasks — `get_authorized_weekdays`, `get_month_dates`, `Exclusions(ranges, termination_date)`, `is_day_eligible(day, authorized_weekdays, exclusions=None)`, `SCHEDULE_RULES`/`get_rules_for_plan`/`parse_hhmm`/`format_minutes`, `build_daily_schedule(rules, rng)`/`validate_schedule(pickup, arrival, time_in, time_out, departure, dropoff, rules)`, `build_rows(year, month, authorized_weekdays, rules, rng, exclusions=None)`/`TIME_KEYS`, `build_connection_string`/`map_member_row`/`MEMBER_QUERY`/`get_member`, `build_workbook(member, rows, output_path)`/`COMPANY_NAME`, `new_monthly_schedule.main(argv)`/`get_member` symbol patched in CLI tests. Member dict keys (`center_id`, `last_name`, `first_name`, `health_plan`, `sadc_auth`) and row dict keys (`date`, `day`, `pickup`, `arrival`, `time_in`, `time_out`, `departure`, `dropoff`) are consistent everywhere they appear.

No issues found.
