# Attendance → Availability Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Estimate each active member's per-weekday availability window from the Time-In / Time-Out values on the last three months of Attendance sheets and write it to the `Availability` table, with a report CSV of what changed and what needs a human look.

**Architecture:** A pure module `monthly_schedule/attendance_envelope.py` (time normalization, filename parsing, envelope math, flags — no IO) and a thin CLI `scripts/backfill_availability_from_attendance.py` that walks the month folders with openpyxl, reads active members from Access via pyodbc, upserts the open `Availability` row per (member, weekday) in one transaction, and writes the report. Tests cover the pure module directly and the CLI with a fake cursor, exactly like `tests/test_apply_hha_answers.py`.

**Tech Stack:** Python 3.11, openpyxl (read-only), pyodbc + Microsoft Access ODBC driver, pytest. Run everything from the BSCA repo root with `.venv\Scripts\python.exe` / `.venv\Scripts\pytest`.

**Spec:** `docs/superpowers/specs/2026-09-15-attendance-availability-backfill-design.md`

---

## File structure

| File | Responsibility |
| --- | --- |
| `monthly_schedule/attendance_envelope.py` (create) | Pure logic: `hhmm`, `normalize_time`, `parse_sheet_filename`, `collect_samples`, `round_window`, `window_flags`, `Estimate`, `estimate_windows`. |
| `scripts/backfill_availability_from_attendance.py` (create) | CLI: args, month defaults, sheet walk, DB reads, upsert, backup copy, report CSV, summary. |
| `tests/test_attendance_envelope.py` (create) | Unit tests for the pure module. |
| `tests/test_backfill_availability_from_attendance.py` (create) | CLI tests with a fake cursor/conn and a temp Attendance folder built with openpyxl. |
| `scripts/README.md` (modify) | Add the script to the table. |
| `README.md` (modify) | Add a "Backfill Availability from Attendance sheets" section. |

Conventions to follow (from the existing backfills): scripts insert the repo root into `sys.path` so `from monthly_schedule import …` works; DB helpers take a `cur`; SQL strings are module constants; Access time-of-day values arrive as `datetime.datetime(1899, 12, 30, H, M)`; `--dry-run` rolls back; CSVs are `utf-8-sig`.

---

### Task 1: `hhmm` and `normalize_time`

**Files:**
- Create: `monthly_schedule/attendance_envelope.py`
- Create: `tests/test_attendance_envelope.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_attendance_envelope.py
import datetime

import pytest

from monthly_schedule.attendance_envelope import (
    hhmm,
    normalize_time,
)


# ---------------------------------------------------------------------------
# hhmm
# ---------------------------------------------------------------------------

def test_hhmm_formats_minutes():
    assert hhmm(0) == "00:00"
    assert hhmm(8 * 60 + 5) == "08:05"
    assert hhmm(14 * 60) == "14:00"


# ---------------------------------------------------------------------------
# normalize_time — Attendance sheets store 12-hour clock times without AM/PM
# ---------------------------------------------------------------------------

def test_normalize_time_morning_time_object():
    assert normalize_time(datetime.time(8, 21)) == 8 * 60 + 21


def test_normalize_time_before_six_is_pm():
    assert normalize_time(datetime.time(2, 0)) == 14 * 60
    assert normalize_time(datetime.time(5, 59)) == 17 * 60 + 59


def test_normalize_time_six_is_am():
    assert normalize_time(datetime.time(6, 0)) == 6 * 60


def test_normalize_time_accepts_datetime():
    assert normalize_time(datetime.datetime(1899, 12, 30, 1, 33)) == 13 * 60 + 33


def test_normalize_time_accepts_excel_fraction():
    assert normalize_time(0.5) == 12 * 60          # noon
    assert normalize_time(0.0625) == 13 * 60 + 30  # 1.5h -> 01:30 -> PM


def test_normalize_time_accepts_hhmm_string():
    assert normalize_time("09:41") == 9 * 60 + 41
    assert normalize_time("1:20") == 13 * 60 + 20


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_normalize_time_blank_is_none(blank):
    assert normalize_time(blank) is None


def test_normalize_time_rejects_garbage():
    assert normalize_time("lunch") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests\test_attendance_envelope.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monthly_schedule.attendance_envelope'`

- [ ] **Step 3: Write the minimal implementation**

```python
# monthly_schedule/attendance_envelope.py
"""Pure logic for estimating Availability windows from Attendance sheets.

No IO, no DB. See
docs/superpowers/specs/2026-09-15-attendance-availability-backfill-design.md
"""
import datetime
import re
from dataclasses import dataclass, field

# Attendance sheets store clock times in 12-hour form without AM/PM.
# Anything before this is read as PM (a member never signs in before 06:00).
PM_CUTOFF_MIN = 6 * 60


def hhmm(minutes):
    """Minutes since midnight -> 'HH:MM'."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _apply_pm_rule(minutes):
    return minutes + 12 * 60 if minutes < PM_CUTOFF_MIN else minutes


def normalize_time(value):
    """Cell value -> minutes since midnight, or None when blank/unparseable.

    Accepts datetime.time, datetime.datetime (Access placeholder date),
    an Excel day fraction, or an 'H:MM' string. Values before 06:00 are
    read as PM.
    """
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        value = value.time()
    if isinstance(value, datetime.time):
        return _apply_pm_rule(value.hour * 60 + value.minute)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _apply_pm_rule(int(round(value * 24 * 60)) % (24 * 60))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
        if not m:
            return None
        return _apply_pm_rule(int(m.group(1)) * 60 + int(m.group(2)))
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests\test_attendance_envelope.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/attendance_envelope.py tests/test_attendance_envelope.py
git commit -m "feat(attendance): time normalization for Attendance sheets"
```

---

### Task 2: `parse_sheet_filename`

**Files:**
- Modify: `monthly_schedule/attendance_envelope.py`
- Modify: `tests/test_attendance_envelope.py`

- [ ] **Step 1: Write the failing tests** (append to the test file; extend the import)

```python
from monthly_schedule.attendance_envelope import (
    hhmm,
    normalize_time,
    parse_sheet_filename,
)


# ---------------------------------------------------------------------------
# parse_sheet_filename
# ---------------------------------------------------------------------------

def test_parse_sheet_filename_real_pattern():
    assert parse_sheet_filename(
        "(1001).Zhang, Mingli Attendance 2026-08.xlsm"
    ) == (1001, "Zhang, Mingli", "2026-08")


def test_parse_sheet_filename_tolerates_spaces_and_case():
    assert parse_sheet_filename(
        "(25).Lin,  Bo Hua  Attendance 2026-07.XLSM"
    ) == (25, "Lin,  Bo Hua", "2026-07")


@pytest.mark.parametrize("name", [
    "Daily Sign-in-out 2026-08.xlsm",
    "(1001).Zhang, Mingli TP 2026-08.xlsm",
    "Zhang, Mingli Attendance 2026-08.xlsm",
    "~$(1001).Zhang, Mingli Attendance 2026-08.xlsm",
])
def test_parse_sheet_filename_rejects_other_files(name):
    assert parse_sheet_filename(name) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests\test_attendance_envelope.py -v -k filename`
Expected: FAIL — `ImportError: cannot import name 'parse_sheet_filename'`

- [ ] **Step 3: Write the minimal implementation** (append to the module)

```python
_FILENAME_RE = re.compile(
    r"^\((\d+)\)\.(.+?)\s+Attendance\s+(\d{4}-\d{2})\.xlsm$", re.IGNORECASE,
)


def parse_sheet_filename(name):
    """'(1001).Zhang, Mingli Attendance 2026-08.xlsm'
    -> (1001, 'Zhang, Mingli', '2026-08'); None for anything else
    (Excel lock files starting with '~$' included)."""
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    return int(m.group(1)), m.group(2).strip(), m.group(3)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests\test_attendance_envelope.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/attendance_envelope.py tests/test_attendance_envelope.py
git commit -m "feat(attendance): parse Attendance sheet filenames"
```

---

### Task 3: `collect_samples`

**Files:**
- Modify: `monthly_schedule/attendance_envelope.py`
- Modify: `tests/test_attendance_envelope.py`

- [ ] **Step 1: Write the failing tests** (append; extend import with `collect_samples`)

```python
# ---------------------------------------------------------------------------
# collect_samples — rows: (center_id, iso_weekday, time_in_min, time_out_min)
# ---------------------------------------------------------------------------

def test_collect_samples_groups_by_member_and_weekday():
    rows = [
        (1001, 1, 500, 745),
        (1001, 1, 505, 750),
        (1001, 2, 510, 755),
        (1002, 1, 600, 840),
    ]
    samples, dropped = collect_samples(rows)
    assert samples == {
        (1001, 1): [(500, 745), (505, 750)],
        (1001, 2): [(510, 755)],
        (1002, 1): [(600, 840)],
    }
    assert dropped == 0


def test_collect_samples_drops_out_not_after_in():
    rows = [(1001, 1, 500, 500), (1001, 1, 600, 550), (1001, 1, 500, 745)]
    samples, dropped = collect_samples(rows)
    assert samples == {(1001, 1): [(500, 745)]}
    assert dropped == 2


def test_collect_samples_skips_rows_missing_a_time():
    rows = [(1001, 1, None, 745), (1001, 1, 500, None), (1001, 1, 500, 745)]
    samples, dropped = collect_samples(rows)
    assert samples == {(1001, 1): [(500, 745)]}
    assert dropped == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests\test_attendance_envelope.py -v -k collect`
Expected: FAIL — `ImportError: cannot import name 'collect_samples'`

- [ ] **Step 3: Write the minimal implementation** (append)

```python
def collect_samples(rows):
    """Group (center_id, iso_weekday, in_min, out_min) rows into
    {(center_id, weekday): [(in, out), ...]}.

    Rows with either time missing are skipped silently (a day with no
    visit). Rows whose Time-Out is not after Time-In are dropped and
    counted; returns (samples, dropped_count).
    """
    samples = {}
    dropped = 0
    for center_id, weekday, time_in, time_out in rows:
        if time_in is None or time_out is None:
            continue
        if time_out <= time_in:
            dropped += 1
            continue
        samples.setdefault((center_id, weekday), []).append(
            (time_in, time_out))
    return samples, dropped
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests\test_attendance_envelope.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/attendance_envelope.py tests/test_attendance_envelope.py
git commit -m "feat(attendance): collect per-weekday samples"
```

---

### Task 4: `round_window` and `window_flags`

**Files:**
- Modify: `monthly_schedule/attendance_envelope.py`
- Modify: `tests/test_attendance_envelope.py`

- [ ] **Step 1: Write the failing tests** (append; extend import with `round_window`, `window_flags`)

```python
# ---------------------------------------------------------------------------
# round_window — start down, end up, to 5 minutes
# ---------------------------------------------------------------------------

def test_round_window_rounds_outward():
    assert round_window(8 * 60 + 21, 12 * 60 + 23) == (8 * 60 + 20, 12 * 60 + 25)


def test_round_window_keeps_exact_multiples():
    assert round_window(8 * 60 + 20, 12 * 60 + 25) == (8 * 60 + 20, 12 * 60 + 25)


# ---------------------------------------------------------------------------
# window_flags
# ---------------------------------------------------------------------------

def test_window_flags_plain_morning_window():
    assert window_flags(8 * 60 + 20, 12 * 60 + 25, closing_min=14 * 60) == []


def test_window_flags_past_close():
    assert window_flags(9 * 60 + 55, 14 * 60 + 25, closing_min=14 * 60) == ["past_close"]


def test_window_flags_afternoon_only_and_past_close():
    assert window_flags(12 * 60 + 30, 17 * 60 + 25, closing_min=14 * 60) == [
        "past_close", "afternoon_only",
    ]


def test_window_flags_afternoon_boundary_is_inclusive():
    assert "afternoon_only" in window_flags(10 * 60 + 30, 15 * 60, closing_min=16 * 60)
    assert "afternoon_only" not in window_flags(10 * 60 + 29, 15 * 60, closing_min=16 * 60)


def test_window_flags_narrow():
    assert window_flags(8 * 60, 11 * 60 + 55, closing_min=14 * 60) == ["narrow"]
    assert "narrow" not in window_flags(8 * 60, 12 * 60, closing_min=14 * 60)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests\test_attendance_envelope.py -v -k "round or flags"`
Expected: FAIL — ImportError

- [ ] **Step 3: Write the minimal implementation** (append)

```python
ROUND_STEP_MIN = 5
AFTERNOON_START_MIN = 10 * 60 + 30   # Time-In at/after this -> afternoon_only
NARROW_WIDTH_MIN = 240               # under this -> narrow


def round_window(start, end):
    """Round start DOWN and end UP to ROUND_STEP_MIN (outward)."""
    lo = (start // ROUND_STEP_MIN) * ROUND_STEP_MIN
    hi = -(-end // ROUND_STEP_MIN) * ROUND_STEP_MIN
    return lo, hi


def window_flags(start, end, closing_min):
    """Report flags for a window against the day's closing time.
    Order is fixed: past_close, afternoon_only, narrow."""
    flags = []
    if end > closing_min:
        flags.append("past_close")
    if start >= AFTERNOON_START_MIN:
        flags.append("afternoon_only")
    if end - start < NARROW_WIDTH_MIN:
        flags.append("narrow")
    return flags
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests\test_attendance_envelope.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/attendance_envelope.py tests/test_attendance_envelope.py
git commit -m "feat(attendance): outward rounding and report flags"
```

---

### Task 5: `Estimate` and `estimate_windows`

**Files:**
- Modify: `monthly_schedule/attendance_envelope.py`
- Modify: `tests/test_attendance_envelope.py`

- [ ] **Step 1: Write the failing tests** (append; extend import with `Estimate`, `estimate_windows`)

```python
# ---------------------------------------------------------------------------
# estimate_windows — {weekday: [(in, out), ...]} -> {1..7: Estimate}
# ---------------------------------------------------------------------------

def _samples(n, lo_in, hi_in, lo_out, hi_out):
    """n samples spread evenly between the given bounds."""
    if n == 1:
        return [(lo_in, lo_out)]
    return [
        (lo_in + (hi_in - lo_in) * i // (n - 1),
         lo_out + (hi_out - lo_out) * i // (n - 1))
        for i in range(n)
    ]


def test_estimate_windows_per_weekday_envelope_rounded_outward():
    member = {
        d: _samples(13, 8 * 60 + 21, 8 * 60 + 33, 12 * 60 + 18, 12 * 60 + 33)
        for d in (1, 2, 3, 4, 5)
    }
    est = estimate_windows(member, min_samples=4)
    assert est[1] == Estimate(start=8 * 60 + 20, end=12 * 60 + 35,
                              samples=13, flags=[])


def test_estimate_windows_low_samples_widen_to_member_envelope():
    member = {
        1: _samples(13, 8 * 60 + 21, 8 * 60 + 33, 12 * 60 + 18, 12 * 60 + 33),
        6: [(8 * 60 + 40, 12 * 60 + 40), (8 * 60 + 41, 12 * 60 + 42)],
    }
    est = estimate_windows(member, min_samples=4)
    # Saturday union: start = min(8:40, 8:21)=8:21 -> 8:20;
    #                 end   = max(12:42, 12:33)=12:42 -> 12:45
    assert est[6] == Estimate(start=8 * 60 + 20, end=12 * 60 + 45,
                              samples=2, flags=["low_samples"])


def test_estimate_windows_no_data_weekday_gets_member_envelope():
    member = {1: _samples(13, 8 * 60 + 21, 8 * 60 + 33, 12 * 60 + 18, 12 * 60 + 33)}
    est = estimate_windows(member, min_samples=4)
    assert set(est) == {1, 2, 3, 4, 5, 6, 7}
    assert est[3] == Estimate(start=8 * 60 + 20, end=12 * 60 + 35,
                              samples=0, flags=["member_wide"])


def test_estimate_windows_empty_member_is_empty():
    assert estimate_windows({}, min_samples=4) == {}


def test_estimate_windows_afternoon_member_keeps_afternoon():
    member = {2: _samples(13, 12 * 60 + 32, 12 * 60 + 47, 16 * 60 + 50, 16 * 60 + 59)}
    est = estimate_windows(member, min_samples=4)
    assert est[2].start == 12 * 60 + 30
    assert est[2].end == 17 * 60
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests\test_attendance_envelope.py -v -k estimate`
Expected: FAIL — ImportError

- [ ] **Step 3: Write the minimal implementation** (append)

```python
DEFAULT_MIN_SAMPLES = 4


@dataclass
class Estimate:
    """One weekday's estimated window (minutes since midnight, already
    rounded) with the per-weekday sample count and provenance flags
    (subset of: low_samples, member_wide)."""
    start: int
    end: int
    samples: int
    flags: list = field(default_factory=list)


def _envelope(pairs):
    return min(p[0] for p in pairs), max(p[1] for p in pairs)


def estimate_windows(samples_by_weekday, min_samples=DEFAULT_MIN_SAMPLES):
    """Spec §3. `samples_by_weekday` is {iso_weekday: [(in, out), ...]}
    for ONE member. Returns {1..7: Estimate}, or {} when the member has
    no samples at all.

    - A weekday with >= min_samples samples gets its own envelope.
    - A weekday with 1..min_samples-1 samples gets the union of its own
      envelope and the member-wide envelope (flag low_samples).
    - A weekday with no samples gets the member-wide envelope
      (flag member_wide).
    Windows are rounded outward to 5 minutes.
    """
    all_pairs = [p for pairs in samples_by_weekday.values() for p in pairs]
    if not all_pairs:
        return {}
    member_lo, member_hi = _envelope(all_pairs)

    result = {}
    for weekday in range(1, 8):
        pairs = samples_by_weekday.get(weekday) or []
        flags = []
        if not pairs:
            lo, hi = member_lo, member_hi
            flags.append("member_wide")
        else:
            lo, hi = _envelope(pairs)
            if len(pairs) < min_samples:
                lo, hi = min(lo, member_lo), max(hi, member_hi)
                flags.append("low_samples")
        lo, hi = round_window(lo, hi)
        result[weekday] = Estimate(start=lo, end=hi, samples=len(pairs),
                                   flags=flags)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests\test_attendance_envelope.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/attendance_envelope.py tests/test_attendance_envelope.py
git commit -m "feat(attendance): per-weekday window estimation"
```

---

### Task 6: CLI skeleton — args, default months, sheet reader

**Files:**
- Create: `scripts/backfill_availability_from_attendance.py`
- Create: `tests/test_backfill_availability_from_attendance.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backfill_availability_from_attendance.py
import datetime
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import backfill_availability_from_attendance as mod


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _t(hour, minute=0):
    """Time-of-day as Access/pyodbc returns it."""
    return datetime.datetime(1899, 12, 30, hour, minute)


def _write_attendance_sheet(folder, center_id, name, month, days):
    """Create '<folder>/(id).Name Attendance YYYY-MM.xlsm' with one row per
    calendar day; `days` maps day-number -> (time_in, time_out) as
    datetime.time (12-hour, no AM/PM, like the real sheets)."""
    folder.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    wb.active.title = "Template"
    ws = wb.create_sheet("Attendance")
    ws["A1"] = f"Name: {name}(1.2.3)   Month, 2026  ID: {center_id}  MLTC: X"
    ws.append(["Date", "Day", "Time-In", "Time-Out"])
    year, mon = (int(p) for p in month.split("-"))
    import calendar
    for d in range(1, calendar.monthrange(year, mon)[1] + 1):
        dow = datetime.date(year, mon, d).strftime("%a")
        ti, to = days.get(d, (None, None))
        ws.append([d, dow, ti, to])
    path = folder / f"({center_id}).{name} Attendance {month}.xlsm"
    wb.save(path)   # openpyxl writes xlsx bytes; the reader only cares about the name
    return path


# ---------------------------------------------------------------------------
# _default_months
# ---------------------------------------------------------------------------

def test_default_months_three_ending_this_month():
    assert mod._default_months(datetime.date(2026, 9, 15)) == [
        "2026-07", "2026-08", "2026-09"]


def test_default_months_wraps_year():
    assert mod._default_months(datetime.date(2026, 1, 3)) == [
        "2025-11", "2025-12", "2026-01"]


def test_parse_months_flag():
    assert mod._parse_months("2026-07, 2026-08,2026-09") == [
        "2026-07", "2026-08", "2026-09"]
    with pytest.raises(ValueError):
        mod._parse_months("July 2026")


# ---------------------------------------------------------------------------
# read_month_sheets — yields (center_id, iso_weekday, in_min, out_min)
# ---------------------------------------------------------------------------

def test_read_month_sheets_yields_normalized_rows(tmp_path):
    att = tmp_path / "2026" / "08" / "Attendance"
    _write_attendance_sheet(att, 1001, "Zhang, Mingli", "2026-08", {
        3: (datetime.time(8, 21), datetime.time(12, 23)),   # Mon
        4: (datetime.time(9, 41), datetime.time(2, 0)),     # Tue, 02:00 -> 14:00
    })
    (att / "Daily Sign-in-out 2026-08.xlsm").write_bytes(b"")  # ignored by name
    errors = []
    rows = list(mod.read_month_sheets(tmp_path, "2026-08", errors.append))
    assert rows == [
        (1001, 1, 8 * 60 + 21, 12 * 60 + 23),
        (1001, 2, 9 * 60 + 41, 14 * 60),
    ]
    assert errors == []


def test_read_month_sheets_reports_unreadable_file(tmp_path):
    att = tmp_path / "2026" / "07" / "Attendance"
    att.mkdir(parents=True)
    (att / "(5).Bad, File Attendance 2026-07.xlsm").write_bytes(b"not a workbook")
    errors = []
    rows = list(mod.read_month_sheets(tmp_path, "2026-07", errors.append))
    assert rows == []
    assert len(errors) == 1 and "(5).Bad, File" in errors[0]


def test_read_month_sheets_missing_folder_is_an_error(tmp_path):
    errors = []
    rows = list(mod.read_month_sheets(tmp_path, "2026-06", errors.append))
    assert rows == []
    assert len(errors) == 1 and "2026-06" in errors[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests\test_backfill_availability_from_attendance.py -v`
Expected: FAIL — `ImportError: cannot import name 'backfill_availability_from_attendance'`

- [ ] **Step 3: Write the minimal implementation**

```python
# scripts/backfill_availability_from_attendance.py
"""Estimate Availability windows from printed Attendance sheets.

For every active member (open Enrollment row), reads the Time-In /
Time-Out values on the last three months of Attendance sheets, takes the
per-weekday envelope (earliest Time-In, latest Time-Out) and writes it to
the currently-open Availability row. One transaction; --dry-run rolls
back. A report CSV lists old/new windows and flags.

See docs/superpowers/specs/2026-09-15-attendance-availability-backfill-design.md
"""
import argparse
import csv
import datetime
import os
import re
import shutil
import sys
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monthly_schedule.attendance_envelope import (  # noqa: E402
    DEFAULT_MIN_SAMPLES,
    collect_samples,
    estimate_windows,
    hhmm,
    normalize_time,
    parse_sheet_filename,
    window_flags,
)

DEFAULT_SHEETS_ROOT = r"\\Dell-NJ02\Desktop\Backup TP System\data"

# Rows 3..33 of the Attendance sheet: A=day number, B=weekday, C=Time-In,
# D=Time-Out. Row 2 is the header.
_FIRST_DATA_ROW = 3
_LAST_DATA_ROW = 33

_DAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri",
              6: "Sat", 7: "Sun"}


# ---------------------------------------------------------------------------
# months
# ---------------------------------------------------------------------------

def _default_months(today):
    """The three 'YYYY-MM' months ending with `today`'s month."""
    year, month = today.year, today.month
    out = []
    for _ in range(3):
        out.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return list(reversed(out))


def _parse_months(text):
    months = [m.strip() for m in text.split(",") if m.strip()]
    for m in months:
        if not re.fullmatch(r"\d{4}-\d{2}", m):
            raise ValueError(f"bad month {m!r}; expected YYYY-MM")
    return months


def _today():
    """Wrapped so tests can pin the date."""
    return datetime.date.today()


# ---------------------------------------------------------------------------
# sheets
# ---------------------------------------------------------------------------

def read_month_sheets(root, month, on_error):
    """Yield (center_id, iso_weekday, in_min, out_min) for every dated row
    of every Attendance sheet under <root>/<YYYY>/<MM>/Attendance/.

    Rows with no visit (blank times) are yielded with None so the caller's
    collect_samples can skip them. Unreadable workbooks and a missing
    month folder are reported through on_error(str) and skipped.
    """
    import openpyxl

    year_s, mon_s = month.split("-")
    folder = Path(root) / year_s / mon_s / "Attendance"
    if not folder.is_dir():
        on_error(f"month folder not found for {month}: {folder}")
        return
    year, mon = int(year_s), int(mon_s)
    for path in sorted(folder.iterdir()):
        parsed = parse_sheet_filename(path.name)
        if parsed is None:
            continue
        center_id, _name, _month = parsed
        try:
            wb = openpyxl.load_workbook(
                path, read_only=True, data_only=True, keep_vba=False)
        except Exception as exc:  # openpyxl raises many types
            on_error(f"could not open {path.name}: {exc}")
            continue
        try:
            ws = wb["Attendance"] if "Attendance" in wb.sheetnames \
                else wb.worksheets[-1]
            for row in ws.iter_rows(min_row=_FIRST_DATA_ROW,
                                    max_row=_LAST_DATA_ROW, max_col=4,
                                    values_only=True):
                day_no, _dow, time_in, time_out = row
                if not isinstance(day_no, (int, float)):
                    continue
                try:
                    date = datetime.date(year, mon, int(day_no))
                except ValueError:
                    continue   # 29..31 on a shorter month
                yield (center_id, date.isoweekday(),
                       normalize_time(time_in), normalize_time(time_out))
        finally:
            wb.close()


# ---------------------------------------------------------------------------
# args
# ---------------------------------------------------------------------------

def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Estimate Availability windows from Attendance sheets.",
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--sheets-root", default=DEFAULT_SHEETS_ROOT,
                   help="Folder holding <YYYY>/<MM>/Attendance/ "
                        f"(default {DEFAULT_SHEETS_ROOT}).")
    p.add_argument("--months", default=None,
                   help="Comma-separated YYYY-MM list. Default: the three "
                        "months ending this month.")
    p.add_argument("--csv-out", default=None,
                   help="Directory for the report CSV. "
                        "Default: the DB's directory.")
    p.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES,
                   help="Weekdays with fewer samples widen to the "
                        f"member-wide envelope (default {DEFAULT_MIN_SAMPLES}).")
    p.add_argument("--dry-run", action="store_true",
                   help="Report only; roll back DB writes; no backup copy.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-member stdout; print only the summary.")
    return p.parse_args(argv)


def main(argv=None):  # filled in by Task 8
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests\test_backfill_availability_from_attendance.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_availability_from_attendance.py tests/test_backfill_availability_from_attendance.py
git commit -m "feat(attendance): CLI args, month defaults and sheet reader"
```

---

### Task 7: DB helpers and upsert (fake cursor)

**Files:**
- Modify: `scripts/backfill_availability_from_attendance.py`
- Modify: `tests/test_backfill_availability_from_attendance.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
# ---------------------------------------------------------------------------
# fake DB
# ---------------------------------------------------------------------------

class _FakeCursor:
    """Answers the queries the script issues.

    members: list of (cid_float, last, first, plan, hha) for active members.
    operating_days: list of (dow_int, closing_dt).
    open_rows: {(cid_str, day_int): (row_id, start_dt, end_dt)}
    """

    def __init__(self, members, open_rows, operating_days=None):
        self._members = members
        self._open_rows = open_rows
        self._operating_days = operating_days if operating_days is not None \
            else [(d, _t(14, 0)) for d in range(1, 8)]
        self.executed = []
        self.updates = []    # (start_time, end_time, notes, row_id)
        self.inserts = []    # (cid, eff_start, day, start_time, end_time, notes)
        self._pending_all = []
        self._pending = None
        self._next_row_id = 9000

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        if "FROM [Contacts]" in sql:
            self._pending_all = list(self._members)
        elif "FROM [OperatingDays]" in sql:
            self._pending_all = list(self._operating_days)
        elif sql.startswith("SELECT") and "FROM [Availability]" in sql:
            self._pending = self._open_rows.get((params[0], params[1]))
        elif sql.startswith("UPDATE [Availability]"):
            self.updates.append(params)
            start_t, end_t, notes, row_id = params
            for key, (rid, _s, _e) in self._open_rows.items():
                if rid == row_id:
                    self._open_rows[key] = (rid, start_t, end_t)
                    break
        elif sql.startswith("INSERT INTO [Availability]"):
            self.inserts.append(params)
            cid, _eff, day, start_t, end_t, _notes = params
            self._open_rows[(cid, day)] = (self._next_row_id, start_t, end_t)
            self._next_row_id += 1
        else:  # pragma: no cover
            raise AssertionError(f"unexpected SQL: {sql}")
        return self

    def fetchone(self):
        return self._pending

    def fetchall(self):
        rows, self._pending_all = self._pending_all, []
        return rows


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def test_fetch_active_members_normalizes_ids_and_blanks():
    cur = _FakeCursor(
        members=[(1001.0, "Zhang", "Mingli", "VCM", None),
                 (25.0, "Lin", "Bo Hua", None, "BetterChoice 7AM-11AM")],
        open_rows={})
    assert mod._fetch_active_members(cur) == [
        {"center_id": 1001, "last_name": "Zhang", "first_name": "Mingli",
         "health_plan": "VCM", "hha": ""},
        {"center_id": 25, "last_name": "Lin", "first_name": "Bo Hua",
         "health_plan": "", "hha": "BetterChoice 7AM-11AM"},
    ]


def test_fetch_closing_times_defaults_missing_days_to_16():
    cur = _FakeCursor(members=[], open_rows={},
                      operating_days=[(1, _t(14, 0)), (2, _t(14, 30))])
    closing = mod._fetch_closing_times(cur)
    assert closing[1] == 14 * 60
    assert closing[2] == 14 * 60 + 30
    assert closing[7] == 16 * 60


def test_fetch_open_window_present_and_absent():
    cur = _FakeCursor(members=[], open_rows={
        ("1001", 1): (42, _t(8, 0), _t(13, 0))})
    assert mod._fetch_open_window(cur, 1001, 1) == (42, (8 * 60, 13 * 60))
    assert mod._fetch_open_window(cur, 1001, 2) is None


def test_upsert_updates_existing_row_with_notes():
    cur = _FakeCursor(members=[], open_rows={
        ("1001", 1): (42, _t(8, 0), _t(13, 0))})
    old = mod._upsert_window(cur, 1001, 1, 8 * 60 + 20, 12 * 60 + 25,
                             "Attendance envelope 2026-07..09, n=13",
                             datetime.date(2026, 9, 15))
    assert old == (8 * 60, 13 * 60)
    assert cur.updates == [(datetime.time(8, 20), datetime.time(12, 25),
                            "Attendance envelope 2026-07..09, n=13", 42)]
    assert cur.inserts == []


def test_upsert_inserts_when_no_open_row():
    cur = _FakeCursor(members=[], open_rows={})
    old = mod._upsert_window(cur, 1001, 3, 8 * 60 + 20, 12 * 60 + 25, "note",
                             datetime.date(2026, 9, 15))
    assert old is None
    assert cur.inserts == [("1001", datetime.date(2026, 9, 15), 3,
                            datetime.time(8, 20), datetime.time(12, 25), "note")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests\test_backfill_availability_from_attendance.py -v -k "fetch or upsert"`
Expected: FAIL — `AttributeError: module ... has no attribute '_fetch_active_members'`

- [ ] **Step 3: Write the minimal implementation** (insert after the `# args` section, before `main`)

```python
# ---------------------------------------------------------------------------
# database
# ---------------------------------------------------------------------------

_ACTIVE_MEMBERS_QUERY = (
    "SELECT c.[Center ID], c.[Last Name], c.[First Name], "
    "c.[Health Plan], c.[HHA] "
    "FROM [Contacts] c "
    "WHERE c.[Center ID] IN "
    "(SELECT e.[Center ID] FROM [Enrollment] e WHERE e.[end_date] IS NULL) "
    "ORDER BY c.[Center ID]"
)
_OPERATING_DAYS_QUERY = (
    "SELECT [Day Of Week], [closing_time] FROM [OperatingDays] ORDER BY [ID]"
)
_AVAIL_OPEN_QUERY = (
    "SELECT [ID], [avail_start], [avail_end] FROM [Availability] "
    "WHERE [Center ID] = ? AND [Day Of Week] = ? "
    "AND [effective_end_date] IS NULL"
)
_AVAIL_UPDATE = (
    "UPDATE [Availability] SET [avail_start] = ?, [avail_end] = ?, "
    "[Notes] = ? WHERE [ID] = ?"
)
_AVAIL_INSERT = (
    "INSERT INTO [Availability] "
    "([Center ID], [effective_start_date], [effective_end_date], "
    "[Day Of Week], [avail_start], [avail_end], [Notes]) "
    "VALUES (?, ?, NULL, ?, ?, ?, ?)"
)

_FALLBACK_CLOSING_MIN = 16 * 60   # rules.py latest_time_out when no row


def _minutes_to_time(minutes):
    return datetime.time(minutes // 60, minutes % 60)


def _time_to_minutes(value):
    """Access stores time-of-day as DATETIME with a 1899-12-30 date part;
    pyodbc returns datetime.datetime. Accept datetime.time too."""
    t = value.time() if hasattr(value, "time") else value
    return t.hour * 60 + t.minute


def _fetch_active_members(cur):
    """Active = has an Enrollment row with end_date IS NULL."""
    cur.execute(_ACTIVE_MEMBERS_QUERY)
    members = []
    for cid, last, first, plan, hha in cur.fetchall():
        if cid is None:
            continue
        members.append({
            "center_id": int(cid),
            "last_name": (last or "").strip(),
            "first_name": (first or "").strip(),
            "health_plan": (plan or "").strip(),
            "hha": (hha or "").strip(),
        })
    return members


def _fetch_closing_times(cur):
    """{iso_weekday: closing minutes}; the largest ID wins per weekday
    (matches CenterCalendar); weekdays without a row fall back to 16:00."""
    closing = {d: _FALLBACK_CLOSING_MIN for d in range(1, 8)}
    cur.execute(_OPERATING_DAYS_QUERY)
    for dow, closing_time in cur.fetchall():
        if dow is None or closing_time is None:
            continue
        closing[int(dow)] = _time_to_minutes(closing_time)
    return closing


def _fetch_open_window(cur, center_id, day):
    """(row_id, (start_min, end_min)) for the open row, or None."""
    cur.execute(_AVAIL_OPEN_QUERY, str(center_id), day)
    row = cur.fetchone()
    if row is None:
        return None
    row_id, start, end = row
    return int(row_id), (_time_to_minutes(start), _time_to_minutes(end))


def _upsert_window(cur, center_id, day, start_min, end_min, notes, today):
    """Write the window to the open row (UPDATE) or a new row (INSERT).
    Returns the previous (start_min, end_min) or None if there was no row."""
    found = _fetch_open_window(cur, center_id, day)
    start_t, end_t = _minutes_to_time(start_min), _minutes_to_time(end_min)
    if found is None:
        cur.execute(_AVAIL_INSERT, str(center_id), today, day,
                    start_t, end_t, notes)
        return None
    row_id, old = found
    cur.execute(_AVAIL_UPDATE, start_t, end_t, notes, row_id)
    return old


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests\test_backfill_availability_from_attendance.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_availability_from_attendance.py tests/test_backfill_availability_from_attendance.py
git commit -m "feat(attendance): DB reads and Availability upsert"
```

---

### Task 8: `main` — orchestration, backup, report, summary

**Files:**
- Modify: `scripts/backfill_availability_from_attendance.py`
- Modify: `tests/test_backfill_availability_from_attendance.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
# ---------------------------------------------------------------------------
# main — end to end with fake DB + temp sheets
# ---------------------------------------------------------------------------

def _month_days(lo_in, lo_out):
    """Days 1..28 filled with (in, out) datetime.time pairs in 12-hour form.
    The drift is i % 13 minutes, so the envelope is lo..lo+12 and every
    weekday gets 4 samples per month (8 over two months, above min_samples)."""
    out = {}
    for i in range(28):
        drift = datetime.timedelta(minutes=i % 13)
        ti = (datetime.datetime(2000, 1, 1, *lo_in) + drift).time()
        to = (datetime.datetime(2000, 1, 1, *lo_out) + drift).time()
        out[i + 1] = (ti, to)
    return out


def _sheets(tmp_path):
    """Two months of sheets for member 1001 (morning) and 1500 (afternoon);
    member 777 has no sheets."""
    for month in ("2026-08", "2026-09"):
        att = tmp_path / month[:4] / month[5:] / "Attendance"
        _write_attendance_sheet(att, 1001, "Zhang, Mingli", month,
                                _month_days((8, 21), (12, 23)))
        # afternoon: 12:32 in, 04:50 (= 16:50) out
        _write_attendance_sheet(att, 1500, "Yuan, XiaoFen", month,
                                _month_days((12, 32), (4, 50)))
    return tmp_path


def _run(tmp_path, monkeypatch, extra_args=(), members=None, open_rows=None):
    db = tmp_path / "test.accdb"
    db.write_bytes(b"fake")
    members = members if members is not None else [
        (1001.0, "Zhang", "Mingli", "VCM", ""),
        (1500.0, "Yuan", "XiaoFen", "EMPIRE-BCBS", "ABI 1-7 8am-12pm"),
        (777.0, "New", "Member", "HF", None),
    ]
    open_rows = open_rows if open_rows is not None else {
        (str(cid), d): (cid * 10 + d, _t(8, 0), _t(13, 0))
        for cid in (1001, 1500, 777) for d in range(1, 8)
    }
    cursor = _FakeCursor(members=members, open_rows=open_rows)
    conn = _FakeConn(cursor)
    monkeypatch.setattr("pyodbc.connect", lambda cs: conn)
    monkeypatch.setattr(mod, "_today", lambda: datetime.date(2026, 9, 15))
    rc = mod.main([
        "--db", str(db), "--sheets-root", str(_sheets(tmp_path)),
        "--months", "2026-08,2026-09", "--quiet", *extra_args,
    ])
    return rc, cursor, conn, db


def _report_rows(db):
    path = db.parent / "attendance_availability_2026-09-15.csv"
    with open(path, newline="", encoding="utf-8-sig") as f:
        import csv
        return list(csv.DictReader(f))


def test_main_writes_all_seven_weekdays_for_covered_members(tmp_path, monkeypatch):
    rc, cursor, conn, db = _run(tmp_path, monkeypatch)
    assert rc == 0
    assert conn.committed and not conn.rolled_back
    # 2 covered members x 7 weekdays, member 777 untouched
    assert len(cursor.updates) == 14
    assert cursor.inserts == []
    updated_ids = {u[3] for u in cursor.updates}
    assert all(rid // 10 in (1001, 1500) for rid in updated_ids)


def test_main_envelope_values_and_notes(tmp_path, monkeypatch):
    _, cursor, _, _ = _run(tmp_path, monkeypatch)
    by_row = {u[3]: u for u in cursor.updates}
    # 1001 Monday, 8 samples over Aug+Sep with drift 0..12 min:
    # 08:21..08:33 -> 08:20; 12:23..12:35 -> 12:35
    start, end, notes, _ = by_row[1001 * 10 + 1]
    assert (start, end) == (datetime.time(8, 20), datetime.time(12, 35))
    assert notes.startswith("Attendance envelope 2026-08..09, n=")
    # 1500 afternoon, 12:32 -> 12:30 ; 16:50+12 = 17:02 -> 17:05
    start, end, _, _ = by_row[1500 * 10 + 1]
    assert (start, end) == (datetime.time(12, 30), datetime.time(17, 5))


def test_main_report_rows_and_flags(tmp_path, monkeypatch):
    _, _, _, db = _run(tmp_path, monkeypatch)
    rows = _report_rows(db)
    assert len(rows) == 14 + 1        # 7 per covered member + one no_data row
    r1001 = [r for r in rows if r["center_id"] == "1001" and r["day"] == "1"][0]
    assert r1001["old_window"] == "08:00-13:00"
    assert r1001["new_window"] == "08:20-12:35"
    assert r1001["flags"] == ""
    r1500 = [r for r in rows if r["center_id"] == "1500" and r["day"] == "1"][0]
    assert r1500["flags"] == "past_close;afternoon_only"
    assert r1500["hha"] == "ABI 1-7 8am-12pm"
    r777 = [r for r in rows if r["center_id"] == "777"][0]
    assert r777["flags"] == "no_data" and r777["day"] == "" and r777["new_window"] == ""


def test_main_flags_hand_edit_replaced(tmp_path, monkeypatch):
    open_rows = {(str(cid), d): (cid * 10 + d, _t(8, 0), _t(13, 0))
                 for cid in (1001, 1500, 777) for d in range(1, 8)}
    open_rows[("1001", 2)] = (10012, _t(8, 0), _t(14, 0))   # hand edit
    _, _, _, db = _run(tmp_path, monkeypatch, open_rows=open_rows)
    r = [r for r in _report_rows(db) if r["center_id"] == "1001" and r["day"] == "2"][0]
    assert r["old_window"] == "08:00-14:00"
    assert "hand_edit_replaced" in r["flags"].split(";")


def test_main_inserts_when_member_has_no_open_rows(tmp_path, monkeypatch):
    _, cursor, _, _ = _run(tmp_path, monkeypatch, open_rows={})
    assert cursor.updates == []
    assert len(cursor.inserts) == 14
    assert cursor.inserts[0][1] == datetime.date(2026, 9, 15)


def test_main_dry_run_rolls_back_no_backup_but_reports(tmp_path, monkeypatch):
    rc, cursor, conn, db = _run(tmp_path, monkeypatch, extra_args=["--dry-run"])
    assert rc == 0
    assert conn.rolled_back and not conn.committed
    assert len(cursor.updates) == 14           # writes issued, then rolled back
    assert not list(tmp_path.glob("*.backup_*.accdb"))
    assert len(_report_rows(db)) == 15


def test_main_apply_takes_backup_copy(tmp_path, monkeypatch):
    _, _, _, db = _run(tmp_path, monkeypatch)
    backups = list(tmp_path.glob("test.backup_*.accdb"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"fake"


def test_main_missing_db_returns_2(tmp_path, capsys):
    rc = mod.main(["--db", str(tmp_path / "nope.accdb"),
                   "--sheets-root", str(tmp_path)])
    assert rc == 2
    assert "database not found" in capsys.readouterr().err


def test_main_bad_months_returns_2(tmp_path, capsys):
    db = tmp_path / "x.accdb"
    db.write_bytes(b"")
    rc = mod.main(["--db", str(db), "--months", "August"])
    assert rc == 2
    assert "YYYY-MM" in capsys.readouterr().err


def test_main_summary_mentions_reserve_checkboxes(tmp_path, monkeypatch, capsys):
    _run(tmp_path, monkeypatch, extra_args=["--dry-run"])
    out = capsys.readouterr().out
    assert "Drop-off by availability end" in out
    assert "Pick-up by availability start" in out
    assert "DRY-RUN" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests\test_backfill_availability_from_attendance.py -v -k main`
Expected: FAIL — `NotImplementedError` from `main`

- [ ] **Step 3: Write the implementation** (replace the `main` stub; add the report/backup helpers above it)

```python
# ---------------------------------------------------------------------------
# report + backup
# ---------------------------------------------------------------------------

_REPORT_COLUMNS = [
    "center_id", "last_name", "first_name", "health_plan", "day",
    "old_window", "new_window", "samples", "flags", "hha",
]
_DEFAULT_WINDOW = (8 * 60, 13 * 60)   # the post-setup seeded default

_REMINDER = (
    "  Reminder: uncheck \"Drop-off by availability end\" and \"Pick-up by\n"
    "  availability start\" in the Monthly Schedule Generator settings\n"
    "  (Settings -> Scheduling Rules) before the next run. These windows\n"
    "  describe Time-In..Time-Out; pick-up and drop-off fall around them."
)


def _window_str(window):
    if window is None:
        return ""
    return f"{hhmm(window[0])}-{hhmm(window[1])}"


def _months_label(months):
    """['2026-07','2026-08','2026-09'] -> '2026-07..09';
    a single month -> '2026-07'; mixed years -> '2025-11..2026-01'."""
    if len(months) == 1:
        return months[0]
    first, last = months[0], months[-1]
    if first[:4] == last[:4]:
        return f"{first}..{last[5:]}"
    return f"{first}..{last}"


def _note_for(est, label, member_samples):
    if "member_wide" in est.flags:
        return (f"member-wide envelope (no {_DAY_NAMES[est_day(est)]} data) "
                f"{label}, n={member_samples}")
    if "low_samples" in est.flags:
        return (f"Attendance envelope widened to member-wide "
                f"(n={est.samples}) {label}, member n={member_samples}")
    return f"Attendance envelope {label}, n={est.samples}"


def _write_report(rows, out_dir, today):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir, f"attendance_availability_{today.isoformat()}.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_REPORT_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path


def _backup_db(db_path):
    """Copy <name>.accdb -> <name>.backup_<YYYY-MM-DD-HHMMSS>.accdb next to
    it. Returns the copy's path. Raises OSError on failure."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    base, _ext = os.path.splitext(db_path)
    target = f"{base}.backup_{stamp}.accdb"
    shutil.copy2(db_path, target)
    return target
```

The `_note_for` helper above references a day; simplify by passing the weekday explicitly. Use this final version instead (delete the `est_day` reference):

```python
def _note_for(day, est, label, member_samples):
    if "member_wide" in est.flags:
        return (f"member-wide envelope (no {_DAY_NAMES[day]} data) "
                f"{label}, n={member_samples}")
    if "low_samples" in est.flags:
        return (f"Attendance envelope widened to member-wide "
                f"(n={est.samples}) {label}, member n={member_samples}")
    return f"Attendance envelope {label}, n={est.samples}"
```

```python
# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    args = _parse_args(argv)
    if not os.path.exists(args.db):
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)
        return 2
    try:
        months = (_parse_months(args.months) if args.months
                  else _default_months(_today()))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # 1. Sheets -> samples (before touching the DB, so a bad share path
    #    fails fast and never leaves a backup copy behind).
    sheet_errors = []
    all_rows = []
    sheets_read = 0
    for month in months:
        seen_ids = set()

        def _on_error(msg, _month=month):
            sheet_errors.append(f"{_month}: {msg}")

        for row in read_month_sheets(args.sheets_root, month, _on_error):
            seen_ids.add(row[0])
            all_rows.append(row)
        sheets_read += len(seen_ids)
    samples, dropped = collect_samples(all_rows)
    rows_with_times = sum(len(v) for v in samples.values())
    if not samples:
        print("ERROR: no Attendance samples found under "
              f"{args.sheets_root} for {', '.join(months)}", file=sys.stderr)
        for err in sheet_errors:
            print(f"  {err}", file=sys.stderr)
        return 2

    # 2. Backup (skipped on dry run).
    backup_path = None
    if not args.dry_run:
        try:
            backup_path = _backup_db(args.db)
        except OSError as exc:
            print(f"ERROR: could not back up the database: {exc}",
                  file=sys.stderr)
            return 2

    # 3. DB.
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

    label = _months_label(months)
    try:
        cur = conn.cursor()
        today = _today()
        members = _fetch_active_members(cur)
        closing = _fetch_closing_times(cur)

        stats = {
            "members": len(members), "written": 0, "no_data": 0,
            "updated": 0, "inserted": 0,
        }
        flag_counts = {k: 0 for k in (
            "past_close", "afternoon_only", "low_samples", "member_wide",
            "hand_edit_replaced", "narrow")}
        report = []

        for m in members:
            cid = m["center_id"]
            by_weekday = {d: samples.get((cid, d), []) for d in range(1, 8)}
            member_samples = sum(len(v) for v in by_weekday.values())
            estimates = estimate_windows(by_weekday, args.min_samples)
            base = {
                "center_id": cid, "last_name": m["last_name"],
                "first_name": m["first_name"],
                "health_plan": m["health_plan"], "hha": m["hha"],
            }
            if not estimates:
                stats["no_data"] += 1
                report.append({**base, "day": "", "old_window": "",
                               "new_window": "", "samples": 0,
                               "flags": "no_data"})
                continue

            stats["written"] += 1
            for day in range(1, 8):
                est = estimates[day]
                note = _note_for(day, est, label, member_samples)
                old = _upsert_window(cur, cid, day, est.start, est.end,
                                     note, today)
                if old is None:
                    stats["inserted"] += 1
                else:
                    stats["updated"] += 1
                flags = list(est.flags)
                flags += window_flags(est.start, est.end, closing[day])
                if old is not None and old != _DEFAULT_WINDOW:
                    flags.append("hand_edit_replaced")
                for fl in flags:
                    flag_counts[fl] += 1
                report.append({
                    **base, "day": day,
                    "old_window": _window_str(old),
                    "new_window": _window_str((est.start, est.end)),
                    "samples": est.samples, "flags": ";".join(flags),
                })
                if not args.quiet:
                    print(f"  {cid} {_DAY_NAMES[day]}: "
                          f"{_window_str(old) or '(none)'} -> "
                          f"{_window_str((est.start, est.end))}"
                          f"  [{';'.join(flags)}]")

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        out_dir = args.csv_out or os.path.dirname(os.path.abspath(args.db))
        csv_path = _write_report(report, out_dir, today)

        print()
        print("Attendance availability backfill summary")
        print(f"  Months scanned:                {', '.join(months)}")
        print(f"  Sheets read / errors:          {sheets_read} / {len(sheet_errors)}")
        for err in sheet_errors:
            print(f"    {err}")
        print(f"  Dated rows with times:         {rows_with_times}   (dropped: {dropped})")
        print(f"  Active members:                {stats['members']}")
        print(f"    with estimates written:      {stats['written']}")
        print(f"    no attendance data:          {stats['no_data']}")
        print(f"  Availability rows updated:     {stats['updated']}")
        print(f"  Availability rows inserted:    {stats['inserted']}")
        print("  Weekday rows flagged:          "
              + "  ".join(f"{k}={v}" for k, v in flag_counts.items()))
        print(f"  Report CSV: {csv_path}")
        print(f"  Backup:     {backup_path or 'none - dry run'}")
        print(f"  Mode: {mode}")
        print()
        print(_REMINDER)
    finally:
        conn.close()
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests\test_backfill_availability_from_attendance.py tests\test_attendance_envelope.py -v`
Expected: all PASS

If `test_main_envelope_values_and_notes` fails on the exact end minute, check the `_thirteen` helper: 13 samples per month × 2 months with a 1-minute drift give 12:23..12:35 → rounds up to 12:35. Fix the test data rather than the rounding.

- [ ] **Step 5: Run the whole suite to make sure nothing else broke**

Run: `.venv\Scripts\pytest -q`
Expected: all PASS (existing tests untouched)

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill_availability_from_attendance.py tests/test_backfill_availability_from_attendance.py
git commit -m "feat(attendance): backfill Availability from Attendance sheets"
```

---

### Task 9: Documentation

**Files:**
- Modify: `scripts/README.md` (the "What each script does" table)
- Modify: `README.md` (after the "Backfill Authorization from Contacts" section)

- [ ] **Step 1: Add the table row to `scripts/README.md`** (after the `backfill_availability_from_hha.py` row)

```markdown
| [`backfill_availability_from_attendance.py`](backfill_availability_from_attendance.py) | Estimates each active member's per-weekday `Availability` window from the Time-In / Time-Out values on the last three months of printed Attendance sheets (`\\Dell-NJ02\...\data\<YYYY>\<MM>\Attendance\`): earliest Time-In to latest Time-Out, rounded outward to 5 min. Overwrites the open row (hand edits included), stamps `Notes` with the provenance, and writes a report CSV flagging windows past the `OperatingDays` closing time, afternoon-only members, low-sample weekdays and members with no sheets. Takes a timestamped backup copy first. |
```

- [ ] **Step 2: Add a README section** (after "## Backfill Authorization from Contacts")

```markdown
## Backfill Availability from Attendance sheets

One-shot script that estimates each active member's availability
window from what was actually printed on the last three months of
Attendance sheets, and writes it to `Availability`. The HHA text is
too vague to derive hours from, but the printed Time-In / Time-Out
already avoided each member's home-care hours by hand, so their
envelope (earliest Time-In, latest Time-Out, per weekday) is a good
estimate of when the member can be at the center.

```
python scripts\backfill_availability_from_attendance.py --db <PATH> --dry-run
python scripts\backfill_availability_from_attendance.py --db <PATH>
```

Options: `--sheets-root DIR` (default the Dell-NJ02 share),
`--months 2026-07,2026-08,2026-09` (default: the three months ending
this month), `--csv-out DIR`, `--min-samples N` (weekdays with fewer
samples widen to the member-wide envelope; default 4), `--quiet`.

Every active member's seven open rows are overwritten, including
hand-edited ones; the old window is kept in the report
`<csv-out>/attendance_availability_<YYYY-MM-DD>.csv`. Members with no
sheets in the lookback are left untouched and listed as `no_data`.
`OperatingDays` is never changed: windows that run past the closing
time are written as-is and flagged `past_close` / `afternoon_only`.
A non-dry run first copies the `.accdb` to
`<name>.backup_<timestamp>.accdb`.

**The windows describe Time-In..Time-Out**, so the two rules
"Drop-off by availability end" and "Pick-up by availability start"
(Settings → Scheduling Rules) must be **unchecked** in the deployment
that uses them; with them on, the scheduler reserves travel time
inside the window on both ends and most days go blank. Design in
[`docs/superpowers/specs/2026-09-15-attendance-availability-backfill-design.md`](docs/superpowers/specs/2026-09-15-attendance-availability-backfill-design.md).
```

- [ ] **Step 3: Commit**

```bash
git add README.md scripts/README.md
git commit -m "docs: attendance availability backfill"
```

---

### Task 10: Acceptance — dry run, then apply against `dbm-09-15-2026.accdb`

**Files:** none (operational)

- [ ] **Step 1: Make sure the DB is not open in Access** (no `dbm-09-15-2026.laccdb` next to it)

```powershell
Test-Path "C:\Users\luald\OneDrive\Desktop\dbm-09-15-2026.laccdb"   # expect False
```

- [ ] **Step 2: Dry run**

```
.venv\Scripts\python.exe scripts\backfill_availability_from_attendance.py --db "C:\Users\luald\OneDrive\Desktop\dbm-09-15-2026.accdb" --months 2026-07,2026-08,2026-09 --dry-run --quiet
```

Expected summary (from the exploratory analysis; small drifts are fine, large ones are not):

```
  Sheets read / errors:          1283 / 0
  Dated rows with times:         18575   (dropped: 0)
  Active members:                448
    with estimates written:      434
    no attendance data:          14
  Availability rows updated:     3038
  Availability rows inserted:    0
  Mode: DRY-RUN (no changes committed)
```

`past_close` should be about 144 members' worth of rows and `afternoon_only` about 41 members' worth (times 7 weekdays each, minus weekdays whose estimate happens to end by 14:00). `hand_edit_replaced` should be about 232.

- [ ] **Step 3: Spot-check the report** against known members

```powershell
Import-Csv "C:\Users\luald\OneDrive\Desktop\attendance_availability_2026-09-15.csv" | Where-Object { $_.center_id -in 1001,1500,1768,25 } | Format-Table center_id,day,old_window,new_window,samples,flags
```

Expected: 1001 ≈ 08:15–12:35 all weekdays, no flags; 1500 Tue/Wed ≈ 09:20–14:15 with `past_close`; 1768 Mon–Wed ≈ 12:30–17:00 with `past_close;afternoon_only`; a member with `no_data` (e.g. 1776) has one row with an empty `day`.

- [ ] **Step 4: Confirm the DB is unchanged after the dry run**

```
.venv\Scripts\python.exe -c "import pyodbc;c=pyodbc.connect(r'DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=C:\Users\luald\OneDrive\Desktop\dbm-09-15-2026.accdb');print(c.execute('SELECT COUNT(*) FROM Availability WHERE Notes IS NOT NULL').fetchone())"
```

Expected: `(0, )`

- [ ] **Step 5: Apply**

```
.venv\Scripts\python.exe scripts\backfill_availability_from_attendance.py --db "C:\Users\luald\OneDrive\Desktop\dbm-09-15-2026.accdb" --months 2026-07,2026-08,2026-09 --quiet
```

Expected: same counts, `Mode: APPLIED`, a `Backup:` line naming `dbm-09-15-2026.backup_<stamp>.accdb`.

- [ ] **Step 6: Verify the write**

```
.venv\Scripts\python.exe -c "import pyodbc;c=pyodbc.connect(r'DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=C:\Users\luald\OneDrive\Desktop\dbm-09-15-2026.accdb');cur=c.cursor();print(cur.execute('SELECT COUNT(*) FROM Availability WHERE Notes IS NOT NULL').fetchone());print(cur.execute('SELECT [Day Of Week],avail_start,avail_end,Notes FROM Availability WHERE [Center ID]=1001 AND effective_end_date IS NULL ORDER BY [Day Of Week]').fetchall())"
```

Expected: `(3038, )` and seven rows for 1001 around 08:15–12:35 with `Attendance envelope 2026-07..09, n=…` notes.

- [ ] **Step 7: Hand the report and the reminder to the user.** Nothing to commit.

---

## Self-review

**Spec coverage.** §2 inputs → Task 6 (reader, months) and Task 7 (active members). §3.1–3.5 → Task 5 (+ Task 4 rounding). §3.6 no clipping → Task 8 writes raw and flags via `window_flags`. §4 reminder → Task 8 `_REMINDER` + README (Task 9). §5 writes, Notes, transaction, backup → Tasks 7–8. §6 report columns and flag vocabulary → Task 8 (`_REPORT_COLUMNS`, `flag_counts`, `no_data`, `hand_edit_replaced`; `narrow` from Task 4). §7 CLI → Task 6 args, Task 8 summary and exit codes. §8 layout → matches. §9 tests → Tasks 1–8. §10 out of scope → nothing touches OperatingDays/OneOff/Absences.

**Placeholders.** None; every step has code. The one mid-step correction (`_note_for` signature) is resolved in place — use the four-argument version.

**Type consistency.** `estimate_windows(samples_by_weekday, min_samples)` returns `{int: Estimate}` (Task 5) and Task 8 indexes `estimates[day]`. `collect_samples` returns `(samples, dropped)` (Task 3) and Task 8 unpacks both. `_upsert_window` returns the old `(start, end)` tuple or `None` (Task 7) and Task 8 compares it to `_DEFAULT_WINDOW`. `window_flags(start, end, closing_min)` (Task 4) is called with `closing[day]` (Task 8). Fake cursor UPDATE params are `(start_t, end_t, notes, row_id)` matching `_AVAIL_UPDATE`; INSERT params `(cid, eff, day, start_t, end_t, notes)` matching `_AVAIL_INSERT`.
