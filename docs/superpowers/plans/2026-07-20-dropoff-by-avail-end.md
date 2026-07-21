# Drop-Off by Availability End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee Drop-Off lands at or before a day's recurring availability end (home care deadline) via a new on-by-default rule, and make the debug CSV show the numbers behind every window decision.

**Architecture:** The eligibility check (`compute_day_eligibility`) reserves the whole transport tail (max time-out drift + max drop-off trail) inside the placement window, so no generation-time change is needed and the time cache invalidates affected days automatically. The debug CSV builder starts using the same travel-adjusted rules as the real run and gains a `reason_detail` column.

**Tech Stack:** Python 3.11, pytest, PyQt6 (settings checkbox), no new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-20-dropoff-by-avail-end-design.md`

---

## Background for the implementer

- The pipeline: `new_monthly_schedule.process_member` → `monthly_schedule/rows.py:build_rows` → `monthly_schedule/per_day.py:compute_day_eligibility` (per day) → `monthly_schedule/daily_schedule.py:build_daily_schedule`.
- Before `build_rows`, `process_member` rewrites `pickup_lead_min`/`dropoff_trail_min` to `(travel + buf_lo, travel + buf_hi)` (see `new_monthly_schedule.py:296-303`). So inside eligibility, `dropoff_trail_min[1]` already equals `travel + max buffer`.
- Drop-Off = Time-Out + `time_out_drift` + `dropoff_trail`. Reserving `time_out_drift_min[1] + dropoff_trail_min[1]` below `avail_end` guarantees Drop-Off ≤ `avail_end` for every random draw.
- The rule applies ONLY to recurring `Availability` rows, only when `avail_end < latest_time_out`, and only when the new rule key `dropoff_by_avail_end` is truthy (default True).
- Run tests with: `python -m pytest tests/<file> -v` from the repo root (venv at `.venv`).

---

### Task 1: Rule key defaults (on by default)

**Files:**
- Modify: `monthly_schedule/rules.py:7-24` (SCHEDULE_RULES)
- Modify: `gui/app_settings.py:15-22` (DEFAULTS["schedule_rules"])
- Test: `tests/test_rules.py`, `tests/test_app_settings.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rules.py`:

```python
def test_dropoff_by_avail_end_defaults_on():
    assert SCHEDULE_RULES["Default"]["dropoff_by_avail_end"] is True


def test_dropoff_by_avail_end_bool_override_passes_through():
    # Booleans must survive the overrides merge untouched (only lists
    # are converted to tuples).
    rules = get_rules_for_plan("Default", {"dropoff_by_avail_end": False})
    assert rules["dropoff_by_avail_end"] is False
```

Append to `tests/test_app_settings.py` (uses the existing `settings_file` fixture):

```python
def test_dropoff_by_avail_end_default_on_fresh_install(settings_file):
    from gui import app_settings
    s = app_settings.load()
    assert s["schedule_rules"]["dropoff_by_avail_end"] is True


def test_dropoff_by_avail_end_missing_key_filled_on(settings_file):
    # A settings file saved before this feature has no key — the loader
    # must fill it from DEFAULTS (i.e., turn it on).
    settings_file.write_text(json.dumps({
        "schedule_rules": {"earliest_time_in": "09:00"}
    }))
    from gui import app_settings
    s = app_settings.load()
    assert s["schedule_rules"]["dropoff_by_avail_end"] is True
    assert s["schedule_rules"]["earliest_time_in"] == "09:00"


def test_dropoff_by_avail_end_saved_false_respected(settings_file):
    settings_file.write_text(json.dumps({
        "schedule_rules": {"dropoff_by_avail_end": False}
    }))
    from gui import app_settings
    s = app_settings.load()
    assert s["schedule_rules"]["dropoff_by_avail_end"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_rules.py tests/test_app_settings.py -v`
Expected: the four new tests FAIL with `KeyError: 'dropoff_by_avail_end'` (existing tests pass).

- [ ] **Step 3: Add the key to both defaults**

In `monthly_schedule/rules.py`, inside `SCHEDULE_RULES["Default"]` after the `travel_buffer_min` line:

```python
        "travel_buffer_min": (1, 5),      # random buffer added to Google travel time
        # When truthy: on days with a RECURRING availability ending
        # before latest_time_out, Drop-Off must land at or before that
        # end (home care starts then). Enforced by shrinking the
        # placement window in per_day.compute_day_eligibility.
        "dropoff_by_avail_end": True,
```

In `gui/app_settings.py`, inside `DEFAULTS["schedule_rules"]` after `"time_out_drift_min": [2, 2],`:

```python
        "time_out_drift_min": [2, 2],
        "dropoff_by_avail_end": True,
```

(The loader's `known`-key filter at `gui/app_settings.py:47` only keeps keys present in DEFAULTS, so this line is what lets the value round-trip — and what turns the feature on for existing installs.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rules.py tests/test_app_settings.py -v`
Expected: all PASS. Note: `test_default_rules_present_and_shaped` does not assert key absence, so it still passes.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/rules.py gui/app_settings.py tests/test_rules.py tests/test_app_settings.py
git commit -m "feat(rules): dropoff_by_avail_end rule key, on by default"
```

---

### Task 2: Eligibility — reserve the transport tail

**Files:**
- Modify: `monthly_schedule/per_day.py:40-106` (DayEligibility + compute_day_eligibility)
- Test: `tests/test_per_day.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_per_day.py`. Note the existing module-level `PLAN_RULES` has no `dropoff_by_avail_end` key (flag off → legacy behavior), which keeps all existing tests green. These tests use a full rules dict:

```python
DEADLINE_RULES = {
    "earliest_time_in": "08:00",
    "latest_time_out": "16:00",
    "session_length_min": (210, 240),
    "time_out_drift_min": (2, 2),
    "dropoff_trail_min": (30, 34),   # travel-adjusted in real runs
    "dropoff_by_avail_end": True,
}

MONDAY_AVAIL_8_TO_15 = {
    "id": 1, "center_id": 1,
    "effective_start_date": date(2026, 1, 1),
    "effective_end_date": None,
    "day_of_week": 1,
    "avail_start": "08:00", "avail_end": "15:00",
}


def test_deadline_shrinks_out_hi_by_reserve():
    # avail_end 15:00 (900) < latest_out 16:00 → reserve = 2 + 34 = 36
    # → out_hi = 900 - 36 = 864 (14:24). Window (480, 864) is 384 min.
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=MONDAY_AVAIL_8_TO_15),
        DEADLINE_RULES,
    )
    assert result.eligible is True
    assert result.placement_window == (480, 864)
    assert result.dropoff_reserve == 36


def test_deadline_off_keeps_legacy_window():
    rules = {**DEADLINE_RULES, "dropoff_by_avail_end": False}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=MONDAY_AVAIL_8_TO_15), rules
    )
    assert result.placement_window == (480, 900)
    assert result.dropoff_reserve == 0


def test_deadline_skipped_when_avail_end_at_day_bound():
    # avail_end == latest_time_out → member has no home care deadline;
    # window unchanged.
    avail = {**MONDAY_AVAIL_8_TO_15, "avail_end": "16:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=avail), DEADLINE_RULES
    )
    assert result.placement_window == (480, 960)
    assert result.dropoff_reserve == 0


def test_deadline_does_not_apply_to_one_off():
    # One-off 08:00-15:00: per the spec, one-offs keep legacy behavior.
    one_off = {"id": 99, "center_id": 1, "date": date(2026, 5, 4),
               "avail_start": "08:00", "avail_end": "15:00"}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(one_offs=[one_off]), DEADLINE_RULES
    )
    assert result.placement_window == (480, 900)
    assert result.dropoff_reserve == 0


def test_deadline_too_narrow_day_blank_with_numbers():
    # avail 08:00-11:30 (690): out_hi = 690 - 36 = 654 → width 174 < 210
    # → ineligible, but the window/reserve are still reported for debug.
    from monthly_schedule.per_day import REASON_DAY_WINDOW_TOO_NARROW
    avail = {**MONDAY_AVAIL_8_TO_15, "avail_end": "11:30"}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=avail), DEADLINE_RULES
    )
    assert result.eligible is False
    assert result.reason == REASON_DAY_WINDOW_TOO_NARROW
    assert result.placement_window == (480, 654)
    assert result.dropoff_reserve == 36


def test_legacy_too_narrow_also_reports_window():
    # Flag absent (module PLAN_RULES): the too-narrow rejection now
    # carries the window it computed instead of None.
    avail = {"id": 1, "center_id": 1,
             "effective_start_date": date(2026, 1, 1),
             "effective_end_date": None,
             "day_of_week": 1,
             "avail_start": "12:00", "avail_end": "13:30"}
    result = compute_day_eligibility(
        date(2026, 5, 4), _ctx(availability=avail), PLAN_RULES
    )
    assert result.eligible is False
    assert result.placement_window == (720, 810)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_per_day.py -v`
Expected: new tests FAIL (`dropoff_reserve` attribute missing / window is None or unshrunk). Existing tests PASS.

- [ ] **Step 3: Implement**

In `monthly_schedule/per_day.py`, extend the dataclass (replace the existing `DayEligibility` body, keeping its docstring and adding to it):

```python
@dataclass(frozen=True)
class DayEligibility:
    """Result of a single-day eligibility check.

    `placement_window` is (in_lo, out_hi) in minutes — the earliest
    allowed Time-In and latest allowed Time-Out for the day, after
    intersecting the plan's day bounds with the member's availability
    (and, when `dropoff_by_avail_end` applies, subtracting the
    drop-off reserve). It is None when no availability rule applies
    (the open day: the generator falls back to the plan's full day
    bounds). Unlike before, it IS populated on a too-narrow rejection
    so the debug CSV can show the numbers.
    `reason` is None when eligible=True, otherwise one of the
    REASON_DAY_* constants explaining the rejection (used by the debug
    CSV).
    `dropoff_reserve` is the minutes subtracted from avail_end to keep
    Drop-Off at or before it (max time-out drift + max drop-off
    trail); 0 when the deadline did not apply.
    """
    eligible: bool
    placement_window: Optional[Tuple[int, int]] = None
    reason: Optional[str] = None
    dropoff_reserve: int = 0
```

Replace the window computation at the end of `compute_day_eligibility` (currently lines 92-106) with:

```python
    earliest_in = parse_hhmm(plan_rules["earliest_time_in"])
    latest_out = parse_hhmm(plan_rules["latest_time_out"])
    avail_lo = parse_hhmm(avail["avail_start"])
    avail_hi = parse_hhmm(avail["avail_end"])
    length_min = plan_rules["session_length_min"][0]

    # Placement window: the member's availability clipped to the hard
    # day bounds (Time-In >= earliest, Time-Out <= latest).
    in_lo = max(earliest_in, avail_lo)
    out_hi = min(latest_out, avail_hi)
    # Home-care deadline: recurring availability ending before the day
    # bound means home care starts at avail_end, so the whole transport
    # tail (drift + drive + buffer) must fit before it. Reserving the
    # maximum of each random range guarantees Drop-Off <= avail_end for
    # any draw. One-off rows are exempt (user decision, spec 2026-07-20).
    reserve = 0
    if (plan_rules.get("dropoff_by_avail_end")
            and not one_offs and avail_hi < latest_out):
        reserve = (plan_rules["time_out_drift_min"][1]
                   + plan_rules["dropoff_trail_min"][1])
        out_hi = avail_hi - reserve
    if out_hi - in_lo < length_min:
        return DayEligibility(
            eligible=False, reason=REASON_DAY_WINDOW_TOO_NARROW,
            placement_window=(in_lo, out_hi), dropoff_reserve=reserve,
        )
    return DayEligibility(
        eligible=True, placement_window=(in_lo, out_hi),
        dropoff_reserve=reserve,
    )
```

(`one_offs` is already in scope from the earlier branch; empty list ⇒ recurring row.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_per_day.py tests/test_rows.py -v`
Expected: all PASS (`build_rows` only reads `placement_window` on eligible days, so populating it on rejection is inert there).

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/per_day.py tests/test_per_day.py
git commit -m "feat(per_day): reserve transport tail so drop-off meets avail_end"
```

---

### Task 3: End-to-end guarantee test (property test)

**Files:**
- Test: `tests/test_rows.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_rows.py` (add `import random` and `from monthly_schedule.rules import parse_hhmm` to the module imports if not present; `MemberContext` and `build_rows` are already imported there):

```python
DEADLINE_E2E_RULES = {
    "earliest_time_in": "08:00",
    "latest_time_out": "16:00",
    "session_length_min": (210, 240),
    "pickup_lead_min": (26, 30),      # travel 25 + buffer 1-5
    "dropoff_trail_min": (26, 30),
    "time_in_drift_min": (2, 2),
    "time_out_drift_min": (2, 2),
    "round_to_minutes": 1,
    "dropoff_by_avail_end": True,
}


def _deadline_ctx():
    return MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1"}],
        absences=[],
        availabilities=[{"id": 1, "center_id": 1,
                         "effective_start_date": date(2026, 1, 1),
                         "effective_end_date": None,
                         "day_of_week": 1,
                         "avail_start": "08:00", "avail_end": "15:00"}],
        one_offs=[],
    )


def test_dropoff_never_past_avail_end_across_seeds():
    # The guarantee the whole feature rests on: for ANY random draw,
    # Drop-Off <= avail_end on recurring-availability days.
    deadline = parse_hhmm("15:00")
    ctx = _deadline_ctx()
    for seed in range(50):
        rows = build_rows(2026, 5, ctx, DEADLINE_E2E_RULES,
                          random.Random(seed))
        scheduled = [r for r in rows if r["dropoff"]]
        assert scheduled, "expected Mondays to be scheduled"
        for r in scheduled:
            assert parse_hhmm(r["dropoff"]) <= deadline, (
                f"seed {seed} {r['date']}: dropoff {r['dropoff']} "
                f"past 15:00"
            )
            # Full session still granted when the window allows it.
            length = parse_hhmm(r["time_out"]) - parse_hhmm(r["time_in"])
            assert 210 <= length <= 240
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/test_rows.py::test_dropoff_never_past_avail_end_across_seeds -v`
Expected: PASS (Task 2 already implemented the mechanism; this is a regression fence, not a red-first test).

- [ ] **Step 3: Commit**

```bash
git add tests/test_rows.py
git commit -m "test(rows): property test — dropoff never past avail_end"
```

---

### Task 4: Debug rows — numbers behind every window decision

**Files:**
- Modify: `monthly_schedule/rows.py:79-164` (build_debug_rows)
- Modify: `new_monthly_schedule.py:79-111` (write_debug_csv)
- Test: `tests/test_rows.py`, `tests/test_cli.py` (only if its debug-CSV header assertions break)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rows.py` (`build_debug_rows` is already imported in that module; if not, add it):

```python
def test_debug_too_narrow_day_has_window_and_detail():
    # avail 08:00-11:30, reserve 2+34=36 → usable 08:00-10:54 (2h54m),
    # under the 3h30m minimum.
    rules = {**DEADLINE_E2E_RULES,
             "dropoff_trail_min": (30, 34)}
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1"}],
        absences=[],
        availabilities=[{"id": 1, "center_id": 1,
                         "effective_start_date": date(2026, 1, 1),
                         "effective_end_date": None,
                         "day_of_week": 1,
                         "avail_start": "08:00", "avail_end": "11:30"}],
        one_offs=[],
    )
    rows = build_debug_rows(2026, 5, ctx, rules)
    assert rows, "expected one row per authorized Monday"
    row = rows[0]
    assert row["scheduled"] is False
    assert row["placement_window"] == "08:00-10:54"
    assert row["max_length"] == "02:54"
    assert row["reason_detail"] == (
        "avail 08:00-11:30 minus 36m drop-off reserve -> "
        "usable 08:00-10:54 (2h54m) < min 3h30m"
    )


def test_debug_eligible_day_notes_reserve():
    rules = {**DEADLINE_E2E_RULES, "dropoff_trail_min": (30, 34)}
    ctx = _deadline_ctx()  # avail 08:00-15:00 → reserve 36, eligible
    rows = build_debug_rows(2026, 5, ctx, rules)
    row = rows[0]
    assert row["scheduled"] is True
    assert row["placement_window"] == "08:00-14:24"
    assert row["reason_detail"] == (
        "drop-off reserve 36m before 15:00 avail end"
    )


def test_debug_too_narrow_without_deadline_shows_width():
    # Legacy narrow window (12:00-13:30, no deadline): detail carries
    # the arithmetic that used to be invisible.
    rules = {**DEADLINE_E2E_RULES, "dropoff_by_avail_end": False}
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1"}],
        absences=[],
        availabilities=[{"id": 1, "center_id": 1,
                         "effective_start_date": date(2026, 1, 1),
                         "effective_end_date": None,
                         "day_of_week": 1,
                         "avail_start": "12:00", "avail_end": "13:30"}],
        one_offs=[],
    )
    rows = build_debug_rows(2026, 5, ctx, rules)
    row = rows[0]
    assert row["scheduled"] is False
    assert row["placement_window"] == "12:00-13:30"
    assert row["reason_detail"] == "usable 12:00-13:30 (1h30m) < min 3h30m"


def test_debug_open_day_has_empty_detail():
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1"}],
        absences=[], availabilities=[], one_offs=[],
    )
    rows = build_debug_rows(2026, 5, ctx, DEADLINE_E2E_RULES)
    assert rows[0]["scheduled"] is True
    assert rows[0]["reason_detail"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_rows.py -v -k debug`
Expected: new tests FAIL with `KeyError: 'reason_detail'`.

- [ ] **Step 3: Implement in `monthly_schedule/rows.py`**

Add a helper above `build_debug_rows` and import the reason constant (extend the existing `monthly_schedule.per_day` import):

```python
from monthly_schedule.per_day import (
    compute_day_eligibility, OneOffConflict, REASON_DAY_WINDOW_TOO_NARROW,
)


def _fmt_duration(minutes):
    """126 -> '2h06m' (durations in the debug reason_detail column)."""
    minutes = max(0, minutes)
    return f"{minutes // 60}h{minutes % 60:02d}m"
```

In `build_debug_rows`, capture the reserve in the try/except (replace the existing block):

```python
        try:
            result = compute_day_eligibility(day, ctx, plan_rules)
            scheduled = result.eligible
            reason = "" if scheduled else (result.reason or "")
            window = result.placement_window
            reserve = result.dropoff_reserve
        except OneOffConflict as exc:
            scheduled = False
            reason = exc.reason
            window = None
            reserve = 0
```

Replace the `if window is not None:` formatting block (keep the preceding open-day fallback) with:

```python
        reason_detail = ""
        if window is not None:
            in_lo, out_hi = window
            placement = f"{format_minutes(in_lo)}-{format_minutes(out_hi)}"
            max_len = max(0, min(plan_rules["session_length_min"][1],
                                 out_hi - in_lo))
            max_length = format_minutes(max_len)
            usable = (f"usable {placement} "
                      f"({_fmt_duration(out_hi - in_lo)})")
            if reason == REASON_DAY_WINDOW_TOO_NARROW:
                min_len = plan_rules["session_length_min"][0]
                prefix = (
                    f"avail {availability} minus {reserve}m "
                    f"drop-off reserve -> " if reserve else ""
                )
                reason_detail = (
                    f"{prefix}{usable} < min {_fmt_duration(min_len)}"
                )
            elif reserve:
                reason_detail = (
                    f"drop-off reserve {reserve}m before "
                    f"{avail_row['avail_end']} avail end"
                )
        else:
            placement = ""
            max_length = ""
```

Add the field to the appended row dict, after `"reason": reason,`:

```python
            "reason": reason,
            "reason_detail": reason_detail,
```

- [ ] **Step 4: Implement in `new_monthly_schedule.py` `write_debug_csv`**

Header list becomes:

```python
        writer.writerow([
            "center_id", "name", "date", "day", "scheduled", "reason",
            "reason_detail", "availability", "availability_source",
            "absent", "auth_days", "placement_window", "max_length",
        ])
```

And in the row loop, after `row["reason"],`:

```python
                row["reason"],
                row["reason_detail"],
```

Also update the docstring's key list to include `reason_detail`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_rows.py tests/test_cli.py -v`
Expected: new tests PASS. If any `test_cli.py` assertion pins the debug CSV header row, update it to include `reason_detail` in the same position as above.

- [ ] **Step 6: Commit**

```bash
git add monthly_schedule/rows.py new_monthly_schedule.py tests/test_rows.py tests/test_cli.py
git commit -m "feat(debug): reason_detail column + windows for rejected days"
```

---

### Task 5: Debug rows use the run's travel-adjusted rules

**Files:**
- Modify: `new_monthly_schedule.py:272-314` (process_member) and `:114-129` (collect_debug_rows)
- Modify: `gui/worker.py:199-204` (collect_debug_rows call)
- Modify: `new_monthly_schedule.py:412-416` (CLI collect_debug_rows call)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py` (it already imports `new_monthly_schedule as cli`-style module access and monkeypatches `resolve_travel_minutes` — follow the file's existing import conventions):

```python
def test_collect_debug_rows_uses_travel_adjusted_offsets(monkeypatch):
    import new_monthly_schedule as cli
    from datetime import date
    from monthly_schedule.eligibility_context import MemberContext

    monkeypatch.setattr(cli, "resolve_travel_minutes",
                        lambda member, api_key, cache: 25)
    member = {"center_id": 1, "first_name": "A", "last_name": "B",
              "health_plan": None, "address": "1 Main St",
              "long_lat": "40.0,-73.0"}
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1"}],
        absences=[],
        availabilities=[{"id": 1, "center_id": 1,
                         "effective_start_date": date(2026, 1, 1),
                         "effective_end_date": None,
                         "day_of_week": 1,
                         "avail_start": "08:00", "avail_end": "15:00"}],
        one_offs=[],
    )
    rows = cli.collect_debug_rows(member, ctx, 2026, 5,
                                  api_key="K", cache={})
    # travel 25 + buffer max 5 + drift max 2 = 32 min reserve
    # → out_hi = 15:00 - 32m = 14:28 (default rules, flag on).
    assert rows[0]["placement_window"] == "08:00-14:28"
    assert rows[0]["reason_detail"] == (
        "drop-off reserve 32m before 15:00 avail end"
    )


def test_collect_debug_rows_without_cache_uses_defaults(monkeypatch):
    import new_monthly_schedule as cli
    from datetime import date
    from monthly_schedule.eligibility_context import MemberContext

    def boom(member, api_key, cache):
        raise AssertionError("must not resolve travel without a cache")
    monkeypatch.setattr(cli, "resolve_travel_minutes", boom)
    member = {"center_id": 1, "first_name": "A", "last_name": "B",
              "health_plan": None}
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1"}],
        absences=[],
        availabilities=[{"id": 1, "center_id": 1,
                         "effective_start_date": date(2026, 1, 1),
                         "effective_end_date": None,
                         "day_of_week": 1,
                         "avail_start": "08:00", "avail_end": "15:00"}],
        one_offs=[],
    )
    rows = cli.collect_debug_rows(member, ctx, 2026, 5)
    # Default offsets: drift max 2 + dropoff trail max 12 = 14 min.
    assert rows[0]["placement_window"] == "08:00-14:46"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v -k collect_debug`
Expected: FAIL — `collect_debug_rows() got an unexpected keyword argument 'api_key'`.

- [ ] **Step 3: Extract the shared helper and rewire**

In `new_monthly_schedule.py`, add above `process_member`:

```python
def apply_travel_offsets(rules, travel_minutes):
    """Return a copy of `rules` with pickup/drop-off offsets rebuilt
    from the member's drive time plus the configured travel buffer.
    This is the single place the travel -> offsets mapping lives, so
    the schedule run and the debug CSV can never disagree."""
    rules = dict(rules)
    buf_lo, buf_hi = rules.get("travel_buffer_min", (5, 15))
    rules["pickup_lead_min"] = (travel_minutes + buf_lo,
                                travel_minutes + buf_hi)
    rules["dropoff_trail_min"] = (travel_minutes + buf_lo,
                                  travel_minutes + buf_hi)
    return rules
```

In `process_member`, replace lines 296-303 with:

```python
        rules = apply_travel_offsets(
            get_rules_for_plan(
                member["health_plan"], schedule_rules_overrides
            ),
            travel_minutes,
        )
```

Replace `collect_debug_rows` with:

```python
def collect_debug_rows(member, ctx, year, month,
                       start_day=None, end_day=None,
                       schedule_rules_overrides=None,
                       api_key=None, cache=None):
    """Build the run-level debug rows for one member: each row from
    build_debug_rows annotated with center_id + 'Last, First' name.

    When `cache` is given, the same travel-adjusted pickup/drop-off
    offsets as the real run are used (a geo-cache hit in practice), so
    the CSV's placement windows match what was scheduled. On travel
    failure the built-in offsets are kept — the member fails the run
    anyway, and the eligibility columns are still useful."""
    from monthly_schedule.rules import get_rules_for_plan
    rules = dict(get_rules_for_plan(
        member["health_plan"], schedule_rules_overrides
    ))
    if cache is not None:
        try:
            travel_minutes = resolve_travel_minutes(member, api_key, cache)
            rules = apply_travel_offsets(rules, travel_minutes)
        except TravelError:
            pass
    name = f"{member['last_name']}, {member['first_name']}"
    return [
        {"center_id": member["center_id"], "name": name, **r}
        for r in build_debug_rows(
            year, month, ctx, rules, start_day, end_day
        )
    ]
```

- [ ] **Step 4: Update both callers**

`gui/worker.py:200-204`:

```python
                    member_debug_rows = collect_debug_rows(
                        member, ctx, self.year, self.month,
                        self.start_day, self.end_day,
                        schedule_rules_overrides=self.schedule_rules,
                        api_key=api_key, cache=cache,
                    )
```

`new_monthly_schedule.py:413-416` (CLI main loop — `api_key` and `cache` are in scope, they're passed to `process_member` a few lines below):

```python
            member_debug_rows = collect_debug_rows(
                member, ctx, args.year, args.month,
                args.start_day, args.end_day,
                api_key=api_key, cache=cache,
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py tests/test_schedule_worker.py tests/test_smoke.py -v`
Expected: PASS. If a worker/smoke test stubs `collect_debug_rows`, keep its signature compatible (new kwargs default to None).

- [ ] **Step 6: Commit**

```bash
git add new_monthly_schedule.py gui/worker.py tests/test_cli.py
git commit -m "fix(debug): debug CSV uses the run's travel-adjusted offsets"
```

---

### Task 6: Settings checkbox (GUI + i18n)

**Files:**
- Modify: `gui/settings_dialog.py:291-296` (build), `:334-340` (_retranslate), `:383-420` (_save)
- Modify: `gui/i18n.py` (en block near line 89, zh block near line 274)
- Test: `tests/test_i18n.py` (only if it enumerates keys — it checks en/zh parity automatically)

- [ ] **Step 1: Add i18n keys**

In `gui/i18n.py`, English block after the `settings.rules.time_out` entry:

```python
        "settings.rules.dropoff_deadline": (
            "Drop off by availability end (home care):"
        ),
```

Chinese block after its `settings.rules.time_out` entry:

```python
        "settings.rules.dropoff_deadline": (
            "在可用时间结束前送回（家庭护理）："
        ),
```

- [ ] **Step 2: Add the checkbox**

In `gui/settings_dialog.py`, add `QCheckBox` to the existing `PyQt6.QtWidgets` import list. Then after the `time_out` row block (line 294):

```python
        self._dropoff_deadline_check = QCheckBox()
        self._dropoff_deadline_check.setChecked(
            bool(rules.get("dropoff_by_avail_end", True))
        )
        self._dropoff_deadline_label = QLabel()
        rules_form.addRow(self._dropoff_deadline_label,
                          self._dropoff_deadline_check)
```

In `_retranslate` after the `time_out` label line:

```python
        self._dropoff_deadline_label.setText(
            tr("settings.rules.dropoff_deadline")
        )
```

In `_save`, inside the `"schedule_rules"` dict after `"time_out_drift_min": list(time_out),`:

```python
                "dropoff_by_avail_end":
                    self._dropoff_deadline_check.isChecked(),
```

- [ ] **Step 3: Run the GUI test suites**

Run: `python -m pytest tests/test_i18n.py tests/test_schedule_worker.py -v`
Expected: PASS (i18n parity check sees the key in both languages). If a settings-dialog test constructs the dialog and asserts saved keys, extend its expected dict with `"dropoff_by_avail_end": True`.

- [ ] **Step 4: Commit**

```bash
git add gui/settings_dialog.py gui/i18n.py
git commit -m "feat(gui): drop-off-by-availability-end checkbox in Scheduling Rules"
```

---

### Task 7: Update the scheduling docs

**Files:**
- Modify: `docs/scheduling-flow.md`
- Modify: `docs/time-calculation-overview.md`

- [ ] **Step 1: `docs/scheduling-flow.md`**

In the mermaid flow, replace the node `I` text so the width check mentions the deadline:

```
    H --> I{Day bounds 08:00-16:00<br/>intersected with avail,<br/>minus drop-off reserve when<br/>avail ends early — at least<br/>3h30m wide?}
```

In the **Clock-time attributes** glossary table, update the Placement window row and add one row after it:

```markdown
| **Placement window** `(in_lo, out_hi)` | The overlap of the two pairs above: `in_lo = max(earliest_time_in, avail_start)`, `out_hi = min(latest_time_out, avail_end)`. With **Drop off by availability end** on (the default), a recurring availability ending before 16:00 further lowers `out_hi` by the drop-off reserve. The whole attendance block (Time-In → Time-Out) must fit inside it. If the member has no availability row, the window is simply 08:00–16:00 (an "open day"). |
| **Drop-off reserve** | Minutes subtracted from an early `avail_end` so the whole ride home fits before home care starts: max Time-Out drift (2) + drive time + max travel buffer (5). Applies only to recurring availability, only when the **Drop off by availability end** checkbox (Settings → Scheduling Rules, on by default) is checked. Guarantees Drop-Off ≤ `avail_end`. One-off rows are exempt. |
```

In "The six generated times" section, replace the sentence "Only Time-In and Time-Out are constrained by the placement window; the transport times deliberately spill just outside it." with:

```markdown
Only Time-In and Time-Out are constrained by the placement window. With
**Drop off by availability end** off, the transport times deliberately
spill just outside it; with it on (the default), days whose recurring
availability ends before 16:00 reserve the whole transport tail inside
the window, so Drop-Off lands at or before `avail_end`.
```

In the final Debug paragraph, mention the new column: after "which of these checks made it ineligible (or `yes` if it was scheduled)," insert "a `reason_detail` column with the arithmetic behind window rejections (availability, drop-off reserve, usable width vs. required minimum),".

- [ ] **Step 2: `docs/time-calculation-overview.md`**

Add a row to the rules table after `round_to_minutes`:

```markdown
| `dropoff_by_avail_end` | on | When a recurring availability ends before `latest_time_out`, shrink the window so Drop-Off lands at or before `avail_end` (home care). Day goes blank if under 3h30m. |
```

In §3's placement-window sentence, after "intersected with the member's availability" add: "— minus the drop-off reserve (max drift + drive time + max buffer) when `dropoff_by_avail_end` applies".

- [ ] **Step 3: Commit**

```bash
git add docs/scheduling-flow.md docs/time-calculation-overview.md
git commit -m "docs: document drop-off-by-avail-end rule and debug details"
```

---

### Task 8: Full-suite verification

**Files:**
- Possibly modify: any test whose fixtures assumed the legacy window with default rules

- [ ] **Step 1: Run the entire suite**

Run: `python -m pytest -q`
Expected: PASS. Watch specifically `tests/test_smoke.py`, `tests/test_cli.py`, `tests/test_schedule_worker.py`, `tests/test_printing.py` — any fixture with a recurring availability ending before 16:00 that runs through `get_rules_for_plan` defaults now gets a shrunken window.

- [ ] **Step 2: Fix fallout, if any**

For each failure, decide which side is wrong:
- If the test pinned exact generated times or window bounds under the old behavior → update the expectation to the new (shrunken) window; the new numbers must satisfy `dropoff ≤ avail_end`.
- If the test intends to exercise legacy behavior explicitly → add `"dropoff_by_avail_end": False` to that test's rules dict.
- Never "fix" a failure by weakening Task 3's guarantee test.

- [ ] **Step 3: Commit (only if fixes were needed)**

```bash
git add tests/
git commit -m "test: adjust fixtures for dropoff_by_avail_end default-on"
```
