# Holidays and Operating Days Implementation Plan (BSCA repo)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `Holidays` and `OperatingDays` tables to the Setup chain and make the monthly scheduler skip holidays and closed weekdays and take each weekday's day bounds from `OperatingDays`.

**Architecture:** A new `CenterCalendar` object (built once per run from two new `db.py` fetchers) answers "is the center closed on this day?" and rewrites the plan rules' `earliest_time_in` / `latest_time_out` per weekday. `rows.py` asks it for per-day rules and passes them down, so `per_day.py` and `daily_schedule.py` keep reading the same two rule keys. A new `REASON_DAY_CENTER_CLOSED` rejection fires right after the authorization check. The Settings dialog loses its two day-bound fields.

**Tech Stack:** Python 3.11, pyodbc against Microsoft Access, PyQt6, pytest. Run tests with `.venv\Scripts\python.exe -m pytest` from the repo root `C:\Users\luald\OneDrive\Desktop\BSCA`.

**Spec:** `docs/superpowers/specs/2026-09-08-holidays-operating-days-design.md`. The Members-app half is a separate plan in the `BSCA-Members` repo: `docs/superpowers/plans/2026-09-08-company-calendar.md`.

---

## File map

| File | Change |
| --- | --- |
| `scripts/create_supporting_tables.py` | Two new DDL constants + `_DDLS` entries |
| `scripts/seed_operating_days.py` | **New.** Seeds 7 default rows when the table is empty |
| `setup_gui/setup_worker.py` | Register the seed step after `create_supporting_tables` |
| `monthly_schedule/db.py` | `get_holidays`, `get_operating_days`, mappers; `_fetch_all_unfiltered` gains `require_col` |
| `monthly_schedule/center_calendar.py` | **New.** `CenterCalendar`, `DAY_NAME` |
| `monthly_schedule/per_day.py` | `REASON_DAY_CENTER_CLOSED`; `calendar=` on `compute_day_eligibility` and `compute_month_failure` |
| `monthly_schedule/rows.py` | `calendar=` on `build_rows` / `build_debug_rows`; per-day rules; closed-day wording |
| `new_monthly_schedule.py` | `calendar=` on `collect_debug_rows` / `process_member`; `main()` builds one |
| `gui/worker.py` | Fetch both tables, build the calendar, pass it through |
| `scripts/audit_enrollment_gate.py` | Same |
| `gui/settings_dialog.py`, `gui/app_settings.py`, `gui/i18n.py` | Remove the two day-bound fields/keys/labels |
| `scripts/make_test_db.py` | Ensure + seed the tables; `happy_path` gets one holiday |
| `docs/database.md`, `README.md`, `scripts/README.md` | Document |
| Tests | `tests/test_create_supporting_tables.py`, `tests/test_seed_operating_days.py` (new), `tests/test_setup_worker.py`, `tests/test_db.py`, `tests/test_center_calendar.py` (new), `tests/test_per_day.py`, `tests/test_rows.py`, `tests/test_cli.py`, `tests/test_schedule_worker.py`, `tests/test_app_settings.py`, `tests/test_settings_dialog.py` |

---

### Task 1: DDL for the two tables

**Files:**
- Modify: `scripts/create_supporting_tables.py`
- Test: `tests/test_create_supporting_tables.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_create_supporting_tables.py`:

```python
def test_create_holidays_ddl():
    q = build._CREATE_HOLIDAYS
    assert "CREATE TABLE [Holidays]" in q
    assert "[ID] AUTOINCREMENT PRIMARY KEY" in q
    assert "[holiday_name] TEXT(255)" in q
    assert "[date] DATETIME" in q


def test_create_operating_days_ddl():
    q = build._CREATE_OPERATING_DAYS
    assert "CREATE TABLE [OperatingDays]" in q
    assert "[ID] AUTOINCREMENT PRIMARY KEY" in q
    assert "[day_name] TEXT(20)" in q
    assert "[Day Of Week] LONG" in q
    assert "[opening_time] DATETIME" in q
    assert "[closing_time] DATETIME" in q


def test_ddls_end_with_calendar_tables():
    names = [name for name, _ddl in build._DDLS]
    assert names[-2:] == ["Holidays", "OperatingDays"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_create_supporting_tables.py -q`
Expected: 3 failures, `AttributeError: module ... has no attribute '_CREATE_HOLIDAYS'` and the `_DDLS` assertion.

- [ ] **Step 3: Add the DDL**

In `scripts/create_supporting_tables.py`, after `_CREATE_EMERGENCY_CONTACT` and before `_DDLS`, add:

```python
# Company holidays: one row per closed date. The scheduler generates
# no times on these days (they look like non-authorized weekdays, not
# absences). Entered through the Members app's Company Calendar dialog.
_CREATE_HOLIDAYS = (
    "CREATE TABLE [Holidays] ("
    "[ID] AUTOINCREMENT PRIMARY KEY, "
    "[holiday_name] TEXT(255), "
    "[date] DATETIME"
    ")"
)

# Weekly operating hours, one row per OPEN weekday. A weekday with no
# row is closed. [Day Of Week] follows Availability's convention
# (1 = Monday … 7 = Sunday); the scheduler matches on it, never on
# [day_name]. Times are time-only DATETIMEs (1899-12-30 HH:MM), the
# same encoding as Availability.avail_start. Seeded Mon–Sun
# 08:00–16:00 by scripts/seed_operating_days.py.
_CREATE_OPERATING_DAYS = (
    "CREATE TABLE [OperatingDays] ("
    "[ID] AUTOINCREMENT PRIMARY KEY, "
    "[day_name] TEXT(20), "
    "[Day Of Week] LONG, "
    "[opening_time] DATETIME, "
    "[closing_time] DATETIME"
    ")"
)
```

Extend `_DDLS`:

```python
_DDLS = [
    ("Enrollment", _CREATE_ENROLLMENT),
    ("Authorization", _CREATE_AUTHORIZATION),
    ("TransportAuthorization", _CREATE_TRANSPORT_AUTHORIZATION),
    ("Absences", _CREATE_ABSENCES),
    ("Availability", _CREATE_AVAILABILITY),
    ("OneOffAvailability", _CREATE_ONE_OFF_AVAILABILITY),
    ("EmergencyContact", _CREATE_EMERGENCY_CONTACT),
    ("AuthEdge", _CREATE_AUTH_EDGE),
    ("Holidays", _CREATE_HOLIDAYS),
    ("OperatingDays", _CREATE_OPERATING_DAYS),
]
```

Update the module docstring's first two sentences to read "Create the ten supporting tables …" and list `Holidays` and `OperatingDays` after `AuthEdge`. In `_parse_args`, change the description to `"Create the supporting tables (Enrollment, Authorization, Absences, Availability, OneOffAvailability, EmergencyContact, AuthEdge, Holidays, OperatingDays) in an Access .accdb that already contains Contacts."`.

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_create_supporting_tables.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/create_supporting_tables.py tests/test_create_supporting_tables.py
git commit -m "feat(setup): Holidays and OperatingDays DDL"
```

---

### Task 2: `seed_operating_days` script and Setup step

**Files:**
- Create: `scripts/seed_operating_days.py`
- Modify: `setup_gui/setup_worker.py`
- Modify: `scripts/README.md`
- Test: `tests/test_seed_operating_days.py` (new), `tests/test_setup_worker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_seed_operating_days.py`:

```python
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import seed_operating_days as seed


class _FakeCursor:
    """Records every execute; `existing` is what COUNT(*) returns."""

    def __init__(self, existing: int):
        self._existing = existing
        self.executed = []

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self

    def fetchone(self):
        return (self._existing,)


def test_build_connection_string():
    cs = seed._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


def test_parse_args():
    ns = seed._parse_args(["--db", "x"])
    assert ns.db == "x"


def test_main_missing_db_returns_2(tmp_path, capsys):
    rc = seed.main(["--db", str(tmp_path / "nope.accdb")])
    assert rc == 2
    assert "database not found" in capsys.readouterr().err.lower()


def test_seed_inserts_seven_defaults_when_empty():
    cur = _FakeCursor(existing=0)
    existing, inserted = seed.seed_if_empty(cur)
    assert (existing, inserted) == (0, 7)
    inserts = [e for e in cur.executed if e[0].startswith("INSERT")]
    assert len(inserts) == 7
    assert [p[0] for _sql, p in inserts] == list(seed.DAY_NAMES)
    assert [p[1] for _sql, p in inserts] == [1, 2, 3, 4, 5, 6, 7]
    for _sql, p in inserts:
        assert p[2] == datetime(1899, 12, 30, 8, 0)
        assert p[3] == datetime(1899, 12, 30, 16, 0)


def test_seed_is_noop_when_rows_exist():
    cur = _FakeCursor(existing=5)
    assert seed.seed_if_empty(cur) == (5, 0)
    assert not any(e[0].startswith("INSERT") for e in cur.executed)


def test_insert_statement_shape():
    q = seed._INSERT_ROW
    assert q.startswith("INSERT INTO [OperatingDays]")
    for col in ("[day_name]", "[Day Of Week]", "[opening_time]",
                "[closing_time]"):
        assert col in q
```

In `tests/test_setup_worker.py`, update `test_setup_steps_constant_lists_fifteen_scripts`: rename it to `test_setup_steps_constant_lists_sixteen_scripts`, change the docstring's "15" to "16", `assert len(SETUP_STEPS) == 16`, and insert `"seed_operating_days",` immediately after `"create_supporting_tables",` in the expected names list.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_seed_operating_days.py tests/test_setup_worker.py -q`
Expected: `ModuleNotFoundError: No module named 'scripts.seed_operating_days'` and the step-count assertion failing.

- [ ] **Step 3: Write the script**

Create `scripts/seed_operating_days.py`:

```python
"""Seed the OperatingDays table with the seven default rows
(Monday–Sunday, 08:00–16:00) — but only when the table is empty.

The scheduler treats a weekday with no OperatingDays row as closed,
so a freshly created table would silently close the center every day.
This one-shot fill gives every new database the 7-days-a-week default.

Idempotent: if the table already has any rows (defaults or hand edits
from the Members app's Company Calendar dialog) nothing is written, so
re-running the Setup chain never overwrites staff changes.

Runs in the Setup chain right after create_supporting_tables.
"""
import argparse
import os
import sys
from datetime import datetime


DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday")

# Time-only DATETIME values use Access's 1899-12-30 placeholder date,
# the same encoding as Availability.avail_start / avail_end.
DEFAULT_OPENING = datetime(1899, 12, 30, 8, 0)
DEFAULT_CLOSING = datetime(1899, 12, 30, 16, 0)

_COUNT_ROWS = "SELECT COUNT(*) FROM [OperatingDays]"

_INSERT_ROW = (
    "INSERT INTO [OperatingDays] "
    "([day_name], [Day Of Week], [opening_time], [closing_time]) "
    "VALUES (?, ?, ?, ?)"
)


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def seed_if_empty(cursor):
    """Insert the seven default rows when the table has none.
    Returns (existing_row_count, inserted_row_count)."""
    cursor.execute(_COUNT_ROWS)
    (existing,) = cursor.fetchone()
    existing = int(existing or 0)
    if existing:
        return existing, 0
    for day_of_week, name in enumerate(DAY_NAMES, start=1):
        cursor.execute(
            _INSERT_ROW, name, day_of_week, DEFAULT_OPENING, DEFAULT_CLOSING,
        )
    return 0, len(DAY_NAMES)


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Fill an empty OperatingDays table with Monday–Sunday "
            "08:00–16:00. Leaves a non-empty table untouched."
        ),
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
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
        existing, inserted = seed_if_empty(cur)
        conn.commit()
    finally:
        conn.close()

    if inserted:
        print(f"Seeded {inserted} operating days (Mon-Sun, 08:00-16:00)")
    else:
        print(f"OperatingDays already has {existing} rows; left unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Register the step**

In `setup_gui/setup_worker.py`, inside `SETUP_STEPS`, insert right after the `create_supporting_tables` tuple:

```python
    ("seed_operating_days",
     "scripts.seed_operating_days"),
```

Update the module docstring's chain description: after `create_supporting_tables →` add `seed_operating_days →`.

- [ ] **Step 5: Document the script**

In `scripts/README.md`, in the scripts table, replace the `create_supporting_tables.py` row's text with: "DDL bootstrap. Issues `CREATE TABLE` for the supporting tables (`Enrollment`, `Authorization`, `TransportAuthorization`, `Absences`, `Availability`, `OneOffAvailability`, `EmergencyContact`, `AuthEdge`, `Holidays`, `OperatingDays`) on an `.accdb` that already contains `Contacts`. No data is written." Then add a new row directly below it:

```
| [`seed_operating_days.py`](seed_operating_days.py) | Fills an empty `OperatingDays` table with the seven default rows (Monday–Sunday, 08:00–16:00). No-op when the table already has rows, so staff edits made in the Members app survive re-running Setup. |
```

- [ ] **Step 6: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_seed_operating_days.py tests/test_setup_worker.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/seed_operating_days.py setup_gui/setup_worker.py scripts/README.md tests/test_seed_operating_days.py tests/test_setup_worker.py
git commit -m "feat(setup): seed_operating_days step fills the 7-day default"
```

---

### Task 3: Fetchers in `monthly_schedule/db.py`

**Files:**
- Modify: `monthly_schedule/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py` (the file already imports `sys`, `pytest`, and `tmp_path` fixtures are built in; add `from datetime import date, datetime` and `import types` at the top if not present):

```python
def test_map_holiday_row():
    from monthly_schedule.db import map_holiday_row
    row = (3, " Labor Day ", datetime(2026, 9, 7, 0, 0))
    assert map_holiday_row(row) == {
        "id": 3, "name": "Labor Day", "date": date(2026, 9, 7),
    }


def test_map_holiday_row_blank_name():
    from monthly_schedule.db import map_holiday_row
    assert map_holiday_row((4, None, datetime(2026, 1, 1)))["name"] == ""


def test_map_operating_day_row():
    from monthly_schedule.db import map_operating_day_row
    row = (1, "Monday", 1, datetime(1899, 12, 30, 8, 0),
           datetime(1899, 12, 30, 16, 0))
    assert map_operating_day_row(row) == {
        "id": 1, "day_name": "Monday", "day_of_week": 1,
        "opening_time": "08:00", "closing_time": "16:00",
    }


def test_get_holidays_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_holidays
    with pytest.raises(FileNotFoundError):
        get_holidays(str(tmp_path / "nope.accdb"))


def test_get_operating_days_missing_db_raises(tmp_path):
    from monthly_schedule.db import get_operating_days
    with pytest.raises(FileNotFoundError):
        get_operating_days(str(tmp_path / "nope.accdb"))


def test_fetch_all_unfiltered_require_col(monkeypatch, tmp_path):
    """require_col picks which column must be non-NULL for a row to be
    kept (default 1 = Center ID; the calendar tables use 2)."""
    from monthly_schedule.db import _fetch_all_unfiltered
    db = tmp_path / "x.accdb"
    db.write_bytes(b"")
    rows = [(1, None, 5), (2, "x", None)]

    class FakeCursor:
        def execute(self, q):
            pass

        def fetchall(self):
            return rows

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    fake_pyodbc = types.SimpleNamespace(
        connect=lambda cs: FakeConn(), Error=Exception,
    )
    monkeypatch.setitem(sys.modules, "pyodbc", fake_pyodbc)
    assert _fetch_all_unfiltered("q", str(db), lambda r: r) == [(2, "x", None)]
    assert _fetch_all_unfiltered("q", str(db), lambda r: r,
                                 require_col=2) == [(1, None, 5)]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db.py -q -k "holiday or operating or require_col"`
Expected: ImportError / TypeError failures.

- [ ] **Step 3: Implement**

In `monthly_schedule/db.py`, change `_fetch_all_unfiltered` to:

```python
def _fetch_all_unfiltered(query: str, db_path: str, mapper, require_col=1):
    """Open one connection, run an unfiltered SELECT, map each row.
    Used by the `get_all_<table>` batch fetchers so a whole-table load
    is one ODBC round-trip instead of N. Rows whose column at index
    `require_col` is NULL are dropped (default 1 = [Center ID]; the
    center-wide calendar tables pass the index of their key column)."""
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
        cursor.execute(query)
        return [mapper(row) for row in cursor.fetchall()
                if row[require_col] is not None]
    finally:
        conn.close()
```

After `get_all_one_offs`, add:

```python
HOLIDAYS_QUERY = "SELECT [ID], [holiday_name], [date] FROM [Holidays]"


def map_holiday_row(row):
    """Map a raw Holidays row. `date` is a DATETIME truncated to a
    date; a NULL name becomes ''."""
    return {
        "id": int(row[0]),
        "name": str(row[1] or "").strip(),
        "date": _to_date(row[2]),
    }


def get_holidays(db_path: str) -> list:
    """Every Holidays row (center-wide, so no center_id index). Rows
    with a NULL date are dropped."""
    return _fetch_all_unfiltered(
        HOLIDAYS_QUERY, db_path, map_holiday_row, require_col=2,
    )


OPERATING_DAYS_QUERY = (
    "SELECT [ID], [day_name], [Day Of Week], [opening_time], "
    "[closing_time] FROM [OperatingDays]"
)


def map_operating_day_row(row):
    """Map a raw OperatingDays row. Times are the 1899-12-30
    placeholder DATETIMEs, extracted as 'HH:MM' like Availability."""
    return {
        "id": int(row[0]),
        "day_name": str(row[1] or ""),
        "day_of_week": int(row[2]),
        "opening_time": _datetime_to_hhmm(row[3]),
        "closing_time": _datetime_to_hhmm(row[4]),
    }


def get_operating_days(db_path: str) -> list:
    """Every OperatingDays row. Rows with a NULL [Day Of Week] are
    dropped. A weekday with no row is closed (see CenterCalendar)."""
    return _fetch_all_unfiltered(
        OPERATING_DAYS_QUERY, db_path, map_operating_day_row, require_col=2,
    )
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/db.py tests/test_db.py
git commit -m "feat(db): get_holidays and get_operating_days fetchers"
```

---

### Task 4: `CenterCalendar`

**Files:**
- Create: `monthly_schedule/center_calendar.py`
- Test: `tests/test_center_calendar.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_center_calendar.py`:

```python
from datetime import date

from monthly_schedule.center_calendar import CenterCalendar, DAY_NAME


PLAN_RULES = {
    "earliest_time_in": "08:00",
    "latest_time_out": "16:00",
    "session_length_min": (210, 240),
}


def _open(*days, opening="08:00", closing="16:00", first_id=1):
    return [
        {"id": first_id + i, "day_name": DAY_NAME[d], "day_of_week": d,
         "opening_time": opening, "closing_time": closing}
        for i, d in enumerate(days)
    ]


ALL_WEEK = _open(1, 2, 3, 4, 5, 6, 7)
MON = date(2026, 5, 4)      # Monday
SUN = date(2026, 5, 3)      # Sunday


def test_holiday_is_closed_with_name():
    cal = CenterCalendar(
        [{"id": 1, "name": "Labor Day", "date": MON}], ALL_WEEK)
    assert cal.closed_reason(MON) == ("holiday", "Labor Day")
    assert cal.is_closed(MON) is True


def test_weekday_without_row_is_closed():
    cal = CenterCalendar([], _open(1, 2, 3, 4, 5))
    assert cal.closed_reason(SUN) == ("weekday", None)
    assert cal.closed_reason(MON) is None


def test_holiday_wins_over_closed_weekday():
    cal = CenterCalendar(
        [{"id": 1, "name": "Easter", "date": SUN}], _open(1, 2, 3, 4, 5))
    assert cal.closed_reason(SUN) == ("holiday", "Easter")


def test_holiday_with_null_date_is_ignored():
    cal = CenterCalendar([{"id": 1, "name": "x", "date": None}], ALL_WEEK)
    assert cal.closed_reason(MON) is None


def test_rules_for_substitutes_weekday_hours():
    cal = CenterCalendar([], _open(1, opening="09:30", closing="15:00"))
    rules = cal.rules_for(MON, PLAN_RULES)
    assert rules["earliest_time_in"] == "09:30"
    assert rules["latest_time_out"] == "15:00"
    assert rules["session_length_min"] == (210, 240)
    assert PLAN_RULES["earliest_time_in"] == "08:00"   # input untouched


def test_rules_for_closed_weekday_returns_plan_rules():
    cal = CenterCalendar([], _open(1))
    assert cal.rules_for(SUN, PLAN_RULES) is PLAN_RULES


def test_always_open_never_closes_and_keeps_rules():
    cal = CenterCalendar.always_open()
    assert cal.closed_reason(SUN) is None
    assert cal.rules_for(SUN, PLAN_RULES) is PLAN_RULES


def test_empty_operating_days_closes_every_weekday():
    cal = CenterCalendar([], [])
    assert cal.closed_reason(MON) == ("weekday", None)


def test_duplicate_weekday_rows_largest_id_wins():
    rows = _open(1, opening="08:00") + _open(1, opening="10:00", first_id=9)
    cal = CenterCalendar([], rows)
    assert cal.rules_for(MON, PLAN_RULES)["earliest_time_in"] == "10:00"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_center_calendar.py -q`
Expected: `ModuleNotFoundError: No module named 'monthly_schedule.center_calendar'`.

- [ ] **Step 3: Write the module**

Create `monthly_schedule/center_calendar.py`:

```python
"""The center's own calendar: company holidays plus weekly operating
hours, read once per run from the Holidays and OperatingDays tables.

Two questions, one object:
  - `closed_reason(day)`: is the center closed that day, and why?
  - `rules_for(day, plan_rules)`: the plan rules with that weekday's
    opening/closing time substituted for earliest_time_in /
    latest_time_out, so everything downstream keeps reading the same
    two keys.

`CenterCalendar.always_open()` is the no-information calendar (no
holidays, no weekday restriction, rules untouched) used by callers and
tests that don't load the tables.
"""

DAY_NAME = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday",
            5: "Friday", 6: "Saturday", 7: "Sunday"}


class CenterCalendar:
    def __init__(self, holidays=(), operating_days=None):
        """`holidays`: dicts from db.get_holidays ({id, name, date}).
        `operating_days`: dicts from db.get_operating_days ({id,
        day_of_week, opening_time, closing_time, ...}) or None for
        "no weekday information" (every weekday open, rules untouched).
        An empty list means every weekday is closed — that is what the
        table says when staff uncheck all seven days."""
        self._holidays = {}
        for row in holidays:
            day = row.get("date")
            if day is None or day in self._holidays:
                continue
            self._holidays[day] = str(row.get("name") or "").strip()

        if operating_days is None:
            self._days = None
        else:
            # Hand edits in Access could leave two rows for a weekday;
            # the newest (largest ID) wins.
            self._days = {}
            for row in operating_days:
                dow = row["day_of_week"]
                current = self._days.get(dow)
                if current is None or row["id"] > current["id"]:
                    self._days[dow] = row

    @classmethod
    def always_open(cls):
        return cls((), None)

    def closed_reason(self, day):
        """("holiday", name) when `day` is a company holiday,
        ("weekday", None) when its weekday has no OperatingDays row,
        else None. Holidays are checked first so the debug report names
        the holiday even on an otherwise-closed weekday."""
        if day in self._holidays:
            return ("holiday", self._holidays[day])
        if self._days is not None and day.isoweekday() not in self._days:
            return ("weekday", None)
        return None

    def is_closed(self, day) -> bool:
        return self.closed_reason(day) is not None

    def rules_for(self, day, plan_rules):
        """`plan_rules` with earliest_time_in / latest_time_out replaced
        by the weekday's opening / closing time. Returns `plan_rules`
        itself (not a copy) when there is nothing to substitute."""
        if self._days is None:
            return plan_rules
        row = self._days.get(day.isoweekday())
        if row is None:
            return plan_rules
        merged = dict(plan_rules)
        merged["earliest_time_in"] = row["opening_time"]
        merged["latest_time_out"] = row["closing_time"]
        return merged
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_center_calendar.py -q`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/center_calendar.py tests/test_center_calendar.py
git commit -m "feat: CenterCalendar answers closed days and per-weekday hours"
```

---

### Task 5: Eligibility honors the calendar

**Files:**
- Modify: `monthly_schedule/per_day.py`
- Test: `tests/test_per_day.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_per_day.py` (add `from monthly_schedule.center_calendar import CenterCalendar` to the imports):

```python
def _open_days(*days, opening="08:00", closing="16:00"):
    return [
        {"id": d, "day_name": "", "day_of_week": d,
         "opening_time": opening, "closing_time": closing}
        for d in days
    ]


ALL_WEEK = _open_days(1, 2, 3, 4, 5, 6, 7)


def test_holiday_rejected_with_center_closed():
    from monthly_schedule.per_day import REASON_DAY_CENTER_CLOSED
    cal = CenterCalendar(
        [{"id": 1, "name": "Labor Day", "date": date(2026, 5, 4)}], ALL_WEEK)
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(), PLAN_RULES, calendar=cal)
    assert result.eligible is False
    assert result.reason == REASON_DAY_CENTER_CLOSED


def test_closed_weekday_rejected_even_when_authorized():
    from monthly_schedule.per_day import REASON_DAY_CENTER_CLOSED
    cal = CenterCalendar([], _open_days(2, 4))       # Tue/Thu only
    # 2026-05-04 is a Monday, authorized by "1,3,5" but the center is closed.
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(), PLAN_RULES, calendar=cal)
    assert result.eligible is False
    assert result.reason == REASON_DAY_CENTER_CLOSED


def test_closed_check_runs_after_enrollment_and_auth():
    from monthly_schedule.per_day import REASON_DAY_NOT_ENROLLED
    cal = CenterCalendar([], _open_days(2, 4))
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(enrolled=False), PLAN_RULES, calendar=cal)
    assert result.reason == REASON_DAY_NOT_ENROLLED


def test_open_day_with_calendar_is_eligible():
    cal = CenterCalendar([], ALL_WEEK)
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(), PLAN_RULES, calendar=cal)
    assert result.eligible is True


def test_month_failure_when_authorized_weekdays_all_closed():
    from monthly_schedule.per_day import REASON_NO_ELIGIBLE_DAYS
    cal = CenterCalendar([], _open_days(2, 4))
    failure = compute_month_failure(
        2026, 5, _ctx(authorized="1,3,5"), calendar=cal)
    assert failure == REASON_NO_ELIGIBLE_DAYS


def test_month_failure_none_when_calendar_open():
    cal = CenterCalendar([], ALL_WEEK)
    assert compute_month_failure(2026, 5, _ctx(), calendar=cal) is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_per_day.py -q`
Expected: the new tests fail with `TypeError: ... unexpected keyword argument 'calendar'` / ImportError for the constant.

- [ ] **Step 3: Implement**

In `monthly_schedule/per_day.py`:

Add after `REASON_DAY_ABSENT`:

```python
REASON_DAY_CENTER_CLOSED = "center closed on this day"
```

Change the signature and insert the check between the authorization lookup and the weekday check:

```python
def compute_day_eligibility(day: date, ctx, plan_rules, calendar=None) -> DayEligibility:
    """Run the ordered eligibility checks for one calendar day.

    `calendar` (a CenterCalendar) rejects company holidays and closed
    weekdays right after the authorization check; None skips that
    check. The day bounds are read from `plan_rules` as given — callers
    that want per-weekday hours pass `calendar.rules_for(day, rules)`."""
    if not ctx.is_enrolled(day):
        return DayEligibility(eligible=False, reason=REASON_DAY_NOT_ENROLLED)

    auth = ctx.active_authorization(day)
    if auth is None:
        return DayEligibility(eligible=False, reason=REASON_DAY_NO_AUTH)

    if calendar is not None and calendar.is_closed(day):
        return DayEligibility(eligible=False, reason=REASON_DAY_CENTER_CLOSED)

    authorized = get_authorized_weekdays(auth["auth_days"])
    ...   # rest unchanged
```

In `compute_month_failure`, add the `calendar=None` parameter and skip closed days before the weekday test:

```python
def compute_month_failure(year: int, month: int, ctx,
                           start_day=None, end_day=None, calendar=None):
    """Return a whole-member failure reason string for the requested
    range (defaults to the full month), or None if the member has at
    least one eligible day in that range. Days the center is closed
    (per `calendar`) count as unschedulable, like wrong weekdays."""
    ...
    for d in days:
        if not ctx.is_enrolled(d):
            continue
        auth = ctx.active_authorization(d)
        if auth is None:
            continue
        if calendar is not None and calendar.is_closed(d):
            continue
        if d.isoweekday() not in get_authorized_weekdays(auth["auth_days"]):
            continue
        has_schedulable = True
        ...
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_per_day.py tests/test_eligibility.py -q`
Expected: all pass (existing tests untouched because `calendar` defaults to None).

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/per_day.py tests/test_per_day.py
git commit -m "feat: reject center-closed days in eligibility and month failure"
```

---

### Task 6: Rows and debug report use per-day rules

**Files:**
- Modify: `monthly_schedule/rows.py`
- Test: `tests/test_rows.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rows.py` (add `from monthly_schedule.center_calendar import CenterCalendar` and `from monthly_schedule.rows import TIME_KEYS` to the imports):

```python
def _calendar(open_days=(1, 2, 3, 4, 5, 6, 7), holidays=(),
              opening="08:00", closing="16:00"):
    return CenterCalendar(
        [{"id": i + 1, "name": name, "date": day}
         for i, (name, day) in enumerate(holidays)],
        [{"id": d, "day_name": "", "day_of_week": d,
          "opening_time": opening, "closing_time": closing}
         for d in open_days],
    )


def test_build_rows_holiday_is_blank_and_ineligible():
    cal = _calendar(holidays=[("Test Holiday", date(2026, 5, 4))])
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES,
                      random.Random(0), calendar=cal)
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["status"] == "ineligible"
    assert all(mon[k] == "" for k in TIME_KEYS)
    wed = next(r for r in rows if r["date"] == date(2026, 5, 6))
    assert wed["status"] == "attended"


def test_build_rows_closed_weekday_is_blank():
    cal = _calendar(open_days=(2, 4))               # Tue/Thu only
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES,
                      random.Random(0), calendar=cal)
    assert all(r["status"] == "ineligible" for r in rows)


def test_build_rows_uses_weekday_opening_and_closing():
    cal = _calendar(opening="09:30", closing="15:00")
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES,
                      random.Random(1), calendar=cal)
    attended = [r for r in rows if r["status"] == "attended"]
    assert attended
    for r in attended:
        assert _to_min(r["time_in"]) >= _to_min("09:30")
        assert _to_min(r["time_out"]) <= _to_min("15:00")


def test_build_rows_cache_regenerates_when_hours_change():
    """A cached day generated under 08:00 bounds must not be reused
    once that weekday opens at 12:00."""
    ctx = _ctx_full_month("1,3,5")
    cache = {}
    build_rows(2026, 5, ctx, PLAN_RULES, random.Random(0),
               time_cache=cache, center_id=1, plan="HF", travel_minutes=10,
               calendar=_calendar(opening="08:00"))
    rows = build_rows(2026, 5, ctx, PLAN_RULES, random.Random(0),
                      time_cache=cache, center_id=1, plan="HF",
                      travel_minutes=10, calendar=_calendar(opening="12:00"))
    for r in rows:
        if r["status"] == "attended":
            assert _to_min(r["time_in"]) >= _to_min("12:00")


def test_debug_rows_holiday_sentence():
    cal = _calendar(holidays=[("Test Holiday", date(2026, 5, 4))])
    rows = build_debug_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES,
                            calendar=cal)
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["scheduled"] is False
    assert mon["reason"] == "Center closed (Test Holiday)"


def test_debug_rows_closed_weekday_sentence():
    cal = _calendar(open_days=(2, 4))
    rows = build_debug_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES,
                            calendar=cal)
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["reason"] == "Center closed on Mondays"


def test_debug_rows_open_day_window_uses_weekday_hours():
    cal = _calendar(opening="09:00", closing="15:00")
    rows = build_debug_rows(2026, 5, _ctx_full_month("1,3,5"), PLAN_RULES,
                            calendar=cal)
    mon = next(r for r in rows if r["date"] == date(2026, 5, 4))
    assert mon["scheduled"] is True
    assert mon["placement_window"] == "09:00-15:00"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rows.py -q -k "holiday or closed or weekday_opening or hours_change"`
Expected: `TypeError: build_rows() got an unexpected keyword argument 'calendar'`.

- [ ] **Step 3: Implement**

In `monthly_schedule/rows.py`:

Imports: add `from monthly_schedule.center_calendar import CenterCalendar, DAY_NAME`, add `REASON_DAY_CENTER_CLOSED` to the `per_day` import list, and **delete** the local `DAY_NAME = {...}` dict (keep `DAY_ABBR`).

`build_rows`: add `calendar=None` as the last parameter. Replace the `plan_default_window = (...)` assignment and the loop head with:

```python
    if calendar is None:
        calendar = CenterCalendar.always_open()
    band = band_for_member(center_id, plan_rules)
    for day in get_month_dates(year, month, start_day, end_day):
        # Per-weekday day bounds from OperatingDays (or the plan's own
        # when the calendar carries none). Everything below — the
        # eligibility window, the generator, the cache guard — reads
        # these rules, so a changed opening time invalidates only that
        # weekday's cached times.
        day_rules = calendar.rules_for(day, plan_rules)
        plan_default_window = (
            parse_hhmm(day_rules["earliest_time_in"]),
            parse_hhmm(day_rules["latest_time_out"]),
        )
        row = {"date": day, "day": DAY_ABBR[day.isoweekday()]}
        result = compute_day_eligibility(day, ctx, day_rules,
                                         calendar=calendar)
```

and in the same loop change `build_daily_schedule(plan_rules, rng, ...)` to `build_daily_schedule(day_rules, rng, ...)`. Add to the docstring: "`calendar` (CenterCalendar) supplies holidays, closed weekdays and per-weekday day bounds; None means always open with the plan's bounds."

`_simple_reason`: add a trailing `closed=None` parameter and, before the final `return reason`, insert:

```python
    if reason == REASON_DAY_CENTER_CLOSED:
        if closed is not None and closed[0] == "holiday":
            name = closed[1]
            return (f"Center closed ({name})" if name
                    else "Center closed (holiday)")
        return f"Center closed on {DAY_NAME[day.isoweekday()]}s"
```

and document it: "`closed` is the calendar's `closed_reason` tuple for the day (or None)."

`build_debug_rows`: add `calendar=None` as the last parameter; at the top add `if calendar is None: calendar = CenterCalendar.always_open()`. Inside the loop, right after `for day in ...:`, add `day_rules = calendar.rules_for(day, plan_rules)` and `closed = calendar.closed_reason(day)`. Then:

- `compute_day_eligibility(day, ctx, plan_rules)` → `compute_day_eligibility(day, ctx, day_rules, calendar=calendar)`
- `_simple_reason(raw_reason, day, authorized, absence, availability)` → `_simple_reason(raw_reason, day, authorized, absence, availability, closed)`
- the `if window is None and scheduled:` fallback reads `day_rules["earliest_time_in"]` / `day_rules["latest_time_out"]`
- `max_len = max(0, min(plan_rules["session_length_min"][1], ...))` → `day_rules[...]`
- `_reason_detail(raw_reason, availability, reserve, in_lo, out_hi, plan_rules, avail_row, pickup_reserve)` → pass `day_rules`

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rows.py tests/test_workbook.py tests/test_activity_log_workbook.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/rows.py tests/test_rows.py
git commit -m "feat: rows and debug report honor the center calendar"
```

---

### Task 7: Callers build the calendar once per run

**Files:**
- Modify: `new_monthly_schedule.py`
- Modify: `gui/worker.py`
- Modify: `scripts/audit_enrollment_gate.py`
- Test: `tests/test_cli.py`, `tests/test_schedule_worker.py`, `tests/test_audit_enrollment_gate.py`

- [ ] **Step 1: Update the test stubs (they fail otherwise once the fetchers are called)**

In `tests/test_cli.py`, inside the stub helper that already contains `monkeypatch.setattr(cli, "get_one_offs", lambda cid, db: [])`, add right after it:

```python
    monkeypatch.setattr(cli, "get_holidays", lambda db: [])
    monkeypatch.setattr(cli, "get_operating_days", lambda db: _OPEN_ALL_WEEK)
```

and define near the top of the file (after the imports):

```python
_OPEN_ALL_WEEK = [
    {"id": d, "day_name": "", "day_of_week": d,
     "opening_time": "08:00", "closing_time": "16:00"}
    for d in range(1, 8)
]
```

In `tests/test_schedule_worker.py`, inside `_stub_db_and_caches`, after the `for name in (...)` loop add:

```python
    monkeypatch.setattr("gui.worker.get_holidays", lambda db: [])
    monkeypatch.setattr(
        "gui.worker.get_operating_days",
        lambda db: [
            {"id": d, "day_name": "", "day_of_week": d,
             "opening_time": "08:00", "closing_time": "16:00"}
            for d in range(1, 8)
        ],
    )
```

Add a new test to `tests/test_cli.py` proving the calendar reaches `process_member`:

```python
def test_main_passes_calendar_to_process_member(monkeypatch, tmp_path):
    # The autouse `_stub_travel` fixture already stubs the DB fetchers.
    seen = {}

    def fake_process_member(member, ctx, year, month, out_dir, api_key,
                            cache, **kwargs):
        seen["calendar"] = kwargs.get("calendar")
        return (True, None, None, None, None)

    monkeypatch.setattr(cli, "get_member", lambda cid, db: {
        "center_id": 1, "last_name": "B", "first_name": "A",
        "health_plan": "HF", "address": "x", "long_lat": "0,0"})
    monkeypatch.setattr(cli, "process_member", fake_process_member)
    rc = cli.main(["--center-id", "1", "--year", "2026", "--month", "5",
                   "--output-path", str(tmp_path)])
    assert rc == 0
    from monthly_schedule.center_calendar import CenterCalendar
    assert isinstance(seen["calendar"], CenterCalendar)
```

(The `get_*` stubs live in the autouse fixture `_stub_travel` at the top of `tests/test_cli.py`; the two new `monkeypatch.setattr` lines go inside that fixture, after the `get_one_offs` line.)

- [ ] **Step 2: Run to verify the new test fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cli.py -q -k calendar`
Expected: FAIL, `seen["calendar"]` is None.

- [ ] **Step 3: Thread the calendar through `new_monthly_schedule.py`**

Imports: extend the `from monthly_schedule.db import (...)` block with `get_holidays, get_operating_days,` and add `from monthly_schedule.center_calendar import CenterCalendar`.

`collect_debug_rows`: add `calendar=None` as the last parameter and pass `calendar=calendar` into `build_debug_rows(...)`.

`process_member`: add `calendar=None` as the last parameter; change the first line to `failure = compute_month_failure(year, month, ctx, start_day, end_day, calendar=calendar)` and add `calendar=calendar,` to the `build_rows(...)` call. Add to the docstring: "`calendar` is the run's CenterCalendar (holidays, closed weekdays, per-weekday hours); None means always open."

`main()`: directly after the `members = [] / failures = [] / try: ... except (FileNotFoundError, RuntimeError)` block that loads members, add:

```python
    try:
        calendar = CenterCalendar(
            get_holidays(args.db_path), get_operating_days(args.db_path),
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
```

and pass `calendar=calendar` to both the `collect_debug_rows(...)` and `process_member(...)` calls in the member loop.

- [ ] **Step 4: Thread it through `gui/worker.py`**

Extend the `from monthly_schedule.db import (...)` block with `get_holidays, get_operating_days,` and add `from monthly_schedule.center_calendar import CenterCalendar`. Directly after `one_off_idx = get_all_one_offs(self.db_path)` add:

```python
        # Center-wide calendar: holidays and weekly hours. Missing
        # tables fail the run like any other supporting table (re-run
        # Setup to create them).
        calendar = CenterCalendar(
            get_holidays(self.db_path), get_operating_days(self.db_path),
        )
```

Pass `calendar=calendar,` to the `collect_debug_rows(...)` call and to the `process_member(...)` call in the member loop.

- [ ] **Step 5: Thread it through `scripts/audit_enrollment_gate.py`**

Extend the db import block with `get_holidays,` and `get_operating_days,`; add `from monthly_schedule.center_calendar import CenterCalendar  # noqa: E402`. Change `audit_member` to accept `calendar=None` as its last parameter and call `compute_month_failure(year, month, ctx, calendar=calendar)`. In `main()`, add `calendar = CenterCalendar(get_holidays(args.db), get_operating_days(args.db))` inside the same `try` that loads `one_off_idx`, and pass `calendar=calendar` in the `audit_member(...)` call.

- [ ] **Step 6: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_schedule_worker.py tests/test_audit_enrollment_gate.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add new_monthly_schedule.py gui/worker.py scripts/audit_enrollment_gate.py tests/test_cli.py tests/test_schedule_worker.py
git commit -m "feat: CLI, GUI worker and audit script load the center calendar"
```

---

### Task 8: Remove the day-bound fields from Settings

**Files:**
- Modify: `gui/app_settings.py`, `gui/settings_dialog.py`, `gui/i18n.py`
- Test: `tests/test_app_settings.py`, `tests/test_settings_dialog.py`

- [ ] **Step 1: Update the tests**

In `tests/test_app_settings.py`:

- `test_fresh_install_has_default_schedule_rules`: delete the two asserts on `earliest_time_in` / `latest_time_out` and add `assert "earliest_time_in" not in rules` and `assert "latest_time_out" not in rules`.
- Every other test in the file that writes `"earliest_time_in": "09:00"` or `"07:00"` as a stand-in "some saved key" (`test_partial_schedule_rules_fills_in_defaults`, `test_legacy_rule_keys_are_dropped`, `test_dropoff_by_avail_end_missing_key_filled_on`, `test_pickup_by_avail_start_missing_key_filled_on`, `test_band_keys_missing_filled_off`): replace the key with `"morning_percent": 70` and the matching assert with `assert rules["morning_percent"] == 70` (or `s["schedule_rules"]["morning_percent"] == 70` where the test uses `s`).
- `test_defaults_not_mutated_after_load`: set `s["schedule_rules"]["morning_percent"] = 1` and assert `fresh["schedule_rules"]["morning_percent"] == 80`.
- Add:

```python
def test_day_bound_keys_are_retired_on_load(settings_file):
    """Hours now live in the database's OperatingDays table; a settings
    file from before that change must not keep the old keys alive."""
    settings_file.write_text(json.dumps({
        "schedule_rules": {"earliest_time_in": "09:00",
                           "latest_time_out": "15:00",
                           "morning_percent": 70},
    }))
    from gui import app_settings
    rules = app_settings.load()["schedule_rules"]
    assert "earliest_time_in" not in rules
    assert "latest_time_out" not in rules
    assert rules["morning_percent"] == 70
```

In `tests/test_settings_dialog.py` add (it needs a QApplication; use the same offscreen pattern as `tests/test_setup_worker.py`, i.e. `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` before importing PyQt6):

```python
def test_dialog_has_no_day_bound_fields():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from gui.settings_dialog import SettingsDialog
    from gui import app_settings
    settings = dict(app_settings.DEFAULTS)        # not the user's live file
    settings["schedule_rules"] = dict(app_settings.DEFAULTS["schedule_rules"])
    dlg = SettingsDialog(settings)                # (settings, parent=None, first_run=False)
    assert not hasattr(dlg, "_earliest_in_edit")
    assert not hasattr(dlg, "_latest_out_edit")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_app_settings.py tests/test_settings_dialog.py -q`
Expected: the retired-keys test and the dialog test fail.

- [ ] **Step 3: Implement**

`gui/app_settings.py`: delete the `"earliest_time_in": "08:00",` and `"latest_time_out": "16:00",` lines from `DEFAULTS["schedule_rules"]`. (The loader already drops saved keys that are not in DEFAULTS, so old files lose them automatically.) Update the comment above `schedule_rules` with: "Day bounds (opening/closing) are not here — they come from the database's OperatingDays table."

`gui/settings_dialog.py`: delete the `_earliest_in_edit` / `_earliest_in_label` block and the `_latest_out_edit` / `_latest_out_label` block (the two `QTimeEdit` rows added to `rules_form`), the two `setText(tr("settings.rules.earliest_in"/"latest_out"))` lines in the retranslate method, the `earliest_in = ...` / `latest_out = ...` lines in `_save`, the `bad = bad or (... _earliest_in_edit ... >= ... _latest_out_edit ...)` clause (keep `bad = any(lo > hi for lo, hi in ranges)`), and the two `"earliest_time_in": earliest_in,` / `"latest_time_out": latest_out,` entries from the saved `schedule_rules` dict. If `QTimeEdit` is now unused in the file, keep the import only if `_RangeTimes` still uses it (it does). Fix the `_save` comment to drop "and the day bounds must be ordered".

`gui/i18n.py`: delete the `"settings.rules.earliest_in"` and `"settings.rules.latest_out"` entries from both the English and Chinese tables. Change `"settings.rules.morning_window"` to `"Morning window length (HH:MM after opening time):"` in English and `"上午时段长度（开门后的 时:分）："` in Chinese.

`monthly_schedule/rules.py`: leave `earliest_time_in` / `latest_time_out` in `SCHEDULE_RULES["Default"]` (they are the fallback) but change their comment to: "Fallback day bounds. In a real run each weekday's bounds come from the OperatingDays table via CenterCalendar.rules_for."

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_app_settings.py tests/test_settings_dialog.py tests/test_i18n.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add gui/app_settings.py gui/settings_dialog.py gui/i18n.py monthly_schedule/rules.py tests/test_app_settings.py tests/test_settings_dialog.py
git commit -m "feat(settings): day bounds move to the OperatingDays table"
```

---

### Task 9: Test-DB scaffold knows the new tables

**Files:**
- Modify: `scripts/make_test_db.py`

- [ ] **Step 1: Add the ensure-and-seed helper**

After `_ensure_plan_type_column`, add:

```python
def _ensure_calendar_tables(conn) -> None:
    """Reference DBs predate the Holidays / OperatingDays tables. Create
    them when absent and seed the 7-day default hours, so every scenario
    runs against the schema the scheduler now requires."""
    from scripts.create_supporting_tables import (
        _CREATE_HOLIDAYS, _CREATE_OPERATING_DAYS,
    )
    from scripts.seed_operating_days import seed_if_empty

    cur = conn.cursor()
    for ddl in (_CREATE_HOLIDAYS, _CREATE_OPERATING_DAYS):
        try:
            cur.execute(ddl)
        except Exception as exc:
            if "42S01" not in str(exc):      # anything but "already exists"
                raise
    seed_if_empty(cur)
    conn.commit()
```

In `main()`, call `_ensure_calendar_tables(conn)` immediately after `_ensure_plan_type_column(conn)`.

Add `"Holidays"` at the front of `SUPPORTING_TABLES` so each scenario starts with no holidays (OperatingDays is deliberately not truncated: the seeded default persists).

- [ ] **Step 2: Give `happy_path` a holiday**

At the end of `seed_happy_path`, before `conn.commit()`, add:

```python
    # One company holiday on the first Wednesday of the month, so the
    # generated timesheet visibly skips a weekday it would otherwise fill.
    first_wed = m1
    while first_wed.isoweekday() != 3:
        first_wed = first_wed + timedelta(days=1)
    cur.execute(
        "INSERT INTO [Holidays] ([holiday_name], [date]) VALUES (?, ?)",
        "Test Holiday", _dt(first_wed),
    )
```

Update the docstring at the top of the file (the scenario list is unchanged) and the `happy_path` docstring: "Center 99001 'Test, Happy' — full happy-path setup plus one company holiday on the first Wednesday."

- [ ] **Step 3: Verify by import and, if the source DB is reachable, by running**

Run: `.venv\Scripts\python.exe -c "import scripts.make_test_db as m; print(m.SUPPORTING_TABLES)"`
Expected: prints a tuple starting with `'Holidays'`.

If `scripts\test_dbs\happy_path.accdb` exists locally: `.venv\Scripts\python.exe scripts\make_test_db.py --scenario happy_path` should print `Seeded scenario 'happy_path' into ...`. Skip this if the reference DB is unavailable; say so in the commit message body.

- [ ] **Step 4: Commit**

```bash
git add scripts/make_test_db.py
git commit -m "test-db: create/seed calendar tables; happy_path gets a holiday"
```

---

### Task 10: Documentation

**Files:**
- Modify: `docs/database.md`, `README.md`

- [ ] **Step 1: `docs/database.md`**

Under **Absences**, delete the paragraph beginning "Center-wide closures (e.g., holidays affecting everyone) are not modeled as a dedicated table" and replace it with: "Center-wide closures are the `Holidays` and `OperatingDays` tables below, not per-member absences."

After the `EmergencyContact` section (or the last table section), add:

```markdown
### Holidays

Company holidays: dates the center is closed for everyone. Entered
through the Members app's Company Calendar dialog.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber | Primary key. |
| holiday_name | Short Text | e.g. `Labor Day`. |
| date | Date/Time | The single closed date. A multi-day closure is one row per day. |

**Semantics:** day `D` is a holiday iff any row's `date` equals `D`.
The scheduler generates no times that day; it is blank on the
timesheet, the activity log and the billing sheet (not an absence).
The debug CSV says `Center closed (<holiday_name>)`.

### OperatingDays

Weekly operating hours, one row per **open** weekday. A weekday with
no row is closed. Seeded Monday–Sunday 08:00–16:00 by
[scripts/seed_operating_days.py](../scripts/seed_operating_days.py)
when the table is empty; edited through the Members app.

| Field | Type | Notes |
| --- | --- | --- |
| ID | AutoNumber | Primary key. |
| day_name | Short Text | `Monday` … `Sunday`, for readability in Access. |
| Day Of Week | Number (LONG) | 1 = Monday … 7 = Sunday, the same convention as `Availability.[Day Of Week]`. The scheduler matches on this column, never on `day_name`. |
| opening_time | Date/Time | Time-of-day only (`1899-12-30 HH:MM`), like `Availability.avail_start`. |
| closing_time | Date/Time | Same. Later than `opening_time`. |

**Semantics:** weekday `W` is open iff a row with `[Day Of Week] = W`
exists; if several exist, the largest `ID` wins. On an open day the
row's `opening_time` / `closing_time` replace the plan rules'
`earliest_time_in` / `latest_time_out` (the hard day bounds). A closed
weekday is blank like a non-authorized weekday; the debug CSV says
`Center closed on Sundays`. Implementation:
[monthly_schedule/center_calendar.py](../monthly_schedule/center_calendar.py).
```

- [ ] **Step 2: `README.md`**

In the **Database schema** section, change "The scheduler reads from five Access tables: `Contacts` plus the four supporting tables `Enrollment`, `Authorization`, `Absences`, and `Availability`." to "The scheduler reads from `Contacts`, the per-member tables `Enrollment`, `Authorization`, `Absences`, `Availability` and `OneOffAvailability`, and the center-wide `Holidays` and `OperatingDays` tables." Append to the eligibility sentence: "…and the center is open that day (not a holiday, and the weekday has an `OperatingDays` row, whose opening and closing times are the day's bounds)."

- [ ] **Step 3: Commit**

```bash
git add docs/database.md README.md
git commit -m "docs: Holidays and OperatingDays tables"
```

---

### Task 11: Full test run and packaged exes

- [ ] **Step 1: Run the whole suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass. Fix anything that regressed before continuing.

- [ ] **Step 2: Rebuild the two affected executables**

The scheduler exe and the Setup GUI exe both changed (`monthly_schedule/`, `gui/`, `scripts/`, `setup_gui/`). Ask the user to close any running copies first, then:

```
.venv\Scripts\pyinstaller MonthlyScheduleGenerator.spec --noconfirm
.venv\Scripts\pyinstaller BSCASetup.spec --noconfirm
```

Expected: `dist\MonthlyScheduleGenerator.exe` and the Setup exe in `dist\` with fresh timestamps.

- [ ] **Step 3: Smoke-check the Setup chain against a copy of a real database**

Run the Setup GUI on a **copy** of the production `.accdb` (it makes its own backup as step 0). Expected log lines include `CREATED  Holidays`, `CREATED  OperatingDays`, and `Seeded 7 operating days (Mon-Sun, 08:00-16:00)`. Then run the scheduler GUI once against that copy for the current month with Debug on: the debug CSV shows `Center closed on ...` only if a weekday was unchecked, and no times outside 08:00–16:00.

- [ ] **Step 4: Commit any spec/exe metadata changes**

```bash
git status
git add -A
git commit -m "build: rebuild scheduler and setup exes for calendar tables"
```

(Only if the `.spec` files or tracked build metadata changed; `dist/` and `build/` are gitignored.)
