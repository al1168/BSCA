# Apply HHA Answers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the human-reviewed HHA answers CSV to the `Availability` table (narrowing windows so availability never overlaps home-care hours), via a CLI script and a standalone preview-then-apply PyQt6 GUI (`ApplyHHAAnswers.exe`).

**Architecture:** Three layers per the spec (`docs/superpowers/specs/2026-07-17-apply-hha-answers-design.md`): a pure parsing/subtraction module in `monthly_schedule/`, a transactional CLI script in `scripts/` with a review CSV for flagged rows, and a small GUI in `apply_hha_gui/` that calls the script's `main()` on a `QThread` — dry-run for Preview, timestamped-backup-then-run for Apply.

**Tech Stack:** Python 3.11, pyodbc (Access ODBC), PyQt6, pytest, PyInstaller. Venv: `.venv\Scripts\python`.

**Conventions to follow** (from existing code):
- Scripts expose `main(argv: list[str] | None = None) -> int`; `2` = environment error.
- Availability queries pass `str(center_id)`; time-of-day values are written as `datetime.time` and read back as `datetime.datetime` with a 1899-12-30 date part (compare via `.time()`).
- Only the open row per (Center ID, Day Of Week) — `effective_end_date IS NULL` — is touched.
- CSVs are written `encoding="utf-8-sig", newline=""`.
- Run tests with: `.venv\Scripts\python -m pytest tests\<file> -v`

---

### Task 1: Answer parsing (`monthly_schedule/hha_answer_parser.py`, part 1)

**Files:**
- Create: `monthly_schedule/hha_answer_parser.py`
- Create: `tests/test_hha_answer_parser.py`

- [ ] **Step 1: Write the failing tests for time + answer parsing**

Create `tests/test_hha_answer_parser.py`:

```python
import pytest

from monthly_schedule.hha_answer_parser import (
    AnswerParseError,
    hhmm,
    parse_answer,
    parse_time,
    subtract_care_window,
)


# ---------------------------------------------------------------------------
# parse_time — minutes since midnight
# ---------------------------------------------------------------------------

def test_parse_time_basic_am_pm():
    assert parse_time("8 AM") == 8 * 60
    assert parse_time("1 PM") == 13 * 60
    assert parse_time("8:30 AM") == 8 * 60 + 30
    assert parse_time("5:30 PM") == 17 * 60 + 30


def test_parse_time_noon_and_midnight():
    assert parse_time("12 PM") == 12 * 60      # noon
    assert parse_time("12:30 PM") == 12 * 60 + 30
    assert parse_time("12 AM") == 0            # midnight


def test_parse_time_is_case_and_space_insensitive():
    assert parse_time("8am") == 8 * 60
    assert parse_time(" 7 pm ") == 19 * 60
    assert parse_time("9:15PM") == 21 * 60 + 15


@pytest.mark.parametrize("bad", ["8", "25 PM", "0 AM", "8:5 PM", "eight AM", ""])
def test_parse_time_rejects_unparseable(bad):
    with pytest.raises(AnswerParseError):
        parse_time(bad)


# ---------------------------------------------------------------------------
# parse_answer — full answer cells, real rows from the reviewed CSV
# ---------------------------------------------------------------------------

def test_parse_answer_single_group():
    groups = parse_answer("1.5.6.7 (1 PM - 7 PM)")
    assert groups == [
        {"days": {1, 5, 6, 7}, "start": 13 * 60, "end": 19 * 60},
    ]


def test_parse_answer_multi_group_pipe_separated():
    groups = parse_answer(
        "1.5 (8:30 AM - 5:30 PM) | 3.6 (12 PM - 5 PM) | 7 (12:30 PM - 2:30 PM)"
    )
    assert [g["days"] for g in groups] == [{1, 5}, {3, 6}, {7}]
    assert groups[0] == {"days": {1, 5}, "start": 510, "end": 1050}
    assert groups[2] == {"days": {7}, "start": 750, "end": 870}


def test_parse_answer_tolerates_hand_filled_spacing():
    """Spacing quirks taken verbatim from the operator's hand-filled rows."""
    assert parse_answer("1.5.6.7  (1 PM- 7 PM)")[0]["days"] == {1, 5, 6, 7}
    assert parse_answer("2.5 (1 PM-5 PM) | 6.7 (8AM-12PM)")[1] == {
        "days": {6, 7}, "start": 8 * 60, "end": 12 * 60,
    }
    # Missing space before the pipe.
    groups = parse_answer("4 (8 AM - 2 PM)| 6.7 (8 AM - 1 PM)")
    assert [g["days"] for g in groups] == [{4}, {6, 7}]


@pytest.mark.parametrize("bad", [
    "",                        # blank (callers skip blanks; parsing one is an error)
    "gibberish",
    "1.8 (1 PM - 2 PM)",       # day out of 1-7
    "(1 PM - 2 PM)",           # no days
    "1 (3 PM - 1 PM)",         # start not before end
    "1 (3 PM - 3 PM)",         # zero-length
    "1 (1 PM 2 PM)",           # no dash
    "1 1 PM - 2 PM",           # no parentheses
])
def test_parse_answer_rejects_malformed(bad):
    with pytest.raises(AnswerParseError):
        parse_answer(bad)


# ---------------------------------------------------------------------------
# hhmm — display helper
# ---------------------------------------------------------------------------

def test_hhmm_formats_minutes():
    assert hhmm(8 * 60) == "08:00"
    assert hhmm(12 * 60 + 30) == "12:30"
    assert hhmm(0) == "00:00"
```

(`subtract_care_window` is imported now but only tested in Task 2 — the
import line stays stable across both tasks.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests\test_hha_answer_parser.py -v`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'monthly_schedule.hha_answer_parser'`

- [ ] **Step 3: Implement parsing (plus a `subtract_care_window` stub so the import works)**

Create `monthly_schedule/hha_answer_parser.py`:

```python
"""Parse reviewed HHA answer strings and subtract home-care windows
from availability windows. Pure logic — no DB, no IO.

Answer grammar (spec §3): pipe-separated groups of `days (start - end)`,
days dot-separated ISO weekdays 1-7, times `H[:MM]` with AM/PM on each
side, whitespace flexible:

    1.5 (8:30 AM - 5:30 PM) | 3.6 (12 PM - 5 PM) | 7 (12:30 PM - 2:30 PM)

Times are minutes since midnight throughout this module.
"""
import re


class AnswerParseError(ValueError):
    """An answer string that cannot be safely interpreted. Callers flag
    the whole row for review rather than guessing."""


_GROUP_RE = re.compile(r"^\s*([0-9.]+?)\s*\(\s*([^)]+?)\s*\)\s*$")
_TIME_RE = re.compile(r"^(\d{1,2})(?::([0-5]\d))?\s*(am|pm)$", re.IGNORECASE)


def parse_time(text):
    """'8:30 AM' -> 510. Hour 1-12 with AM/PM required; 12 AM -> 0,
    12 PM -> 720 (noon)."""
    m = _TIME_RE.match(text.strip())
    if not m:
        raise AnswerParseError(f"unparseable time: {text!r}")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    if not 1 <= hour <= 12:
        raise AnswerParseError(f"hour out of range: {text!r}")
    if hour == 12:
        hour = 0
    if m.group(3).lower() == "pm":
        hour += 12
    return hour * 60 + minute


def parse_answer(text):
    """Parse one answer cell into a list of
    `{"days": set[int], "start": int, "end": int}` groups.
    Raises AnswerParseError on anything malformed — no guessing."""
    groups = []
    for part in text.split("|"):
        m = _GROUP_RE.match(part)
        if not m:
            raise AnswerParseError(f"unrecognized group: {part.strip()!r}")
        days_raw, time_raw = m.group(1), m.group(2)
        days = set()
        for tok in days_raw.split("."):
            tok = tok.strip()
            if not tok:
                continue
            if not tok.isdigit() or not 1 <= int(tok) <= 7:
                raise AnswerParseError(
                    f"bad day {tok!r} in group {part.strip()!r}")
            days.add(int(tok))
        if not days:
            raise AnswerParseError(f"no days in group {part.strip()!r}")
        sides = time_raw.split("-")
        if len(sides) != 2:
            raise AnswerParseError(
                f"bad time block in group {part.strip()!r}")
        start, end = parse_time(sides[0]), parse_time(sides[1])
        if start >= end:
            raise AnswerParseError(
                f"start not before end in group {part.strip()!r}")
        groups.append({"days": days, "start": start, "end": end})
    return groups


def subtract_care_window(avail, care):
    raise NotImplementedError  # Task 2
    

def hhmm(minutes):
    """510 -> '08:30'."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests\test_hha_answer_parser.py -v`
Expected: all PASS.

Note: `parse_answer("")` fails correctly because `"".split("|")` yields
`[""]`, which does not match `_GROUP_RE`.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/hha_answer_parser.py tests/test_hha_answer_parser.py
git commit -m "feat(monthly_schedule): parse reviewed HHA answer strings"
```

---

### Task 2: Interval subtraction (`monthly_schedule/hha_answer_parser.py`, part 2)

**Files:**
- Modify: `monthly_schedule/hha_answer_parser.py` (replace the `subtract_care_window` stub)
- Modify: `tests/test_hha_answer_parser.py` (append tests)

- [ ] **Step 1: Append the failing subtraction tests**

Append to `tests/test_hha_answer_parser.py`:

```python
# ---------------------------------------------------------------------------
# subtract_care_window — spec §4. Windows are (start_min, end_min) tuples;
# the typical open window post-setup is the seeded default 08:00-13:00.
# ---------------------------------------------------------------------------

DEFAULT = (8 * 60, 13 * 60)


def test_subtract_no_overlap_after_close():
    """5 PM - 9 PM care vs 08:00-13:00: no change."""
    result = subtract_care_window(DEFAULT, (17 * 60, 21 * 60))
    assert result == {"action": "none", "window": DEFAULT, "dropped": None}


def test_subtract_no_overlap_touching_edges():
    """Care ending exactly at open / starting exactly at close: no change."""
    assert subtract_care_window(DEFAULT, (6 * 60, 8 * 60))["action"] == "none"
    assert subtract_care_window(DEFAULT, (13 * 60, 15 * 60))["action"] == "none"


def test_subtract_front_overlap_pushes_start():
    """6 AM - 12 PM care: morning care pushes avail_start to 12:00."""
    result = subtract_care_window(DEFAULT, (6 * 60, 12 * 60))
    assert result == {
        "action": "narrow", "window": (12 * 60, 13 * 60), "dropped": None,
    }


def test_subtract_back_overlap_pulls_end():
    """12 PM - 4 PM care: avail_end pulled to 12:00 (the original rule)."""
    result = subtract_care_window(DEFAULT, (12 * 60, 16 * 60))
    assert result == {
        "action": "narrow", "window": (8 * 60, 12 * 60), "dropped": None,
    }


def test_subtract_strict_inside_keeps_longer_piece():
    """8:30 AM - 12 PM care leaves 08:00-08:30 and 12:00-13:00; the
    longer piece (12:00-13:00) is kept, the other reported as dropped."""
    result = subtract_care_window(DEFAULT, (510, 12 * 60))
    assert result == {
        "action": "split",
        "window": (12 * 60, 13 * 60),
        "dropped": (8 * 60, 510),
    }


def test_subtract_strict_inside_tie_keeps_morning():
    """Equal pieces (30 min each): keep the morning piece."""
    result = subtract_care_window(DEFAULT, (510, 750))
    assert result["action"] == "split"
    assert result["window"] == (8 * 60, 510)
    assert result["dropped"] == (750, 13 * 60)


def test_subtract_full_cover_is_blocked():
    """6:30 AM - 1:30 PM care swallows 08:00-13:00 entirely."""
    result = subtract_care_window(DEFAULT, (390, 810))
    assert result == {"action": "blocked", "window": None, "dropped": None}


def test_subtract_exact_cover_is_blocked():
    result = subtract_care_window(DEFAULT, DEFAULT)
    assert result["action"] == "blocked"


def test_subtract_is_idempotent():
    """Subtracting the same care window from the already-narrowed
    result is a no-op — re-running the tool is safe."""
    care = (12 * 60, 16 * 60)
    first = subtract_care_window(DEFAULT, care)
    second = subtract_care_window(first["window"], care)
    assert second == {
        "action": "none", "window": first["window"], "dropped": None,
    }
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests\test_hha_answer_parser.py -k subtract -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Replace the stub with the implementation**

In `monthly_schedule/hha_answer_parser.py`, replace the whole
`subtract_care_window` stub with:

```python
def subtract_care_window(avail, care):
    """Subtract the care interval from the availability interval
    (both `(start_min, end_min)` tuples). Returns

        {"action": "none" | "narrow" | "split" | "blocked",
         "window": (lo, hi) | None,    # the post-subtraction window
         "dropped": (lo, hi) | None}   # discarded piece (split only)

    Split rule (spec §4): when the care window sits strictly inside,
    keep the longer remaining piece; on a tie keep the morning piece.
    The result is always a subset of `avail` — this only ever narrows.
    """
    a, b = avail
    s, e = care
    if e <= a or s >= b:
        return {"action": "none", "window": (a, b), "dropped": None}
    if s <= a and e >= b:
        return {"action": "blocked", "window": None, "dropped": None}
    if s <= a:
        return {"action": "narrow", "window": (e, b), "dropped": None}
    if e >= b:
        return {"action": "narrow", "window": (a, s), "dropped": None}
    front, back = (a, s), (e, b)
    if (s - a) >= (b - e):
        keep, drop = front, back
    else:
        keep, drop = back, front
    return {"action": "split", "window": keep, "dropped": drop}
```

- [ ] **Step 4: Run the full module's tests**

Run: `.venv\Scripts\python -m pytest tests\test_hha_answer_parser.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/hha_answer_parser.py tests/test_hha_answer_parser.py
git commit -m "feat(monthly_schedule): subtract care windows from availability"
```

---

### Task 3: CLI script (`scripts/apply_hha_answers.py`)

**Files:**
- Create: `scripts/apply_hha_answers.py`
- Create: `tests/test_apply_hha_answers.py`

- [ ] **Step 1: Write the failing script-level tests**

Create `tests/test_apply_hha_answers.py`. The fake-connection pattern
mirrors `tests/test_backfill_availability.py`, extended so tests can
seed per-(member, day) open Availability rows and a set of known
Contacts IDs:

```python
import csv
import datetime
import sys
from pathlib import Path

import pytest

# Ensure the script is importable as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import apply_hha_answers as apply_mod


def _t(hour, minute=0):
    """Time-of-day as Access/pyodbc returns it: a datetime with the
    1899-12-30 placeholder date."""
    return datetime.datetime(1899, 12, 30, hour, minute)


class _FakeCursor:
    """Answers the three queries the script issues.

    contacts_ids: set[int] — Center IDs that exist in Contacts.
    open_rows: {(center_id_str, day_int): (row_id, start_dt, end_dt)}
    """

    def __init__(self, contacts_ids, open_rows):
        self._contacts_ids = contacts_ids
        self._open_rows = open_rows
        self.executed = []      # every (sql, params)
        self.updates = []       # (start_time, end_time, row_id)
        self.inserts = []       # (cid, eff_start, day, start_time, end_time)
        self._pending = None    # next fetchone() result

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        if "FROM [Contacts]" in sql:
            cid = params[0]
            self._pending = (cid,) if cid in self._contacts_ids else None
        elif sql.startswith("SELECT") and "FROM [Availability]" in sql:
            self._pending = self._open_rows.get((params[0], params[1]))
        elif sql.startswith("UPDATE [Availability]"):
            self.updates.append(params)
            self._pending = None
        elif sql.startswith("INSERT INTO [Availability]"):
            self.inserts.append(params)
            self._pending = None
        else:  # pragma: no cover - unexpected SQL is a test failure
            raise AssertionError(f"unexpected SQL: {sql}")
        return self

    def fetchone(self):
        return self._pending


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


_CSV_HEADER = [
    "center_id", "last_name", "first_name", "answer",
    "raw_hha", "reason", "attempted_parse",
]


def _write_answers_csv(path, rows):
    """rows: list of (center_id, last, first, answer)."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(_CSV_HEADER)
        for cid, last, first, answer in rows:
            w.writerow([cid, last, first, answer, "raw", "reason", "parse"])


def _run(tmp_path, monkeypatch, csv_rows, cursor, extra_argv=()):
    """Write the answers CSV, patch pyodbc.connect, run main()."""
    csv_path = tmp_path / "answers.csv"
    _write_answers_csv(csv_path, csv_rows)
    db_path = tmp_path / "members.accdb"
    db_path.touch()
    conn = _FakeConn(cursor)
    monkeypatch.setattr("pyodbc.connect", lambda cs: conn)
    rc = apply_mod.main(
        ["--csv", str(csv_path), "--db", str(db_path), *extra_argv]
    )
    return rc, conn


def _read_review_csv(tmp_path):
    matches = list(tmp_path.glob("hha_answers_review_*.csv"))
    assert len(matches) == 1, matches
    with open(matches[0], encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Environment errors
# ---------------------------------------------------------------------------

def test_missing_csv_returns_2(tmp_path, capsys):
    db = tmp_path / "m.accdb"
    db.touch()
    rc = apply_mod.main(
        ["--csv", str(tmp_path / "nope.csv"), "--db", str(db)]
    )
    assert rc == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_missing_db_returns_2(tmp_path, capsys):
    csv_path = tmp_path / "answers.csv"
    _write_answers_csv(csv_path, [])
    rc = apply_mod.main(
        ["--csv", str(csv_path), "--db", str(tmp_path / "nope.accdb")]
    )
    assert rc == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_csv_without_required_columns_returns_2(tmp_path, monkeypatch, capsys):
    csv_path = tmp_path / "answers.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerow(["something", "else"])
    db = tmp_path / "m.accdb"
    db.touch()
    monkeypatch.setattr(
        "pyodbc.connect", lambda cs: _FakeConn(_FakeCursor(set(), {}))
    )
    rc = apply_mod.main(["--csv", str(csv_path), "--db", str(db)])
    assert rc == 2
    assert "missing columns" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# Core behavior
# ---------------------------------------------------------------------------

def test_back_overlap_updates_open_row(tmp_path, monkeypatch, capsys):
    """25023 day 7 `12 PM - 4 PM` vs open 08:00-13:00 -> end 12:00."""
    cursor = _FakeCursor(
        contacts_ids={25023},
        open_rows={("25023", 7): (41, _t(8), _t(13))},
    )
    rc, conn = _run(
        tmp_path, monkeypatch,
        [("25023", "Lin", "Zi C", "7 (12 PM - 4 PM)")],
        cursor,
    )
    assert rc == 0
    assert conn.committed and not conn.rolled_back
    assert cursor.updates == [
        (datetime.time(8, 0), datetime.time(12, 0), 41),
    ]
    assert cursor.inserts == []
    out = capsys.readouterr().out
    assert "Days updated:" in out
    assert _read_review_csv(tmp_path) == []   # nothing flagged


def test_front_overlap_pushes_start(tmp_path, monkeypatch):
    """25035 `4.5 (6 AM - 12 PM)` -> start pushed to 12:00 on both days."""
    cursor = _FakeCursor(
        contacts_ids={25035},
        open_rows={
            ("25035", 4): (10, _t(8), _t(13)),
            ("25035", 5): (11, _t(8), _t(13)),
        },
    )
    rc, conn = _run(
        tmp_path, monkeypatch,
        [("25035", "Chen", "QiRui", "4.5 (6 AM - 12 PM)")],
        cursor,
    )
    assert rc == 0
    assert sorted(cursor.updates, key=lambda u: u[2]) == [
        (datetime.time(12, 0), datetime.time(13, 0), 10),
        (datetime.time(12, 0), datetime.time(13, 0), 11),
    ]


def test_no_overlap_writes_nothing(tmp_path, monkeypatch, capsys):
    """After-close care (5 PM - 9 PM) changes nothing, counted unchanged."""
    cursor = _FakeCursor(
        contacts_ids={2528900},
        open_rows={("2528900", d): (50 + d, _t(8), _t(13))
                   for d in (1, 5, 6, 7)},
    )
    rc, conn = _run(
        tmp_path, monkeypatch,
        [("2528900", "Tao", "YanEr", "1.5.6.7 (5 PM - 9 PM)")],
        cursor,
    )
    assert rc == 0
    assert cursor.updates == []
    assert cursor.inserts == []
    assert "Days unchanged (no overlap): 4" in capsys.readouterr().out


def test_split_keeps_longer_piece_and_flags(tmp_path, monkeypatch):
    """25249 `6.7 (8:30 AM - 12 PM)` vs 08:00-13:00 -> keep 12:00-13:00,
    flag `split` with the dropped piece in the note."""
    cursor = _FakeCursor(
        contacts_ids={25249},
        open_rows={
            ("25249", 6): (60, _t(8), _t(13)),
            ("25249", 7): (61, _t(8), _t(13)),
        },
    )
    rc, _ = _run(
        tmp_path, monkeypatch,
        [("25249", "Zheng", "Shui Guo", "6.7 (8:30 AM - 12 PM)")],
        cursor,
    )
    assert rc == 0
    assert sorted(cursor.updates, key=lambda u: u[2]) == [
        (datetime.time(12, 0), datetime.time(13, 0), 60),
        (datetime.time(12, 0), datetime.time(13, 0), 61),
    ]
    review = _read_review_csv(tmp_path)
    assert [r["flag"] for r in review] == ["split", "split"]
    assert review[0]["day"] == "6"
    assert review[0]["old_window"] == "08:00-13:00"
    assert review[0]["new_window"] == "12:00-13:00"
    assert "08:00-08:30" in review[0]["note"]


def test_blocked_day_not_written_but_flagged(tmp_path, monkeypatch):
    """Care 6:30 AM - 1:30 PM swallows 08:00-13:00: no write, flag."""
    cursor = _FakeCursor(
        contacts_ids={2509500},
        open_rows={("2509500", 4): (70, _t(8), _t(13))},
    )
    rc, _ = _run(
        tmp_path, monkeypatch,
        [("2509500", "Xie", "Gui Ying", "4 (6:30 AM - 1:30 PM)")],
        cursor,
    )
    assert rc == 0
    assert cursor.updates == []
    review = _read_review_csv(tmp_path)
    assert [r["flag"] for r in review] == ["blocked"]
    assert review[0]["new_window"] == ""
    assert review[0]["old_window"] == "08:00-13:00"


def test_no_open_row_inserts_against_default(tmp_path, monkeypatch):
    """No open Availability row: subtract against the 08:00-13:00
    default and INSERT the result with today's effective_start_date."""
    cursor = _FakeCursor(contacts_ids={25023}, open_rows={})
    rc, _ = _run(
        tmp_path, monkeypatch,
        [("25023", "Lin", "Zi C", "7 (12 PM - 4 PM)")],
        cursor,
    )
    assert rc == 0
    assert cursor.updates == []
    assert len(cursor.inserts) == 1
    cid, eff_start, day, start_t, end_t = cursor.inserts[0]
    assert cid == "25023"
    assert eff_start == datetime.date.today()
    assert day == 7
    assert (start_t, end_t) == (datetime.time(8, 0), datetime.time(12, 0))


def test_blank_answer_skipped_without_db_access(tmp_path, monkeypatch, capsys):
    cursor = _FakeCursor(contacts_ids=set(), open_rows={})
    rc, _ = _run(
        tmp_path, monkeypatch,
        [("24109", "Chen", "Wusong", "")],
        cursor,
    )
    assert rc == 0
    assert cursor.executed == []    # never touched the DB
    assert "Blank answers skipped: 1" in capsys.readouterr().out


def test_parse_error_flags_row_and_isolates_it(tmp_path, monkeypatch):
    """A malformed answer flags that row; the next row still applies."""
    cursor = _FakeCursor(
        contacts_ids={25023},
        open_rows={("25023", 7): (41, _t(8), _t(13))},
    )
    rc, _ = _run(
        tmp_path, monkeypatch,
        [
            ("99999", "Bad", "Row", "1 (3 PM - 1 PM)"),
            ("25023", "Lin", "Zi C", "7 (12 PM - 4 PM)"),
        ],
        cursor,
    )
    assert rc == 0
    assert len(cursor.updates) == 1
    review = _read_review_csv(tmp_path)
    assert [r["flag"] for r in review] == ["parse_error"]
    assert review[0]["center_id"] == "99999"
    assert review[0]["day"] == ""


def test_unknown_member_flagged(tmp_path, monkeypatch):
    cursor = _FakeCursor(contacts_ids=set(), open_rows={})
    rc, _ = _run(
        tmp_path, monkeypatch,
        [("11111", "Ghost", "Member", "1 (12 PM - 4 PM)")],
        cursor,
    )
    assert rc == 0
    assert cursor.updates == [] and cursor.inserts == []
    review = _read_review_csv(tmp_path)
    assert [r["flag"] for r in review] == ["member_not_found"]


def test_dry_run_rolls_back_but_writes_review_csv(
    tmp_path, monkeypatch, capsys,
):
    cursor = _FakeCursor(
        contacts_ids={25249},
        open_rows={("25249", 6): (60, _t(8), _t(13))},
    )
    rc, conn = _run(
        tmp_path, monkeypatch,
        [("25249", "Zheng", "Shui Guo", "6 (8:30 AM - 12 PM)")],
        cursor,
        extra_argv=["--dry-run"],
    )
    assert rc == 0
    assert conn.rolled_back and not conn.committed
    assert len(_read_review_csv(tmp_path)) == 1   # still written
    assert "DRY-RUN" in capsys.readouterr().out


def test_multi_group_same_day_subtracts_sequentially(tmp_path, monkeypatch):
    """Two groups hitting day 1 (morning 8-9 AM and afternoon 12-4 PM
    care) leave 09:00-12:00."""
    cursor = _FakeCursor(
        contacts_ids={25361},
        open_rows={("25361", 1): (80, _t(8), _t(13))},
    )
    rc, _ = _run(
        tmp_path, monkeypatch,
        [("25361", "Lin", "Zhu Ying", "1 (8 AM - 9 AM) | 1 (12 PM - 4 PM)")],
        cursor,
    )
    assert rc == 0
    assert cursor.updates == [
        (datetime.time(9, 0), datetime.time(12, 0), 80),
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests\test_apply_hha_answers.py -v`
Expected: FAIL at import — `ImportError: cannot import name 'apply_hha_answers'` (module doesn't exist yet).

- [ ] **Step 3: Implement the script**

Create `scripts/apply_hha_answers.py`:

```python
"""Apply reviewed HHA answers to the Availability table.

Reads the human-reviewed answers CSV (the `hhbackfill` file), parses
each non-empty `answer`, and narrows the currently-open Availability
window per (member, day) so availability never overlaps home-care
hours. Splits, fully-blocked days, parse errors and unknown members
go to a dated review CSV; all DB writes happen in one transaction.

See docs/superpowers/specs/2026-07-17-apply-hha-answers-design.md
"""
import argparse
import csv
import datetime
import os
import sys
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monthly_schedule.hha_answer_parser import (  # noqa: E402
    AnswerParseError,
    hhmm,
    parse_answer,
    subtract_care_window,
)

# The post-setup seeded default window; used when a (member, day) named
# in an answer has no open Availability row (spec §4).
_DEFAULT_WINDOW = (8 * 60, 13 * 60)

_AVAIL_OPEN_QUERY = (
    "SELECT [ID], [avail_start], [avail_end] FROM [Availability] "
    "WHERE [Center ID] = ? AND [Day Of Week] = ? "
    "AND [effective_end_date] IS NULL"
)
_AVAIL_UPDATE = (
    "UPDATE [Availability] SET [avail_start] = ?, [avail_end] = ? "
    "WHERE [ID] = ?"
)
_AVAIL_INSERT = (
    "INSERT INTO [Availability] "
    "([Center ID], [effective_start_date], [effective_end_date], "
    "[Day Of Week], [avail_start], [avail_end]) "
    "VALUES (?, ?, NULL, ?, ?, ?)"
)
_CONTACT_EXISTS_QUERY = (
    "SELECT [Center ID] FROM [Contacts] WHERE [Center ID] = ?"
)

_REVIEW_COLUMNS = [
    "center_id", "last_name", "first_name", "day", "flag",
    "hha_window", "old_window", "new_window", "note",
]


def _minutes_to_time(minutes):
    return datetime.time(minutes // 60, minutes % 60)


def _time_to_minutes(value):
    """Access stores time-of-day as DATETIME with a 1899-12-30 date
    part; pyodbc returns datetime.datetime. Accept datetime.time too."""
    t = value.time() if hasattr(value, "time") else value
    return t.hour * 60 + t.minute


def _window_str(window):
    return f"{hhmm(window[0])}-{hhmm(window[1])}"


def _read_answer_rows(csv_path):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = {"center_id", "answer"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"answers CSV missing columns: {sorted(missing)}")
        return list(reader)


def _member_exists(cur, center_id):
    cur.execute(_CONTACT_EXISTS_QUERY, int(center_id))
    return cur.fetchone() is not None


def _fetch_open_window(cur, center_id, day):
    """Return (row_id, (start_min, end_min)) for the open Availability
    row, or None if the member has no open row for that weekday."""
    cur.execute(_AVAIL_OPEN_QUERY, str(center_id), day)
    row = cur.fetchone()
    if row is None:
        return None
    row_id, start, end = row
    return int(row_id), (_time_to_minutes(start), _time_to_minutes(end))


def _write_review_csv(rows, out_dir, today):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir, f"hha_answers_review_{today.isoformat()}.csv",
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_REVIEW_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Apply reviewed HHA answers to Availability.",
    )
    p.add_argument("--csv", required=True,
                   help="Path to the reviewed answers CSV.")
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--csv-out", default=None,
                   help="Directory for the review CSV. "
                        "Default: the answers CSV's directory.")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse + report, roll back all DB changes.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-day stdout; print only the summary.")
    return p.parse_args(argv)


def _apply_member_day(cur, cid, day, intervals, today, args, stats,
                      review_rows, names):
    """Subtract every care interval for one (member, day) from its open
    window and write the result. Appends review rows for split/blocked."""
    last, first = names
    found = _fetch_open_window(cur, cid, day)
    if found is None:
        row_id, window = None, _DEFAULT_WINDOW
    else:
        row_id, window = found
    original = window
    hha_desc = "; ".join(_window_str(iv) for iv in intervals)

    blocked = False
    dropped = None
    for care in intervals:
        result = subtract_care_window(window, care)
        if result["action"] == "blocked":
            blocked = True
            break
        if result["action"] == "split":
            dropped = result["dropped"]
        window = result["window"]

    if blocked:
        stats["blocked_days"] += 1
        review_rows.append({
            "center_id": cid, "last_name": last, "first_name": first,
            "day": day, "flag": "blocked", "hha_window": hha_desc,
            "old_window": _window_str(original), "new_window": "",
            "note": "care covers the whole window; not written",
        })
        return

    if window == original:
        stats["days_unchanged"] += 1
        return

    if dropped is not None:
        stats["split_days"] += 1
        review_rows.append({
            "center_id": cid, "last_name": last, "first_name": first,
            "day": day, "flag": "split", "hha_window": hha_desc,
            "old_window": _window_str(original),
            "new_window": _window_str(window),
            "note": f"kept longer piece; dropped {_window_str(dropped)}",
        })

    if row_id is None:
        cur.execute(
            _AVAIL_INSERT, str(cid), today, day,
            _minutes_to_time(window[0]), _minutes_to_time(window[1]),
        )
        stats["days_inserted"] += 1
    else:
        cur.execute(
            _AVAIL_UPDATE,
            _minutes_to_time(window[0]), _minutes_to_time(window[1]),
            row_id,
        )
        stats["days_updated"] += 1

    if not args.quiet:
        print(
            f"  {cid} day {day}: {_window_str(original)} -> "
            f"{_window_str(window)}  (HHA {hha_desc})"
        )


def main(argv=None):
    args = _parse_args(argv)
    if not os.path.exists(args.csv):
        print(f"ERROR: answers CSV not found: {args.csv}", file=sys.stderr)
        return 2
    if not os.path.exists(args.db):
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)
        return 2

    try:
        answer_rows = _read_answer_rows(args.csv)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
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
        today = datetime.date.today()
        stats = {
            "rows": 0, "blank": 0, "members_applied": 0,
            "parse_errors": 0, "members_not_found": 0,
            "days_updated": 0, "days_inserted": 0, "days_unchanged": 0,
            "split_days": 0, "blocked_days": 0,
        }
        review_rows = []

        for row in answer_rows:
            stats["rows"] += 1
            cid_raw = (row.get("center_id") or "").strip()
            answer = (row.get("answer") or "").strip()
            last = (row.get("last_name") or "").strip()
            first = (row.get("first_name") or "").strip()

            if not answer:
                stats["blank"] += 1
                continue

            try:
                groups = parse_answer(answer)
                cid = int(cid_raw)
            except (AnswerParseError, ValueError) as exc:
                stats["parse_errors"] += 1
                review_rows.append({
                    "center_id": cid_raw, "last_name": last,
                    "first_name": first, "day": "",
                    "flag": "parse_error", "hha_window": "",
                    "old_window": "", "new_window": "",
                    "note": str(exc),
                })
                continue

            if not _member_exists(cur, cid):
                stats["members_not_found"] += 1
                review_rows.append({
                    "center_id": cid, "last_name": last,
                    "first_name": first, "day": "",
                    "flag": "member_not_found", "hha_window": "",
                    "old_window": "", "new_window": "",
                    "note": "Center ID not in Contacts; nothing written",
                })
                continue

            stats["members_applied"] += 1
            day_intervals = {}
            for g in groups:
                for d in sorted(g["days"]):
                    day_intervals.setdefault(d, []).append(
                        (g["start"], g["end"]))
            for d, intervals in sorted(day_intervals.items()):
                _apply_member_day(
                    cur, cid, d, intervals, today, args, stats,
                    review_rows, (last, first),
                )

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        out_dir = args.csv_out or os.path.dirname(
            os.path.abspath(args.csv))
        csv_path = _write_review_csv(review_rows, out_dir, today)

        print()
        print("Apply HHA answers summary")
        print(f"  Rows read:                   {stats['rows']}")
        print(f"  Blank answers skipped: {stats['blank']}")
        print(f"  Members applied:             {stats['members_applied']}")
        print(f"  Parse errors:                {stats['parse_errors']}")
        print(f"  Members not found:           {stats['members_not_found']}")
        print(f"  Days updated: {stats['days_updated']}")
        print(f"  Days inserted:               {stats['days_inserted']}")
        print(f"  Days unchanged (no overlap): {stats['days_unchanged']}")
        print(f"  Split days (kept longer piece): {stats['split_days']}")
        print(f"  Blocked days (not written):  {stats['blocked_days']}")
        print(f"  Review CSV: {csv_path}")
        print(f"  Mode: {mode}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests\test_apply_hha_answers.py -v`
Expected: all PASS. Also run the whole suite to catch regressions:
`.venv\Scripts\python -m pytest tests -q` — expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/apply_hha_answers.py tests/test_apply_hha_answers.py
git commit -m "feat(scripts): apply reviewed HHA answers to Availability"
```

---

### Task 4: GUI worker (`apply_hha_gui/worker.py`)

**Files:**
- Create: `apply_hha_gui/__init__.py` (empty)
- Create: `apply_hha_gui/worker.py`
- Create: `tests/test_apply_hha_worker.py`

- [ ] **Step 1: Write the failing worker tests**

Create `tests/test_apply_hha_worker.py` (harness mirrors
`tests/test_setup_worker.py`):

```python
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer


# A QCoreApplication must exist for QThread signal dispatch.
@pytest.fixture(scope="module", autouse=True)
def _qapp():
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    yield app


from apply_hha_gui.worker import ApplyHhaWorker


def _run_to_completion(worker, timeout_ms=5000):
    """Spin a QEventLoop until `worker` emits `finished_run`."""
    loop = QEventLoop()
    captured = []

    def on_finished(success, payload):
        captured.append((success, payload))
        loop.quit()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)

    worker.finished_run.connect(on_finished)
    worker.start()
    loop.exec()
    timer.stop()
    worker.wait(timeout_ms)
    assert captured, "worker did not emit finished_run within timeout"
    return captured[0]


@pytest.fixture
def paths(tmp_path):
    csv_path = tmp_path / "answers.csv"
    csv_path.write_text("center_id,answer\n", encoding="utf-8-sig")
    db_path = tmp_path / "members.accdb"
    db_path.write_bytes(b"fake-db")
    return str(csv_path), str(db_path)


def test_preview_passes_dry_run_and_makes_no_backup(
    paths, tmp_path, monkeypatch,
):
    csv_path, db_path = paths
    mock = MagicMock(return_value=0)
    monkeypatch.setattr("scripts.apply_hha_answers.main", mock)

    worker = ApplyHhaWorker(csv_path, db_path, mode="preview")
    success, payload = _run_to_completion(worker)

    assert success is True
    assert payload["mode"] == "preview"
    assert "backup" not in payload
    mock.assert_called_once_with(
        ["--csv", csv_path, "--db", db_path, "--dry-run"]
    )
    assert list(tmp_path.glob("*.backup_*")) == []


def test_apply_backs_up_before_running_without_dry_run(
    paths, tmp_path, monkeypatch,
):
    csv_path, db_path = paths
    backups_seen_at_call_time = []

    def fake_main(argv):
        backups_seen_at_call_time.append(
            len(list(tmp_path.glob("members.backup_*.accdb")))
        )
        return 0

    monkeypatch.setattr("scripts.apply_hha_answers.main", fake_main)

    worker = ApplyHhaWorker(csv_path, db_path, mode="apply")
    log_lines = []
    worker.log_line.connect(log_lines.append)
    success, payload = _run_to_completion(worker)

    assert success is True
    assert payload["mode"] == "apply"
    assert Path(payload["backup"]).exists()
    assert Path(payload["backup"]).name.startswith("members.backup_")
    assert Path(payload["backup"]).name.endswith(".accdb")
    # The backup existed by the time the script ran.
    assert backups_seen_at_call_time == [1]
    assert any("Backed up to" in line for line in log_lines)


def test_apply_backup_failure_short_circuits(paths, monkeypatch):
    csv_path, db_path = paths
    mock = MagicMock(return_value=0)
    monkeypatch.setattr("scripts.apply_hha_answers.main", mock)

    def raise_copy(_src, _dst):
        raise OSError("locked by Access")

    monkeypatch.setattr("apply_hha_gui.worker.shutil.copy2", raise_copy)

    worker = ApplyHhaWorker(csv_path, db_path, mode="apply")
    success, payload = _run_to_completion(worker)

    assert success is False
    assert payload["step"] == "backup"
    assert "locked by Access" in payload["error"]
    mock.assert_not_called()


def test_nonzero_return_code_reports_failure(paths, monkeypatch):
    csv_path, db_path = paths
    monkeypatch.setattr(
        "scripts.apply_hha_answers.main", MagicMock(return_value=2),
    )

    worker = ApplyHhaWorker(csv_path, db_path, mode="preview")
    success, payload = _run_to_completion(worker)

    assert success is False
    assert payload["step"] == "run"
    assert "exit code 2" in payload["error"]


def test_exception_in_main_is_caught(paths, monkeypatch):
    csv_path, db_path = paths
    monkeypatch.setattr(
        "scripts.apply_hha_answers.main",
        MagicMock(side_effect=RuntimeError("pyodbc boom")),
    )

    worker = ApplyHhaWorker(csv_path, db_path, mode="apply")
    success, payload = _run_to_completion(worker)

    assert success is False
    assert payload["step"] == "run"
    assert "pyodbc boom" in payload["error"]


def test_stdout_is_streamed_through_log_line(paths, monkeypatch):
    csv_path, db_path = paths

    def chatty_main(argv):
        print("  25023 day 7: 08:00-13:00 -> 08:00-12:00")
        print("Apply HHA answers summary")
        return 0

    monkeypatch.setattr("scripts.apply_hha_answers.main", chatty_main)

    worker = ApplyHhaWorker(csv_path, db_path, mode="preview")
    log_lines = []
    worker.log_line.connect(log_lines.append)
    success, _ = _run_to_completion(worker)

    assert success is True
    assert any("25023 day 7" in line for line in log_lines)
    assert any("summary" in line for line in log_lines)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests\test_apply_hha_worker.py -v`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'apply_hha_gui'`

- [ ] **Step 3: Implement the worker**

Create `apply_hha_gui/__init__.py` (empty file), then
`apply_hha_gui/worker.py`:

```python
"""Background worker for the Apply HHA Answers GUI.

Runs scripts.apply_hha_answers.main() on a QThread — with --dry-run
for preview, or backup-then-apply for the real run — streaming the
script's stdout to the GUI line by line via `LineBuffer` (reused from
setup_gui; spec §6)."""
import contextlib
import datetime
import shutil
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from setup_gui.log_buffer import LineBuffer
from scripts import apply_hha_answers


def _backup_path(db_path: str) -> str:
    """`<stem>.backup_<YYYY-MM-DD-HHMMSS><ext>` in the same folder —
    same convention as setup_gui so operators see one backup style."""
    p = Path(db_path)
    ts = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return str(p.with_name(f"{p.stem}.backup_{ts}{p.suffix}"))


class ApplyHhaWorker(QThread):
    log_line = pyqtSignal(str)
    finished_run = pyqtSignal(bool, dict)   # (success, payload)

    def __init__(self, csv_path: str, db_path: str, mode: str,
                 parent=None):
        if mode not in ("preview", "apply"):
            raise ValueError(f"unknown mode: {mode!r}")
        super().__init__(parent)
        self._csv_path = csv_path
        self._db_path = db_path
        self._mode = mode

    def run(self):
        payload = {"mode": self._mode}

        if self._mode == "apply":
            backup = _backup_path(self._db_path)
            try:
                shutil.copy2(self._db_path, backup)
            except OSError as exc:
                self.finished_run.emit(
                    False,
                    {**payload, "step": "backup", "error": str(exc)},
                )
                return
            payload["backup"] = backup
            self.log_line.emit(f"Backed up to {backup}")

        argv = ["--csv", self._csv_path, "--db", self._db_path]
        if self._mode == "preview":
            argv.append("--dry-run")

        buf = LineBuffer(self.log_line.emit)
        try:
            with contextlib.redirect_stdout(buf):
                rc = apply_hha_answers.main(argv)
            buf.flush()
        except Exception as exc:
            buf.flush()
            self.finished_run.emit(
                False, {**payload, "step": "run", "error": str(exc)},
            )
            return
        if rc is not None and rc != 0:
            self.finished_run.emit(
                False,
                {**payload, "step": "run",
                 "error": f"returned exit code {rc}"},
            )
            return
        self.finished_run.emit(True, payload)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests\test_apply_hha_worker.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apply_hha_gui/__init__.py apply_hha_gui/worker.py tests/test_apply_hha_worker.py
git commit -m "feat(apply_hha_gui): preview/apply worker thread"
```

---

### Task 5: Main window + entry point

**Files:**
- Create: `apply_hha_gui/main_window.py`
- Create: `apply_hha.py`

No unit tests for the window (matches `setup_gui/main_window.py`, which
has none — the state logic worth testing lives in the worker). Verified
by a manual smoke run in Step 3 and the full manual pass in Task 6.

- [ ] **Step 1: Implement the main window**

Create `apply_hha_gui/main_window.py`:

```python
"""Apply HHA Answers GUI main window: answers-CSV picker, DB picker,
Preview (dry-run) and Apply buttons, scrolling log. English-only.

Apply is enabled only after a successful Preview on the exact same
pair of paths; editing either path disables it again (spec §6)."""
import os

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from apply_hha_gui.worker import ApplyHhaWorker


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Apply HHA Answers")
        self.setMinimumWidth(560)
        self._worker: ApplyHhaWorker | None = None
        # (csv, db) paths of the last successful preview, or None.
        self._previewed: tuple[str, str] | None = None

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ── Title ─────────────────────────────────────────────
        title = QLabel("Apply HHA Answers")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)

        # ── Answers CSV picker ────────────────────────────────
        root.addWidget(QLabel("Answers CSV:"))
        self._csv_edit, self._csv_browse = self._picker_row(
            root, "Select Answers CSV", "CSV Files (*.csv)",
        )

        # ── DB picker ─────────────────────────────────────────
        root.addWidget(QLabel("Database File:"))
        self._db_edit, self._db_browse = self._picker_row(
            root, "Select Database File",
            "Access Database (*.accdb *.mdb)",
        )

        # ── Buttons ───────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_font = QFont()
        btn_font.setPointSize(11)
        btn_font.setBold(True)
        self._preview_btn = QPushButton("Preview (no changes)")
        self._preview_btn.setFixedHeight(40)
        self._preview_btn.setFont(btn_font)
        self._preview_btn.clicked.connect(self._on_preview_clicked)
        btn_row.addWidget(self._preview_btn)
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setFixedHeight(40)
        self._apply_btn.setFont(btn_font)
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        btn_row.addWidget(self._apply_btn)
        root.addLayout(btn_row)

        # ── Log ───────────────────────────────────────────────
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setMinimumHeight(260)
        root.addWidget(self._log)

    def _picker_row(self, root, caption, name_filter):
        """One QLineEdit + Browse button row. Returns (edit, button)."""
        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setMinimumWidth(360)
        edit.textChanged.connect(self._on_paths_changed)
        row.addWidget(edit, 1)
        btn = QPushButton("Browse…")
        btn.setFixedWidth(90)

        def on_browse():
            start = edit.text() or os.path.expanduser("~")
            path, _ = QFileDialog.getOpenFileName(
                self, caption, start, name_filter,
            )
            if path:
                edit.setText(path)

        btn.clicked.connect(on_browse)
        row.addWidget(btn)
        root.addLayout(row)
        return edit, btn

    # ── State helpers ─────────────────────────────────────────

    def _current_paths(self):
        return (
            self._csv_edit.text().strip(),
            self._db_edit.text().strip(),
        )

    def _on_paths_changed(self, _text=""):
        """Apply stays enabled only while the paths match the last
        successful preview."""
        self._apply_btn.setEnabled(
            self._worker is None
            and self._previewed is not None
            and self._current_paths() == self._previewed
        )

    def _validated_paths(self):
        """Return (csv, db) if both files exist, else None (+dialog)."""
        csv_path, db_path = self._current_paths()
        if not csv_path or not os.path.isfile(csv_path):
            QMessageBox.warning(
                self, "CSV Not Found",
                "Pick a valid answers CSV file first.",
            )
            return None
        if not db_path or not os.path.isfile(db_path):
            QMessageBox.warning(
                self, "Database Not Found",
                "Pick a valid .accdb file first.",
            )
            return None
        return csv_path, db_path

    def _start(self, mode):
        paths = self._validated_paths()
        if paths is None:
            return
        self._log.clear()
        for w in (self._preview_btn, self._apply_btn, self._csv_edit,
                  self._db_edit, self._csv_browse, self._db_browse):
            w.setEnabled(False)
        self._worker = ApplyHhaWorker(paths[0], paths[1], mode,
                                      parent=self)
        self._worker.log_line.connect(self._log.appendPlainText)
        self._worker.finished_run.connect(self._on_finished)
        self._worker.start()

    # ── Slots ─────────────────────────────────────────────────

    def _on_preview_clicked(self):
        self._previewed = None
        self._start("preview")

    def _on_apply_clicked(self):
        self._start("apply")

    def _on_finished(self, success: bool, payload: dict):
        self._worker = None
        for w in (self._preview_btn, self._csv_edit, self._db_edit,
                  self._csv_browse, self._db_browse):
            w.setEnabled(True)

        mode = payload.get("mode", "?")
        if success and mode == "preview":
            self._previewed = self._current_paths()
            self._log.appendPlainText("")
            self._log.appendPlainText(
                "Preview finished — no changes were made. Review the "
                "log above, then click Apply to make these changes."
            )
        elif success and mode == "apply":
            self._previewed = None
            backup = payload.get("backup", "")
            self._log.appendPlainText("")
            self._log.appendPlainText(f"Applied. Backup: {backup}")
            QMessageBox.information(
                self, "Apply Complete",
                "Availability was updated successfully.\n\n"
                f"A backup of the database is at:\n{backup}",
            )
        else:
            self._previewed = None
            step = payload.get("step", "?")
            error = payload.get("error", "unknown error")
            backup = payload.get("backup")
            self._log.appendPlainText("")
            self._log.appendPlainText(f"Failed at {step}: {error}")
            body = f"Failed at step '{step}'.\n\nError: {error}"
            if step == "backup":
                body += (
                    "\n\nNothing was changed. If the database is open "
                    "in Access or Excel, close it and try again."
                )
            elif backup:
                body += (
                    "\n\nThe database may be partially modified. To "
                    "restore, copy this file over the original:\n"
                    f"{backup}"
                )
            QMessageBox.warning(self, "Apply HHA Answers Failed", body)
        self._on_paths_changed()

    def closeEvent(self, event):
        """Wait up to 3 s for an in-flight worker before closing
        (same rationale as setup_gui)."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        event.accept()
```

- [ ] **Step 2: Create the entry point**

Create `apply_hha.py` (repo root, sibling of `gui.py` and `setup.py`):

```python
import sys

from PyQt6.QtWidgets import QApplication

from apply_hha_gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke-test the window manually**

Run: `.venv\Scripts\python apply_hha.py`

Check, then close the window:
- Window opens with both pickers, Preview enabled, Apply greyed out.
- Clicking Preview with empty paths shows the "CSV Not Found" dialog.
- Browse buttons open file dialogs with the right filters.

- [ ] **Step 4: Run the full test suite (no regressions)**

Run: `.venv\Scripts\python -m pytest tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apply_hha_gui/main_window.py apply_hha.py
git commit -m "feat(apply_hha_gui): main window with preview-then-apply flow"
```

---

### Task 6: PyInstaller spec, real-DB verification, exe build

**Files:**
- Create: `ApplyHHAAnswers.spec`

- [ ] **Step 1: Create the PyInstaller spec**

Create `ApplyHHAAnswers.spec` (modeled on `BSCASetup.spec`):

```python
# -*- mode: python ; coding: utf-8 -*-
# Build: .venv/Scripts/pyinstaller ApplyHHAAnswers.spec
# Output: dist/ApplyHHAAnswers.exe

a = Analysis(
    ['apply_hha.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pyodbc',
        # Imported statically, but listed explicitly to mirror
        # BSCASetup.spec and survive future refactors to importlib.
        'scripts',
        'scripts.apply_hha_answers',
        'monthly_schedule',
        'monthly_schedule.hha_answer_parser',
        'setup_gui',
        'setup_gui.log_buffer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest'],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ApplyHHAAnswers',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

- [ ] **Step 2: CLI dry-run against the operator's test DB**

The reviewed answers CSV is `hhbackfill_filled.csv` in the repo root;
the test DB is `C:\Users\luald\Videos\members.accdb` (already through
the setup chain — Availability is seeded).

Run:

```
.venv\Scripts\python scripts\apply_hha_answers.py --csv hhbackfill_filled.csv --db C:\Users\luald\Videos\members.accdb --dry-run
```

Expected: exit 0; summary shows ~85 members applied, 2 blank answers
skipped, 0 parse errors; a `hha_answers_review_<today>.csv` appears
next to `hhbackfill_filled.csv` containing only `split` / `blocked` /
`member_not_found` rows. Eyeball a few log lines against the CSV
(e.g. `25023 day 7: 08:00-13:00 -> 08:00-12:00`). If members are
missing from the test DB, `member_not_found` rows are expected — note
them, they are not failures.

- [ ] **Step 3: CLI real apply + spot-check the DB**

Run (no `--dry-run` — this DB is expendable per the operator):

```
.venv\Scripts\python scripts\apply_hha_answers.py --csv hhbackfill_filled.csv --db C:\Users\luald\Videos\members.accdb
```

Then spot-check with a scratch script (adjust IDs if `member_not_found`
said otherwise) — save as scratchpad, don't commit:

```python
import pyodbc
conn = pyodbc.connect(
    "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
    "DBQ=C:\\Users\\luald\\Videos\\members.accdb;")
cur = conn.cursor()
for cid, day in [("25255", 5), ("25023", 7)]:
    cur.execute(
        "SELECT [avail_start], [avail_end] FROM [Availability] "
        "WHERE [Center ID] = ? AND [Day Of Week] = ? "
        "AND [effective_end_date] IS NULL", cid, day)
    print(cid, day, cur.fetchone())
conn.close()
```

Expected: `25255 5` shows end `09:00` (care 9 AM - 1 PM pulled the end
in), `25023 7` shows end `12:00`. Re-run the apply command once more
and confirm the summary shows those days as unchanged (idempotency).

- [ ] **Step 4: Build the exe and verify the GUI end-to-end**

Run: `.venv\Scripts\pyinstaller ApplyHHAAnswers.spec`
Expected: `dist/ApplyHHAAnswers.exe` produced without errors.

Launch `dist\ApplyHHAAnswers.exe` and walk through:
1. Pick `hhbackfill_filled.csv` and the Videos `members.accdb`.
2. Preview — log streams, ends with the summary; Apply becomes enabled.
3. Edit the DB path (add a character) — Apply greys out; restore it —
   still greyed (path changed → must re-preview). Re-run Preview.
4. Apply — "Backed up to …" appears first, then the run; success
   dialog names the backup; a new `members.backup_*.accdb` exists in
   the Videos folder.

- [ ] **Step 5: Commit**

```bash
git add ApplyHHAAnswers.spec
git commit -m "build: PyInstaller spec for ApplyHHAAnswers.exe"
```
