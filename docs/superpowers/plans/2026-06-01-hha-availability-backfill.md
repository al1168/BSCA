# HHA → Availability Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-shot CLI script that parses the free-text `Contacts.HHA` column in an Access DB and writes resulting end-of-day constraints into the `Availability` table; ambiguous rows that contain time data we can't safely auto-interpret are emitted to a dated CSV.

**Architecture:** Two-module split — a pure parser (`monthly_schedule/hha_parser.py`, no DB or IO) drives a thin CLI (`scripts/backfill_availability_from_hha.py`) that does ODBC reads, upserts, CSV writing, and stdout reporting. The parser is built bottom-up with TDD against real samples drawn from `scripts/test_dbs/populate_real_members.accdb`.

**Tech Stack:** Python 3.11, pyodbc (existing dependency, used same way as `monthly_schedule/db.py`), pytest, csv (stdlib), argparse (stdlib).

**Reference spec:** [docs/superpowers/specs/2026-06-01-hha-availability-backfill-design.md](../specs/2026-06-01-hha-availability-backfill-design.md)

---

## Task 1: Module skeleton + Stage 2 "no time" quick reject

**Files:**
- Create: `monthly_schedule/hha_parser.py`
- Create: `tests/test_hha_parser.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_hha_parser.py`:

```python
"""Tests for monthly_schedule.hha_parser.

The parser must classify each HHA free-text row into one of four
outcomes: applied (DB write emitted), ambiguous (CSV row emitted),
skipped (had time but all clauses fell after center close), or
ignored (no time content at all). See
docs/superpowers/specs/2026-06-01-hha-availability-backfill-design.md
"""
from monthly_schedule.hha_parser import parse_hha_row


def test_empty_string_is_ignored():
    result = parse_hha_row("")
    assert result["ignored"] is True
    assert result["applied"] is False
    assert result["ambiguous"] is False
    assert result["skipped"] is False
    assert result["clauses"] == []


def test_days_only_no_time_is_ignored():
    # Real sample: "1.2.3.7" — just days, nothing to do.
    result = parse_hha_row("1.2.3.7")
    assert result["ignored"] is True


def test_agency_name_only_is_ignored():
    # Real sample: "Better Choice" — agency name, no schedule info.
    result = parse_hha_row("Better Choice")
    assert result["ignored"] is True


def test_agency_with_phone_is_ignored():
    # Real sample: "新康: (212) 390-5496" — phone digits must not
    # be mis-detected as a time block.
    result = parse_hha_row("新康: (212) 390-5496")
    assert result["ignored"] is True


def test_days_with_hours_count_no_time_is_ignored():
    # Real sample: "Better Choice: 3.4.5.6.7 x 3 Hrs" — hours but
    # no explicit time block.
    result = parse_hha_row("Better Choice: 3.4.5.6.7 x 3 Hrs")
    assert result["ignored"] is True


def test_day_range_without_time_marker_is_ignored():
    # "1-7" is a day range, not a time block. Without ':MM' or 'am'/'pm'
    # somewhere we must not mistake it for time content.
    result = parse_hha_row("1-7")
    assert result["ignored"] is True


def test_phone_dash_digits_alone_is_ignored():
    # Phone "390-5496" looks dash-y but has no time marker.
    result = parse_hha_row("Always Home Care 390-5496")
    assert result["ignored"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monthly_schedule.hha_parser'`.

- [ ] **Step 3: Write minimal implementation**

`monthly_schedule/hha_parser.py`:

```python
"""Parse the free-text Contacts.HHA column into Availability writes.

Public surface: parse_hha_row(text) -> dict with keys
  clauses, applied, ambiguous, skipped, ignored,
  ambiguous_reason, attempted_parse.

See docs/superpowers/specs/2026-06-01-hha-availability-backfill-design.md
for the full classification rules. Helpers prefixed with _ are private.
"""
import re

# A loose "time-range-looking substring" pattern: two number groups
# (each up to "12:34" or "12.34") joined by a dash (ASCII or unicode).
# Used by Stage 2 quick reject. We post-filter matches with
# _MARKER_PATTERN below — a real time block must contain ":MM" or
# "am"/"pm" somewhere. This prevents pure day-ranges like "1-7" or
# phone fragments like "390-5496" from being mistaken for times.
_TIME_PATTERN = re.compile(
    r"\d{1,2}\s*[:.]?\s*\d{0,2}\s*(?:am|pm)?"
    r"\s*[-–~]\s*"
    r"\d{1,2}\s*[:.]?\s*\d{0,2}\s*(?:am|pm)?",
    re.IGNORECASE,
)

# A real time block must have ":<digit>" or "am"/"pm" somewhere
# inside. "1-7" and "390-5496" have neither.
_MARKER_PATTERN = re.compile(r":\d|am|pm", re.IGNORECASE)


def _empty_result():
    return {
        "clauses": [],
        "applied": False,
        "ambiguous": False,
        "skipped": False,
        "ignored": False,
        "ambiguous_reason": None,
        "attempted_parse": "",
    }


def _has_time_pattern(text):
    """True iff text contains at least one time-range substring with
    an explicit time marker (':MM' or 'am'/'pm')."""
    for m in _TIME_PATTERN.finditer(text):
        if _MARKER_PATTERN.search(m.group(0)):
            return True
    return False


def parse_hha_row(text):
    result = _empty_result()
    if text is None or not text.strip():
        result["ignored"] = True
        return result
    if not _has_time_pattern(text):
        result["ignored"] = True
        return result
    # No further stages wired yet — placeholder.
    result["ignored"] = True
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/hha_parser.py tests/test_hha_parser.py
git commit -m "feat(hha): module skeleton + Stage 2 no-time quick reject"
```

---

## Task 2: Time block parser helper

**Files:**
- Modify: `monthly_schedule/hha_parser.py` — add `_parse_time_block`
- Modify: `tests/test_hha_parser.py` — add helper tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hha_parser.py`:

```python
import pytest
from monthly_schedule.hha_parser import _parse_time_block


@pytest.mark.parametrize("text,expected", [
    # Trailing pm applies to both sides
    ("2:30-7pm", ("14:30", "19:00")),
    ("2pm-8pm", ("14:00", "20:00")),
    # Trailing am applies to both
    ("7am-11am", ("07:00", "11:00")),
    # Start has am, end has pm (cross noon)
    ("8am-12pm", ("08:00", "12:00")),
    # End only has pm, start < end -> start is am
    ("8-12am", ("08:00", "12:00")),
    # End only has pm, start < end numerically with pm context
    ("3-7pm", ("15:00", "19:00")),
    # Half-time via dot ("5.45pm" -> 5:45 pm)
    ("12-5.45pm", ("12:00", "17:45")),
    # Both sides full
    ("8:30-11:30PM", ("20:30", "23:30")),
    # Unicode en-dash and whitespace
    ("2 – 7 pm", ("14:00", "19:00")),
    # Space in colon position ("8: 30PM")
    ("3:30-8: 30PM", ("15:30", "20:30")),
    # 12am edge: 12am = 00:00, but rare in HHA data; keep strict
    ("12am-1am", ("00:00", "01:00")),
])
def test_parse_time_block_accepts_real_formats(text, expected):
    assert _parse_time_block(text) == expected


@pytest.mark.parametrize("text", [
    "garbage",
    "after 1p.m.",         # only one side, no dash
    "3-",                  # truncated (real sample: "5.6.7(2:45pm-")
    "",
])
def test_parse_time_block_returns_none_for_unparseable(text):
    assert _parse_time_block(text) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`
Expected: FAIL with `ImportError: cannot import name '_parse_time_block'`.

- [ ] **Step 3: Implement `_parse_time_block`**

Add to `monthly_schedule/hha_parser.py`:

```python
# Match a single side of a time block: 1-2 digit hour, optional
# minutes via ":MM" or ".MM", optional am/pm suffix. Tolerates
# spaces around the colon ("8: 30PM" is real data).
_TIME_SIDE = re.compile(
    r"(\d{1,2})\s*[:.]?\s*(\d{2})?\s*(am|pm)?",
    re.IGNORECASE,
)

# Match a full time block: <side> <dash> <side>. The dash may be
# ASCII '-' or unicode en-dash. Anchored with re.search so the
# caller can pass a substring or full clause body.
_TIME_BLOCK = re.compile(
    r"(\d{1,2}\s*[:.]?\s*\d{0,2}\s*(?:am|pm)?)"
    r"\s*[-–~]\s*"
    r"(\d{1,2}\s*[:.]?\s*\d{0,2}\s*(?:am|pm)?)",
    re.IGNORECASE,
)


def _parse_one_side(side_text, fallback_suffix):
    """Parse one side of a time block to ('HH', 'MM', 'am'|'pm'|None).
    fallback_suffix is used when the side has no explicit am/pm but the
    other side does."""
    m = _TIME_SIDE.fullmatch(side_text.strip())
    if not m:
        return None
    hour, minute, suffix = m.group(1), m.group(2) or "00", m.group(3)
    if suffix:
        suffix = suffix.lower()
    else:
        suffix = fallback_suffix
    return hour, minute, suffix


def _to_24h(hour, minute, suffix):
    """Convert ('7','30','pm') to '19:30'. suffix may be None
    meaning 'no am/pm and no fallback' — caller decides."""
    h = int(hour)
    m = int(minute)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    if suffix == "pm":
        if h < 12:
            h += 12
    elif suffix == "am":
        if h == 12:
            h = 0
    elif suffix is None:
        # No am/pm anywhere. Caller has already failed if this is
        # unsafe; we just emit the raw hour.
        pass
    return f"{h:02d}:{m:02d}"


def _parse_time_block(text):
    """Return ('HH:MM', 'HH:MM') or None.

    Suffix propagation: if only one side has am/pm, that suffix is
    inferred for the other side. If neither side has a suffix, we
    can't safely classify so return None.
    """
    if not text:
        return None
    m = _TIME_BLOCK.search(text)
    if not m:
        return None
    left_raw, right_raw = m.group(1), m.group(2)
    right = _parse_one_side(right_raw, None)
    if right is None:
        return None
    left = _parse_one_side(left_raw, right[2])
    if left is None:
        return None
    # If right has no suffix either, try left's
    if right[2] is None and left[2] is not None:
        right = (right[0], right[1], left[2])
    if left[2] is None or right[2] is None:
        return None
    start = _to_24h(*left)
    end = _to_24h(*right)
    if start is None or end is None:
        return None
    return (start, end)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`
Expected: all tests pass (the 5 original + the new parametrized ones).

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/hha_parser.py tests/test_hha_parser.py
git commit -m "feat(hha): _parse_time_block tolerant of real-world formats"
```

---

## Task 3: Days parser helper

**Files:**
- Modify: `monthly_schedule/hha_parser.py` — add `_parse_days`
- Modify: `tests/test_hha_parser.py` — add tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hha_parser.py`:

```python
from monthly_schedule.hha_parser import _parse_days


@pytest.mark.parametrize("text,expected", [
    ("1.2.3", {1, 2, 3}),
    ("1,2,3", {1, 2, 3}),
    ("4.5.6", {4, 5, 6}),
    ("1-5", {1, 2, 3, 4, 5}),
    ("1-7", {1, 2, 3, 4, 5, 6, 7}),
    ("4-7", {4, 5, 6, 7}),
    # Mixed dot+range (real sample: "1-5.6.7" doesn't appear but
    # "1-5(...) 6.7(...)" does; per-clause this could be "1-5" alone)
    ("2.4.7", {2, 4, 7}),
    # Single day
    ("4", {4}),
    # Whitespace tolerance
    (" 1 . 2 . 3 ", {1, 2, 3}),
])
def test_parse_days_accepts_real_formats(text, expected):
    assert _parse_days(text) == expected


@pytest.mark.parametrize("text", [
    "",
    "abc",
    "8",          # out of 1-7 range
    "0",          # out of 1-7 range
])
def test_parse_days_returns_empty_set_when_no_valid_days(text):
    assert _parse_days(text) == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`
Expected: FAIL on the new tests with `ImportError: cannot import name '_parse_days'`.

- [ ] **Step 3: Implement `_parse_days`**

Add to `monthly_schedule/hha_parser.py`:

```python
# Match either a "N-M" range or a single digit N in 1..7.
_DAY_TOKEN = re.compile(r"(\d)\s*-\s*(\d)|(\d)")


def _parse_days(text):
    """Extract day-of-week ints (1..7) from a string fragment.

    Accepts dot-, comma-, or hyphen-separated digits, including ranges
    like '1-5'. Returns a set. Out-of-range digits (0, 8, 9) are
    dropped silently — they're not valid weekdays in this convention
    (1=Mon..7=Sun).
    """
    if not text:
        return set()
    out = set()
    for m in _DAY_TOKEN.finditer(text):
        if m.group(1) and m.group(2):
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo <= hi:
                for d in range(lo, hi + 1):
                    if 1 <= d <= 7:
                        out.add(d)
        elif m.group(3):
            d = int(m.group(3))
            if 1 <= d <= 7:
                out.add(d)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/hha_parser.py tests/test_hha_parser.py
git commit -m "feat(hha): _parse_days handles dot/comma/range formats"
```

---

## Task 4: Single-clause end-of-day classification (happy path)

This is the user's canonical example: `PPL: (4.5.6) 2:30-7pm` → apply on days 4,5,6 with avail_end=14:30.

**Files:**
- Modify: `monthly_schedule/hha_parser.py` — wire parse_hha_row to use helpers for single-clause input
- Modify: `tests/test_hha_parser.py` — high-level row tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hha_parser.py`:

```python
def _apply_clauses(result):
    """Helper: return list of (day, avail_end) for clauses that
    were marked apply, sorted by day for stable comparison."""
    out = []
    for c in result["clauses"]:
        if c["status"] == "apply":
            for d in sorted(c["days"]):
                out.append((d, c["avail_end"]))
    return sorted(out)


def test_user_example_ppl_thursday_friday_saturday():
    # The canonical example from the spec.
    result = parse_hha_row("PPL: (4.5.6) 2:30-7pm")
    assert result["applied"] is True
    assert result["ambiguous"] is False
    assert result["ignored"] is False
    assert _apply_clauses(result) == [
        (4, "14:30"), (5, "14:30"), (6, "14:30"),
    ]


def test_single_clause_no_agency_prefix():
    # Real sample: "5.6.7(2pm-6pm)"
    result = parse_hha_row("5.6.7(2pm-6pm)")
    assert result["applied"] is True
    assert _apply_clauses(result) == [
        (5, "14:00"), (6, "14:00"), (7, "14:00"),
    ]


def test_single_clause_day_range():
    # Real sample: "1-7(2-6pm)"
    result = parse_hha_row("1-7(2-6pm)")
    assert result["applied"] is True
    assert _apply_clauses(result) == [(d, "14:00") for d in range(1, 8)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`
Expected: 3 new failures — `parse_hha_row` still returns ignored.

- [ ] **Step 3: Implement the time-anchored splitter + single-clause classification**

Add to `monthly_schedule/hha_parser.py`:

```python
# Center open/close, baked in per spec.
_CENTER_OPEN = "08:00"
_CENTER_CLOSE = "16:00"


def _split_clauses(text):
    """Yield (days_text, time_text) pairs.

    Strategy: find every time block in `text` via _TIME_BLOCK.finditer
    and post-filter with _MARKER_PATTERN so day-ranges like "1-7" are
    skipped (they get absorbed into the days_text of the next real
    time block).

    For each accepted match, "days_text" is the substring between the
    previous accepted time-end (or start of string) and this match's
    start. Handles both forms naturally:
      "(4.5.6) 2:30-7pm"         -> [("(4.5.6) ", "2:30-7pm")]
      "5.6.7(2pm-6pm)"           -> [("5.6.7(",   "2pm-6pm")]
      "1-7(2-6pm)"               -> [("1-7(",     "2-6pm")]
      "(d1) t1, (d2) t2"         -> [("(d1) ", t1), (", (d2) ", t2)]
      "d1(t1) d2(t2)"            -> [("d1(", t1), (") d2(", t2)]
    """
    pairs = []
    cursor = 0
    for m in _TIME_BLOCK.finditer(text):
        time_text = m.group(0)
        if not _MARKER_PATTERN.search(time_text):
            # Looks dash-joined but no real time marker — skip without
            # advancing cursor so the next accepted clause's days_text
            # subsumes it.
            continue
        days_text = text[cursor:m.start()]
        pairs.append((days_text, time_text))
        cursor = m.end()
    return pairs


def _classify_clause(days, time_block):
    """Given a set of days and a (start, end) tuple, return a Clause
    dict. Pure classification — no side effects.
    """
    if time_block is None:
        return {
            "days": days,
            "avail_end": None,
            "status": "ambiguous",
            "reason": "time_unparseable",
        }
    start, _end = time_block
    if not days:
        return {
            "days": set(),
            "avail_end": None,
            "status": "ambiguous",
            "reason": "days_missing",
        }
    if start >= _CENTER_CLOSE:
        return {
            "days": days,
            "avail_end": None,
            "status": "skip",
            "reason": None,
        }
    if start <= _CENTER_OPEN:
        return {
            "days": days,
            "avail_end": None,
            "status": "ambiguous",
            "reason": "morning_or_pre_open",
        }
    return {
        "days": days,
        "avail_end": start,
        "status": "apply",
        "reason": None,
    }


def _aggregate_row(clauses, attempted_parse):
    """Combine clause outcomes into a ParsedRow dict."""
    applied = any(c["status"] == "apply" for c in clauses)
    ambiguous = any(c["status"] == "ambiguous" for c in clauses)
    skipped_only = (
        not applied and not ambiguous
        and any(c["status"] == "skip" for c in clauses)
    )
    # Reason priority per spec; only set when ambiguous.
    reason = None
    if ambiguous:
        priority = [
            "date_conditioned", "chinese_note", "morning_or_pre_open",
            "time_unparseable", "days_missing", "clause_split_failed",
        ]
        present = {c["reason"] for c in clauses if c["status"] == "ambiguous"}
        for p in priority:
            if p in present:
                reason = p
                break
    return {
        "clauses": clauses,
        "applied": applied,
        "ambiguous": ambiguous,
        "skipped": skipped_only,
        "ignored": False,
        "ambiguous_reason": reason,
        "attempted_parse": attempted_parse,
    }


def parse_hha_row(text):
    if text is None or not text.strip():
        return {**_empty_result(), "ignored": True}
    if not _has_time_pattern(text):
        return {**_empty_result(), "ignored": True}
    pairs = _split_clauses(text)
    if not pairs:
        # Time-looking substring exists but the stricter _TIME_BLOCK
        # regex couldn't lock onto a clause. Flag for review.
        return _aggregate_row(
            [{"days": set(), "avail_end": None,
              "status": "ambiguous", "reason": "clause_split_failed"}],
            attempted_parse=f"raw={text!r}",
        )
    # Collect row-wide days so a clause missing its own days can fall
    # back to "all days mentioned elsewhere in the row".
    row_days = set()
    for days_text, _ in pairs:
        row_days |= _parse_days(days_text)
    clauses = []
    for days_text, time_text in pairs:
        days = _parse_days(days_text) or row_days
        time_block = _parse_time_block(time_text)
        clauses.append(_classify_clause(days, time_block))
    attempted = "; ".join(
        f"days={sorted(c['days'])} end={c['avail_end']} "
        f"status={c['status']} reason={c['reason']}"
        for c in clauses
    )
    return _aggregate_row(clauses, attempted)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/hha_parser.py tests/test_hha_parser.py
git commit -m "feat(hha): classify single end-of-day clause"
```

---

## Task 5: Skip clauses where HHA is fully after center close

**Files:**
- Modify: `tests/test_hha_parser.py` — add tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hha_parser.py`:

```python
def test_evening_only_hha_is_skipped_row_outcome():
    # Real sample: "(1.4.6.7) 5-10pm" — HHA at 17:00, after center
    # closes at 16:00. No DB write, no CSV row.
    result = parse_hha_row("(1.4.6.7) 5-10pm")
    assert result["applied"] is False
    assert result["ambiguous"] is False
    assert result["skipped"] is True
    assert result["ignored"] is False


def test_hha_starting_exactly_at_close_is_skipped():
    # Edge case: HHA_start == 16:00. Per spec >= 16:00 is skip.
    result = parse_hha_row("1.2.3 4-8pm")
    assert result["skipped"] is True
    assert result["applied"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`

If they already pass (Task 4's logic should handle this since `_classify_clause` already returns `status="skip"` for `start >= 16:00`), check that `result["skipped"]` is `True`. If the aggregation isn't setting `skipped` correctly, the test will catch it.

Expected: tests pass (this is a behavior-confirming test for logic already implemented). If they fail, fix `_aggregate_row` to set `skipped=True` when no apply/ambiguous but at least one skip clause.

- [ ] **Step 3: (Conditional) Fix `_aggregate_row` if needed**

If tests failed in Step 2, the fix is already in the code from Task 4 (`skipped_only` variable). Reread that code to confirm the boolean lands in the returned dict as `skipped`.

- [ ] **Step 4: Confirm green**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_hha_parser.py
git commit -m "test(hha): confirm after-close clauses produce skipped row outcome"
```

---

## Task 6: Morning HHA → ambiguous

**Files:**
- Modify: `tests/test_hha_parser.py` — add tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hha_parser.py`:

```python
def test_morning_hha_is_ambiguous():
    # Real sample: "1.2.3(7AM-10AM)" — HHA_start = 07:00 < 08:00.
    # Per spec we don't try to push avail_start later; flag it.
    result = parse_hha_row("1.2.3(7AM-10AM)")
    assert result["ambiguous"] is True
    assert result["ambiguous_reason"] == "morning_or_pre_open"
    assert result["applied"] is False


def test_hha_starting_exactly_at_open_is_ambiguous():
    # Edge: HHA_start == 08:00 means the whole center day is blocked.
    # Per spec <= 08:00 is morning_or_pre_open ambiguous.
    result = parse_hha_row("1.2.3.4.5.6.7 (8am-12am)")
    assert result["ambiguous"] is True
    assert result["ambiguous_reason"] == "morning_or_pre_open"
```

- [ ] **Step 2: Run tests to verify they pass (or fail and fix)**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`

These should already pass because `_classify_clause` returns `ambiguous` with `reason="morning_or_pre_open"` when `start <= _CENTER_OPEN`. If a test fails it indicates a real bug in the classifier — fix it before moving on.

- [ ] **Step 3: Commit**

```bash
git add tests/test_hha_parser.py
git commit -m "test(hha): confirm morning HHA is flagged morning_or_pre_open"
```

---

## Task 7: Normalize stage — lowercase, unicode punctuation, agency strip

Up to now the parser has been lucky that real inputs happen to lowercase cleanly. Add the normalize stage to handle Unicode punctuation (`（）：，`) and to strip leading agency prefixes.

**Files:**
- Modify: `monthly_schedule/hha_parser.py` — add `_normalize`, wire into `parse_hha_row`
- Modify: `tests/test_hha_parser.py` — add tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hha_parser.py`:

```python
from monthly_schedule.hha_parser import _normalize


def test_normalize_replaces_unicode_punctuation():
    # Real sample: "25026.0|万友: 5.6.7 ( 3:30-8: 30PM)" already has
    # ASCII but Chinese rows can have full-width punctuation.
    assert _normalize("（4.5.6）2:30-7pm") == "(4.5.6) 2:30-7pm"


def test_normalize_strips_agency_prefix():
    # "PPL:" is agency name + colon. No digits before the colon =>
    # strip it. (We keep "(212) 226-1353" etc. because the digits
    # come before the colon there.)
    assert _normalize("PPL: (4.5.6) 2:30-7pm") == "(4.5.6) 2:30-7pm"


def test_normalize_does_not_strip_when_digit_precedes_colon():
    # "2:30" is a time, not an agency prefix. Don't strip past it.
    text = _normalize("(4.5.6) 2:30-7pm")
    assert text == "(4.5.6) 2:30-7pm"


def test_normalize_strips_chinese_agency_prefix():
    # Real sample: "万有: (6.7) 12pm-6pm" — CJK agency name.
    out = _normalize("万有: (6.7) 12pm-6pm")
    assert out == "(6.7) 12pm-6pm"


def test_normalize_lowercases_am_pm():
    assert "PM" not in _normalize("2:30-7PM")


def test_user_example_still_works_after_normalize_wiring():
    # Defensive — make sure Task 4's behavior didn't regress.
    result = parse_hha_row("PPL: (4.5.6) 2:30-7pm")
    assert _apply_clauses(result) == [
        (4, "14:30"), (5, "14:30"), (6, "14:30"),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`
Expected: new tests fail — `_normalize` doesn't exist yet.

- [ ] **Step 3: Implement `_normalize`**

Add to `monthly_schedule/hha_parser.py` (place near the top, after the imports/constants):

```python
_UNICODE_PUNCT_MAP = str.maketrans({
    "（": "(",  # full-width (
    "）": ")",  # full-width )
    "：": ":",  # full-width :
    "，": ",",  # full-width ,
    "　": " ",  # ideographic space
})


def _normalize(text):
    """Lowercase, normalize Unicode punctuation, strip a leading
    agency prefix, and collapse whitespace.

    Agency prefix = anything before the first ':' provided no digit
    appears before that ':'. This preserves time substrings like
    '2:30' (digit precedes ':') and phone numbers like '(212) 390-5496'
    (digits precede ':').
    """
    if not text:
        return ""
    s = text.translate(_UNICODE_PUNCT_MAP).lower()
    # Strip leading agency: find first ':' and check if any digit
    # appears before it.
    colon = s.find(":")
    if colon != -1 and not any(ch.isdigit() for ch in s[:colon]):
        s = s[colon + 1:]
    # Collapse internal whitespace, trim ends.
    s = re.sub(r"\s+", " ", s).strip()
    return s
```

Then update `parse_hha_row` to call `_normalize` before the time check (only the first three lines change; the rest of the body from Task 4 is unchanged):

```python
def parse_hha_row(text):
    if text is None or not text.strip():
        return {**_empty_result(), "ignored": True}
    normalized = _normalize(text)
    if not _has_time_pattern(normalized):
        return {**_empty_result(), "ignored": True}
    pairs = _split_clauses(normalized)
    if not pairs:
        return _aggregate_row(
            [{"days": set(), "avail_end": None,
              "status": "ambiguous", "reason": "clause_split_failed"}],
            attempted_parse=f"raw={normalized!r}",
        )
    row_days = set()
    for days_text, _ in pairs:
        row_days |= _parse_days(days_text)
    clauses = []
    for days_text, time_text in pairs:
        days = _parse_days(days_text) or row_days
        time_block = _parse_time_block(time_text)
        clauses.append(_classify_clause(days, time_block))
    attempted = "; ".join(
        f"days={sorted(c['days'])} end={c['avail_end']} "
        f"status={c['status']} reason={c['reason']}"
        for c in clauses
    )
    return _aggregate_row(clauses, attempted)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/hha_parser.py tests/test_hha_parser.py
git commit -m "feat(hha): _normalize handles unicode + agency prefix"
```

---

## Task 8: Confirm multi-clause behavior

The time-anchored `_split_clauses` from Task 4 already handles multi-clause rows. This task locks in that behavior with explicit tests against real samples like `(3.4) 1pm-7pm, (5.6) 1-6pm` and `1.2.3.4(11-2pm) 5.6.7(11-1pm)`. If a test fails, fix the splitter — don't rewrite it.

**Files:**
- Modify: `tests/test_hha_parser.py` — multi-clause tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hha_parser.py`:

```python
def test_two_clauses_comma_separated():
    # Real sample: "仁人: (3.4) 1pm-7pm, (5.6) 1-6pm"
    result = parse_hha_row("(3.4) 1pm-7pm, (5.6) 1-6pm")
    assert result["applied"] is True
    assert _apply_clauses(result) == [
        (3, "13:00"), (4, "13:00"), (5, "13:00"), (6, "13:00"),
    ]


def test_two_clauses_space_separated_with_inline_days():
    # Real sample: "1.2.3.4(11-2pm) 5.6.7(11-1pm)"
    result = parse_hha_row("1.2.3.4(11-2pm) 5.6.7(11-1pm)")
    assert result["applied"] is True
    assert _apply_clauses(result) == [
        (1, "11:00"), (2, "11:00"), (3, "11:00"), (4, "11:00"),
        (5, "11:00"), (6, "11:00"), (7, "11:00"),
    ]


def test_mixed_apply_and_skip_not_flagged():
    # Real sample: "(1.3.5) 8:30-11:30PM, (7)3pm-6PM"
    # First clause is evening (after close) -> skip.
    # Second clause is afternoon -> apply.
    # Per spec: row is applied, NOT ambiguous.
    result = parse_hha_row("(1.3.5) 8:30-11:30PM, (7)3pm-6PM")
    assert result["applied"] is True
    assert result["ambiguous"] is False
    assert _apply_clauses(result) == [(7, "15:00")]


def test_mixed_apply_and_ambiguous_row_flagged():
    # Constructed: first clause morning (ambiguous), second clause
    # afternoon (apply). Per spec: row is applied AND ambiguous.
    result = parse_hha_row("(1) 7am-10am, (7) 3pm-6pm")
    assert result["applied"] is True
    assert result["ambiguous"] is True
    assert result["ambiguous_reason"] == "morning_or_pre_open"


def test_three_clauses_per_day_groups():
    # Real sample: "常常: (1) 4-8pm, (2.3) 4-9pm, (6.7) 5-9pm"
    result = parse_hha_row("(1) 4-8pm, (2.3) 4-9pm, (6.7) 5-9pm")
    assert _apply_clauses(result) == [
        (1, "16:00"), (2, "16:00"), (3, "16:00"),
        (6, "17:00"), (7, "17:00"),
    ]
```

Replace the placeholder third test with this corrected version (note: `4-8pm` has start = 16:00, which is `>= _CENTER_CLOSE` → skip, not apply):

```python
def test_three_clauses_all_after_close_row_is_skipped():
    # Real sample: "常常: (1) 4-8pm, (2.3) 4-9pm, (6.7) 5-9pm"
    # 4pm = 16:00, which is >= center close 16:00 -> skip.
    # Whole row outcome: skipped.
    result = parse_hha_row("(1) 4-8pm, (2.3) 4-9pm, (6.7) 5-9pm")
    assert result["applied"] is False
    assert result["ambiguous"] is False
    assert result["skipped"] is True
```

- [ ] **Step 2: Run tests and confirm they pass**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`

These tests should pass without code changes because `_split_clauses` from Task 4 already handles multi-clause rows. If any test fails, the splitter has a bug — fix it before continuing.

- [ ] **Step 3: Commit**

```bash
git add tests/test_hha_parser.py
git commit -m "test(hha): lock in multi-clause splitter behavior"
```

---

## Task 9: Special-case detectors — date_conditioned and chinese_note

**Files:**
- Modify: `monthly_schedule/hha_parser.py` — add detectors, wire them in before clause-splitting
- Modify: `tests/test_hha_parser.py` — tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hha_parser.py`:

```python
def test_date_conditioned_is_ambiguous():
    # Real sample: "6/1-6/30 (2.4.6.7) 7am-12pm,, 7/1-X (2.4.6.7) 3-8pm"
    text = "6/1-6/30 (2.4.6.7) 7am-12pm,, 7/1-X (2.4.6.7) 3-8pm"
    result = parse_hha_row(text)
    assert result["ambiguous"] is True
    assert result["ambiguous_reason"] == "date_conditioned"


def test_chinese_note_in_body_is_ambiguous():
    # Real sample: "占时每天2pm 开始护理 11/1/25有变动"
    text = "占时每天2pm 开始护理 11/1/25有变动"
    result = parse_hha_row(text)
    assert result["ambiguous"] is True
    # date_conditioned has higher priority than chinese_note per spec,
    # but this string also has "11/1/25" — accept either as long as
    # the row is flagged. Pin the priority:
    assert result["ambiguous_reason"] in {
        "date_conditioned", "chinese_note",
    }


def test_leading_chinese_agency_is_stripped_not_flagged():
    # Real sample: "万有: (6.7) 12pm-6pm" — CJK is only the agency
    # name. Should normalize away and parse cleanly.
    result = parse_hha_row("万有: (6.7) 12pm-6pm")
    assert result["applied"] is True
    assert result["ambiguous"] is False
    assert _apply_clauses(result) == [(6, "12:00"), (7, "12:00")]


def test_date_conditioned_priority_over_morning():
    # Even though "7am-12pm" would be morning_or_pre_open, the date
    # prefix wins per the priority table.
    result = parse_hha_row("6/1-6/30 (2.4.6.7) 7am-12pm")
    assert result["ambiguous_reason"] == "date_conditioned"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`
Expected: failures on the new tests.

- [ ] **Step 3: Implement the detectors**

Add to `monthly_schedule/hha_parser.py`:

```python
# A date substring like "6/1", "6/1-6/30", "11/1/25", "7/1-X".
# Anchored by a digit + slash + digit (with optional more parts).
_DATE_PATTERN = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4}|-\d{1,2}/\d{1,2}|-x)?\b",
                            re.IGNORECASE)

# CJK Unified Ideographs (and most common extensions used in this data).
_CJK_PATTERN = re.compile(r"[一-鿿]")


def _detect_special_case(normalized_text):
    """Return a reason string for date_conditioned or chinese_note,
    or None. `normalized_text` is post-_normalize (agency stripped),
    so any CJK that remains is in the BODY not the agency name.
    """
    if _DATE_PATTERN.search(normalized_text):
        return "date_conditioned"
    if _CJK_PATTERN.search(normalized_text):
        return "chinese_note"
    return None
```

Modify `parse_hha_row` to call the detector right after `_has_time_pattern` and before `_split_clauses`. Only the inserted block is new; the rest is unchanged from Task 7:

```python
def parse_hha_row(text):
    if text is None or not text.strip():
        return {**_empty_result(), "ignored": True}
    normalized = _normalize(text)
    if not _has_time_pattern(normalized):
        return {**_empty_result(), "ignored": True}
    special = _detect_special_case(normalized)
    if special is not None:
        # Short-circuit: emit one ambiguous clause carrying the reason.
        # We still record the row as "saw time content" — not ignored.
        clause = {
            "days": set(), "avail_end": None,
            "status": "ambiguous", "reason": special,
        }
        return _aggregate_row(
            [clause],
            attempted_parse=f"special={special} raw={normalized!r}",
        )
    pairs = _split_clauses(normalized)
    if not pairs:
        return _aggregate_row(
            [{"days": set(), "avail_end": None,
              "status": "ambiguous", "reason": "clause_split_failed"}],
            attempted_parse=f"raw={normalized!r}",
        )
    row_days = set()
    for days_text, _ in pairs:
        row_days |= _parse_days(days_text)
    clauses = []
    for days_text, time_text in pairs:
        days = _parse_days(days_text) or row_days
        time_block = _parse_time_block(time_text)
        clauses.append(_classify_clause(days, time_block))
    attempted = "; ".join(
        f"days={sorted(c['days'])} end={c['avail_end']} "
        f"status={c['status']} reason={c['reason']}"
        for c in clauses
    )
    return _aggregate_row(clauses, attempted)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -m pytest tests/test_hha_parser.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/hha_parser.py tests/test_hha_parser.py
git commit -m "feat(hha): detect date_conditioned and chinese_note rows"
```

---

## Task 10: CLI script skeleton — argparse + DB read

**Files:**
- Create: `scripts/backfill_availability_from_hha.py`

- [ ] **Step 1: Write the script skeleton**

`scripts/backfill_availability_from_hha.py`:

```python
"""Backfill the Availability table from Contacts.HHA free text.

Reads every non-empty HHA row, classifies it via
monthly_schedule.hha_parser, then writes end-of-day constraints to
Availability. Ambiguous rows are emitted to a dated CSV in --csv-out.

See docs/superpowers/specs/2026-06-01-hha-availability-backfill-design.md
"""
import argparse
import csv
import datetime
import os
import sys
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monthly_schedule.hha_parser import parse_hha_row  # noqa: E402


_CONTACTS_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [HHA] "
    "FROM [Contacts]"
)


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _read_contacts(conn):
    """Yield (center_id:int, last_name, first_name, hha_text) tuples.
    Rows with NULL Center ID or NULL/empty HHA are skipped here so
    downstream code only sees actionable rows.
    """
    cur = conn.cursor()
    cur.execute(_CONTACTS_QUERY)
    for row in cur.fetchall():
        center_id, last, first, hha = row
        if center_id is None:
            continue
        if hha is None or not str(hha).strip():
            continue
        yield int(center_id), last, first, str(hha)


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Backfill Availability from Contacts.HHA."
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--csv-out", default=".",
                   help="Directory for the ambiguous CSV. Default: cwd.")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse + write CSV, do NOT commit DB changes.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-row stdout; print only the summary.")
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
        count = 0
        for cid, last, first, hha in _read_contacts(conn):
            _ = parse_hha_row(hha)  # ignored — wired in next task
            count += 1
        print(f"Read {count} non-empty HHA rows. (no writes yet)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test the read path**

Run:
```
c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe scripts/backfill_availability_from_hha.py --db scripts/test_dbs/populate_real_members.accdb --dry-run
```
Expected: prints `Read 377 non-empty HHA rows. (no writes yet)` and exits 0.

If the count differs from 377, that's fine — it just means the DB content shifted. We are confirming the read path works end-to-end.

- [ ] **Step 3: Commit**

```bash
git add scripts/backfill_availability_from_hha.py
git commit -m "feat(hha): CLI skeleton reads Contacts.HHA via ODBC"
```

---

## Task 11: CLI — Availability upsert logic

**Files:**
- Modify: `scripts/backfill_availability_from_hha.py` — add upsert helper, wire into main loop

- [ ] **Step 1: Add the upsert helper and apply directives**

Add to `scripts/backfill_availability_from_hha.py` (above `main`):

```python
_AVAIL_OPEN_QUERY = (
    "SELECT [ID], [avail_end] FROM [Availability] "
    "WHERE [Center ID] = ? AND [Day Of Week] = ? "
    "AND [effective_end_date] IS NULL"
)

_AVAIL_UPDATE = (
    "UPDATE [Availability] SET [avail_end] = ? WHERE [ID] = ?"
)

_AVAIL_INSERT = (
    "INSERT INTO [Availability] "
    "([Center ID], [effective_start_date], [effective_end_date], "
    "[Day Of Week], [avail_start], [avail_end]) "
    "VALUES (?, ?, NULL, ?, ?, ?)"
)


def _hhmm_to_time(hhmm):
    """Convert 'HH:MM' to a datetime.time. Access stores time-only
    DATETIME fields with a 1899-12-30 placeholder; pyodbc accepts
    datetime.time for that column."""
    h, m = hhmm.split(":")
    return datetime.time(int(h), int(m))


def _apply_clause_to_db(cur, center_id, day, avail_end_hhmm, today,
                        stats):
    """One upsert: find the currently-open Availability row for
    (Center ID, Day Of Week). UPDATE if it exists with a different
    avail_end; INSERT if it doesn't. Tracks earliest-time-wins for
    repeat (day) within one row via the `proposed_ends` map carried
    by the caller (see _apply_row)."""
    new_end_time = _hhmm_to_time(avail_end_hhmm)
    cur.execute(_AVAIL_OPEN_QUERY, str(center_id), day)
    existing = cur.fetchone()
    if existing is not None:
        existing_id, existing_end = existing
        # existing_end is a datetime; compare on time of day.
        existing_end_time = existing_end.time() if hasattr(
            existing_end, "time") else existing_end
        if existing_end_time != new_end_time:
            cur.execute(_AVAIL_UPDATE, new_end_time, int(existing_id))
            stats["updated"] += 1
    else:
        cur.execute(
            _AVAIL_INSERT,
            str(center_id),
            today,
            day,
            _hhmm_to_time("08:00"),
            new_end_time,
        )
        stats["inserted"] += 1


def _apply_row(cur, center_id, parsed, today, stats):
    """For each apply clause, collapse to earliest avail_end per day
    (multi-clause same-day rule), then upsert."""
    by_day = {}  # day -> earliest avail_end HHMM
    for c in parsed["clauses"]:
        if c["status"] != "apply":
            continue
        end_hhmm = c["avail_end"]
        for d in c["days"]:
            current = by_day.get(d)
            if current is None or end_hhmm < current:
                if current is not None:
                    stats["multi_clause_same_day"] += 1
                by_day[d] = end_hhmm
    for d, end_hhmm in by_day.items():
        _apply_clause_to_db(cur, center_id, d, end_hhmm, today, stats)
```

- [ ] **Step 2: Wire `_apply_row` into `main` and add stats**

Replace the body of `main`'s try block:

```python
    try:
        cur = conn.cursor()
        today = datetime.date.today()
        stats = {
            "scanned": 0,
            "ignored": 0,
            "skipped_row": 0,
            "applied": 0,
            "applied_with_ambig_clause": 0,
            "ambiguous": 0,
            "updated": 0,
            "inserted": 0,
            "clauses_after_close": 0,
            "multi_clause_same_day": 0,
        }
        ambiguous_rows = []  # filled in Task 12

        for cid, last, first, hha in _read_contacts(conn):
            stats["scanned"] += 1
            parsed = parse_hha_row(hha)
            if parsed["ignored"]:
                stats["ignored"] += 1
                continue
            stats["clauses_after_close"] += sum(
                1 for c in parsed["clauses"] if c["status"] == "skip"
            )
            if parsed["skipped"]:
                stats["skipped_row"] += 1
                continue
            if parsed["applied"]:
                stats["applied"] += 1
                if parsed["ambiguous"]:
                    stats["applied_with_ambig_clause"] += 1
                _apply_row(cur, cid, parsed, today, stats)
            if parsed["ambiguous"]:
                stats["ambiguous"] += 1
                ambiguous_rows.append({
                    "center_id": cid,
                    "last_name": last or "",
                    "first_name": first or "",
                    "raw_hha": hha,
                    "reason": parsed["ambiguous_reason"] or "",
                    "attempted_parse": parsed["attempted_parse"],
                })
            if not args.quiet:
                tag = ("APPLIED" if parsed["applied"] else
                       "AMBIG" if parsed["ambiguous"] else
                       "SKIPPED")
                print(f"  {tag:8s} {cid}  {hha[:60]!r}")

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        # CSV + summary are added in Tasks 12 and 13.
        print(f"Mode: {mode}")
        print(f"Stats so far: {stats}")
    finally:
        conn.close()
    return 0
```

- [ ] **Step 3: Smoke-test with dry-run**

Run:
```
c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe scripts/backfill_availability_from_hha.py --db scripts/test_dbs/populate_real_members.accdb --dry-run --quiet
```
Expected: prints `Mode: DRY-RUN (no changes committed)` followed by the stats dict. Non-zero values for `applied`, `updated`, and/or `inserted`.

- [ ] **Step 4: Verify nothing was actually written**

Run:
```
c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -c "import pyodbc; conn = pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=scripts/test_dbs/populate_real_members.accdb;'); cur = conn.cursor(); cur.execute('SELECT COUNT(*) FROM [Availability]'); print(cur.fetchone()[0])"
```
Expected: `2262` (the original row count from earlier exploration). If it differs, the rollback didn't take — investigate before continuing.

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_availability_from_hha.py
git commit -m "feat(hha): upsert Availability rows from parsed HHA clauses"
```

---

## Task 12: CLI — Ambiguous CSV writer

**Files:**
- Modify: `scripts/backfill_availability_from_hha.py` — add CSV writer

- [ ] **Step 1: Add the CSV writer and wire it in**

Add to `scripts/backfill_availability_from_hha.py` (above `main`):

```python
_CSV_COLUMNS = [
    "center_id", "last_name", "first_name",
    "raw_hha", "reason", "attempted_parse",
]


def _write_ambiguous_csv(rows, out_dir, today):
    """Write the ambiguous-rows CSV to
    `<out_dir>/hha_backfill_ambiguous_<YYYY-MM-DD>.csv`. Returns the
    path written. Writes the header even if `rows` is empty so the
    file's presence still signals 'a backfill ran on this date'.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir,
        f"hha_backfill_ambiguous_{today.isoformat()}.csv",
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path
```

Then in `main`, right before the `Mode:` print, add:

```python
        csv_path = _write_ambiguous_csv(
            ambiguous_rows, args.csv_out, today,
        )
        stats["csv_path"] = csv_path
```

- [ ] **Step 2: Smoke-test the CSV emission**

Run:
```
c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe scripts/backfill_availability_from_hha.py --db scripts/test_dbs/populate_real_members.accdb --dry-run --csv-out . --quiet
```
Expected:
- File `hha_backfill_ambiguous_<today>.csv` exists in the current directory.
- Open it and confirm it has the expected six columns and at least one data row.

```
c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -c "import csv; print(open('hha_backfill_ambiguous_$(date +%Y-%m-%d).csv', encoding='utf-8-sig').read()[:500])"
```

(On Windows PowerShell, substitute today's date in the filename manually if needed.)

- [ ] **Step 3: Commit**

```bash
git add scripts/backfill_availability_from_hha.py
git commit -m "feat(hha): write ambiguous-rows CSV"
```

---

## Task 13: CLI — Final stdout summary

**Files:**
- Modify: `scripts/backfill_availability_from_hha.py` — pretty-print summary

- [ ] **Step 1: Replace the temporary `Stats so far:` print**

Replace the block:

```python
        print(f"Mode: {mode}")
        print(f"Stats so far: {stats}")
```

with:

```python
        non_empty = stats["scanned"]
        print()
        print("HHA backfill summary")
        print(f"  Contacts scanned (with non-empty HHA): {non_empty}")
        print(f"  Rows ignored (no time):                {stats['ignored']}")
        print(f"  Rows skipped (HHA fully after close):  {stats['skipped_row']}")
        print(
            f"  Rows applied:                          {stats['applied']}"
            f"    (of which {stats['applied_with_ambig_clause']} had "
            "at least one ambiguous clause)"
        )
        print(f"  Rows fully or partially ambiguous:     {stats['ambiguous']}")
        print(f"  Availability rows updated:             {stats['updated']}")
        print(f"  Availability rows inserted:            {stats['inserted']}")
        print(
            f"  Clauses skipped (HHA_start >= 16:00):  "
            f"{stats['clauses_after_close']}"
        )
        print(
            f"  Multi-clause same-day collisions:      "
            f"{stats['multi_clause_same_day']}"
        )
        print(f"  Ambiguous CSV: {stats['csv_path']}")
        print(f"  Mode: {mode}")
```

- [ ] **Step 2: Smoke-test**

Run:
```
c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe scripts/backfill_availability_from_hha.py --db scripts/test_dbs/populate_real_members.accdb --dry-run --csv-out . --quiet
```
Expected: a clean summary block matching the §8 layout in the spec, ending with `Mode: DRY-RUN (no changes committed)`.

- [ ] **Step 3: Commit**

```bash
git add scripts/backfill_availability_from_hha.py
git commit -m "feat(hha): formatted stdout summary at end of run"
```

---

## Task 14: End-to-end manual validation

This task does not write code. It validates the whole script against the real test DB.

- [ ] **Step 1: Dry-run and inspect the CSV**

Run:
```
c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe scripts/backfill_availability_from_hha.py --db scripts/test_dbs/populate_real_members.accdb --dry-run --csv-out .
```

Confirm in the summary:
- `Rows ignored` is non-zero (the day-only and agency-only rows).
- `Rows applied` is the largest bucket.
- `Rows skipped` exists and is non-zero (evening-only HHA rows).
- `Rows ambiguous` is non-zero.
- `Availability rows updated` + `inserted` > 0.
- Avail count still equals the pre-run number after rollback.

Open the CSV (Excel or any tool). Confirm:
- Header row has the six expected columns.
- Each row has a real `center_id`, an English/CJK `raw_hha`, and one of the six known `reason` tags.

- [ ] **Step 2: Spot-check the user's canonical example**

Find center 25012 (`PPL: (4.5.6) 2:30-7pm`) in the per-row output:
```
c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe scripts/backfill_availability_from_hha.py --db scripts/test_dbs/populate_real_members.accdb --dry-run --csv-out . | findstr 25012
```
Expected: shows `APPLIED 25012 'PPL: (4.5.6) 2:30-7pm'`.

- [ ] **Step 3: Live run (only after dry-run output looked correct)**

```
c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe scripts/backfill_availability_from_hha.py --db scripts/test_dbs/populate_real_members.accdb --csv-out .
```
Expected: same summary, but ending with `Mode: APPLIED`.

- [ ] **Step 4: Verify the live run took effect**

```
c:\Users\luald\OneDrive\Desktop\BSCA\.venv\Scripts\python.exe -c "import pyodbc; conn = pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=scripts/test_dbs/populate_real_members.accdb;'); cur = conn.cursor(); cur.execute('SELECT [Center ID], [Day Of Week], [avail_start], [avail_end] FROM [Availability] WHERE [Center ID] = ? AND [effective_end_date] IS NULL ORDER BY [Day Of Week]', '25012'); [print(r) for r in cur.fetchall()]"
```
Expected: three rows for center 25012, days 4, 5, 6, each with avail_end at 14:30.

- [ ] **Step 5: Confirm idempotency**

Re-run the live command from Step 3. Expected: same summary, but `updated` and `inserted` should both be 0 the second time (the table already matches what the parser proposes).

- [ ] **Step 6: Commit (no code changes — just record validation)**

If Steps 1-5 all passed and you produced a useful CSV worth keeping in the repo for reference, optionally:

```bash
git add hha_backfill_ambiguous_<today>.csv  # only if desired
git commit -m "chore(hha): commit reference ambiguous CSV from initial backfill"
```

Otherwise skip the commit. The validation is documented by passing tests + visible run output.

---

## Notes for the implementer

- **Bitness:** This script needs the Microsoft Access ODBC driver to match the Python interpreter's bitness, same as the rest of the project. If you get `IM002` or similar from `pyodbc.connect`, that's the cause.
- **Encoding:** The CSV uses `utf-8-sig` so Excel opens CJK characters correctly. Don't change to plain `utf-8` without checking.
- **No `--apply` flag:** Live mode is the default; `--dry-run` opts out of writes. Matches the spec.
- **DB writes go through one cursor inside one transaction.** pyodbc auto-begins; commit or rollback is explicit at the end. Do not commit inside the loop — that defeats the dry-run rollback.
- **If a parser test feels redundant** with one from an earlier task, keep both. They document expectations for different real-world inputs and the cost is negligible.
