# Time-Generation Rules Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw Arrival uniformly in 08:00–11:00, derive Departure = Arrival + a random 210–245-minute span, and pin Time-In = Arrival+2 / Time-Out = Departure−2.

**Architecture:** `monthly_schedule/rules.py` (the `Default` rule set) and `monthly_schedule/daily_schedule.py` (`build_daily_schedule` + `validate_schedule`) change together — they are mutually dependent (the algorithm reads the rule keys), so they're one atomic task. Tests in `tests/test_rules.py` and `tests/test_daily_schedule.py` are updated first (TDD). A second task refreshes the now-stale overview doc and verifies end-to-end.

**Tech Stack:** Python 3, pytest. Tests run from repo root with `python -m pytest`. Windows, `python`.

**Spec:** `docs/superpowers/specs/2026-05-18-time-rules-update-design.md`

---

## File Structure

| File | Change |
|------|--------|
| `monthly_schedule/rules.py` | `Default`: `arrival_window=("08:00","11:00")`, add `session_span_min=(210,245)`, `time_in_drift_min`/`time_out_drift_min`=`(2,2)`; remove `departure_window`, `min_session_hours`, `max_session_hours`. `get_rules_for_plan`/`parse_hhmm`/`format_minutes` unchanged. |
| `monthly_schedule/daily_schedule.py` | `build_daily_schedule`: `departure = arrival + rng.randint(*session_span_min)` (no `departure_window`). `validate_schedule`: session check uses `session_span_min` minutes instead of `min/max_session_hours`. Ordering checks unchanged. `_round_to` unchanged. |
| `tests/test_rules.py` | Rewrite `test_default_rules_present_and_shaped` for the new shape. |
| `tests/test_daily_schedule.py` | Strengthen `test_default_rules_produce_valid_ordering`; rewrite the tight-window/snap test for new keys; fix one stale comment. Other tests unchanged. |
| `docs/time-calculation-overview.md` | Update the rule table + algorithm description to the new model (Task 2). |

No other files reference the removed keys (verified in Task 1 Step 2).

---

## Task 1: New rule set + generation algorithm (atomic) + tests

**Files:**
- Modify: `monthly_schedule/rules.py`
- Modify: `monthly_schedule/daily_schedule.py`
- Modify: `tests/test_rules.py`
- Modify: `tests/test_daily_schedule.py`

- [ ] **Step 1: Update the tests first (failing)**

In `tests/test_rules.py`, replace the entire `test_default_rules_present_and_shaped` function with:

```python
def test_default_rules_present_and_shaped():
    d = SCHEDULE_RULES["Default"]
    assert d["arrival_window"] == ("08:00", "11:00")
    assert d["session_span_min"] == (210, 245)
    assert d["time_in_drift_min"] == (2, 2)
    assert d["time_out_drift_min"] == (2, 2)
    assert d["pickup_lead_min"] == (8, 12)
    assert d["dropoff_trail_min"] == (8, 12)
    assert d["round_to_minutes"] == 1
    assert "departure_window" not in d
    assert "min_session_hours" not in d
    assert "max_session_hours" not in d
```

In `tests/test_daily_schedule.py`, replace the entire `test_default_rules_produce_valid_ordering` function with:

```python
def test_default_rules_produce_valid_ordering():
    rng = random.Random(42)
    for _ in range(200):
        s = build_daily_schedule(SCHEDULE_RULES["Default"], rng)
        pu = _to_min(s["pickup"])
        ar = _to_min(s["arrival"])
        ti = _to_min(s["time_in"])
        to = _to_min(s["time_out"])
        de = _to_min(s["departure"])
        do = _to_min(s["dropoff"])
        assert 8 * 60 <= ar <= 11 * 60          # Arrival 08:00-11:00
        assert 210 <= de - ar <= 245            # span 3h30m-4h5m
        assert ti == ar + 2                     # Time-In = Arrival+2
        assert to == de - 2                     # Time-Out = Departure-2
        assert pu < ar <= ti
        assert to <= de < do
```

In `tests/test_daily_schedule.py`, replace the entire `test_tight_window_with_5_minute_snap` function with:

```python
def test_arrival_snapped_with_5_minute_step():
    rng = random.Random(7)
    rules = {
        "arrival_window": ("08:02", "08:58"),
        "session_span_min": (210, 245),
        "pickup_lead_min": (8, 12),
        "dropoff_trail_min": (8, 12),
        "time_in_drift_min": (2, 2),
        "time_out_drift_min": (2, 2),
        "round_to_minutes": 5,
    }
    for _ in range(100):
        s = build_daily_schedule(rules, rng)
        ar = _to_min(s["arrival"])
        de = _to_min(s["departure"])
        assert ar % 5 == 0
        assert 210 <= de - ar <= 245
        assert _to_min(s["pickup"]) < ar
        assert de < _to_min(s["dropoff"])
```

In `tests/test_daily_schedule.py`, in `test_validate_schedule_raises_on_session_length`, replace the comment line
`        # 30-minute session, below min_session_hours`
with
`        # 30-minute span, below session_span_min lower bound (210)`
(leave the `validate_schedule(470, 480, 480, 510, 510, 520, rules)` call exactly as is).

Leave `test_keys_present`, `test_validate_schedule_raises_on_bad_ordering`, and `test_validate_schedule_raises_on_time_in_after_time_out` unchanged.

- [ ] **Step 2: Run tests to verify they fail, and confirm no stray references**

Run: `python -m pytest tests/test_rules.py tests/test_daily_schedule.py -q`
Expected: FAIL — `test_default_rules_present_and_shaped` fails on the old `("08:05","08:25")` values; `test_default_rules_produce_valid_ordering` fails (old `time_in`/span don't satisfy the new asserts); `test_arrival_snapped_with_5_minute_step` errors with `KeyError: 'departure_window'` (old `build_daily_schedule` reads `departure_window`, absent from the new custom rules).

Also confirm nothing outside the two source files reads the removed keys:

Run: `python -m pytest -q` then, using the Grep tool (or `git grep`), search the repo for `departure_window`, `min_session_hours`, `max_session_hours`.
Expected: matches ONLY in `monthly_schedule/rules.py`, `monthly_schedule/daily_schedule.py`, `tests/test_*.py`, and `docs/` — no references in `rows.py`, `workbook.py`, `eligibility.py`, `new_monthly_schedule.py`, or `db.py`. (If any appear there, STOP and report — the spec assumed only the two source files use these.)

- [ ] **Step 3: Update `monthly_schedule/rules.py`**

Replace the entire `SCHEDULE_RULES` assignment (the `SCHEDULE_RULES = { ... }` block) with:

```python
SCHEDULE_RULES = {
    "Default": {
        "arrival_window": ("08:00", "11:00"),
        "session_span_min": (210, 245),   # Departure = Arrival + span (min)
        "pickup_lead_min": (8, 12),       # minutes before Arrival
        "dropoff_trail_min": (8, 12),     # minutes after Departure
        "time_in_drift_min": (2, 2),      # Time-In = Arrival + 2 min
        "time_out_drift_min": (2, 2),     # Time-Out = Departure - 2 min
        "round_to_minutes": 1,            # 1 = no snap; 5 = snap to :05
    },
}
```

Leave `get_rules_for_plan`, `parse_hhmm`, `format_minutes`, and the module docstring unchanged.

- [ ] **Step 4: Update `monthly_schedule/daily_schedule.py`**

Replace the entire `build_daily_schedule` function with:

```python
def build_daily_schedule(rules, rng):
    """Return a dict of 'HH:MM' strings for one eligible day's visit."""
    a_lo, a_hi = (parse_hhmm(x) for x in rules["arrival_window"])
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

In `validate_schedule`, replace this block:

```python
    session_hours = (departure - arrival) / 60
    lo = rules["min_session_hours"]
    hi = rules["max_session_hours"]
    if not (lo <= session_hours <= hi):
        raise ValueError(
            f"Session length {session_hours}h outside [{lo}, {hi}]"
        )
```

with:

```python
    span = departure - arrival
    lo, hi = rules["session_span_min"]
    if not (lo <= span <= hi):
        raise ValueError(
            f"Session span {span} min outside [{lo}, {hi}]"
        )
```

Leave the three ordering checks (start / mid / end) and `_round_to` and the module docstring unchanged.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_rules.py tests/test_daily_schedule.py -q`
Expected: PASS (all rules + daily_schedule tests).

Then run the full suite: `python -m pytest -q`
Expected: ALL pass (no regressions — eligibility/rows/workbook/cli/db do not depend on these keys).

- [ ] **Step 6: Commit**

```bash
git add monthly_schedule/rules.py monthly_schedule/daily_schedule.py tests/test_rules.py tests/test_daily_schedule.py
git commit -m "feat: arrival 08:00-11:00, departure = arrival + 210-245min span"
```

---

## Task 2: Refresh overview doc + full-suite + manual e2e

**Files:**
- Modify: `docs/time-calculation-overview.md`

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`
Expected: ALL pass.

- [ ] **Step 2: Update `docs/time-calculation-overview.md`**

Replace section **"## 2. The rule set"** (the heading line through the end of its Markdown table, i.e. up to but not including "## 3. Generating one day") with:

```markdown
## 2. The rule set

`monthly_schedule/rules.py` holds `SCHEDULE_RULES`, keyed by Health
Plan with a `"Default"` entry used when the plan has no specific
override (`get_rules_for_plan`). Current `Default` values:

| Rule | Value | Meaning |
|------|-------|---------|
| `arrival_window` | 08:00–11:00 | Arrival drawn uniformly in this range |
| `session_span_min` | 210–245 min | Departure = Arrival + a random span in this range (3 h 30 m – 4 h 5 m) |
| `pickup_lead_min` | 8–12 min | Pick-Up is this many minutes **before** Arrival |
| `dropoff_trail_min` | 8–12 min | Drop-Off is this many minutes **after** Departure |
| `time_in_drift_min` | (2, 2) | Time-In is exactly 2 minutes **after** Arrival |
| `time_out_drift_min` | (2, 2) | Time-Out is exactly 2 minutes **before** Departure |
| `round_to_minutes` | 1 | Snap step for Arrival (1 = no snap; 5 = snap to :05) |
```

Then replace section **"## 3. Generating one day (`daily_schedule.build_daily_schedule`)"** (heading through the end of its numbered list, up to but not including "## 4.") with:

```markdown
## 3. Generating one day (`daily_schedule.build_daily_schedule`)

**Arrival** is the single anchor; **Departure** is derived from it:

1. **Arrival** = random minute in `arrival_window` (08:00–11:00),
   snapped by `round_to_minutes`.
2. **Span** = random minute count in `session_span_min` (210–245).
3. **Departure** = Arrival + Span (max possible 11:00 + 4 h 5 m =
   15:05).
4. Derived (exact offsets):
   - **Pick-Up** = Arrival − random(`pickup_lead_min`)
   - **Time-In** = Arrival + 2
   - **Time-Out** = Departure − 2
   - **Drop-Off** = Departure + random(`dropoff_trail_min`)

Randomness comes from an injected `random.Random` instance, so a
given seed reproduces the same schedule (used in tests).
```

Then, in section **"## 4. Invariant check (`validate_schedule`)"**, replace the line
`min_session_hours ≤ (Departure − Arrival) ≤ max_session_hours`
with
`session_span_min[0] ≤ (Departure − Arrival) ≤ session_span_min[1]   (210–245 min)`
and replace the sentence beginning "With the `Default` rules these always hold (e.g. Pick-Up is at least 8 min before Arrival, session span is ~3.7–4.3 h, inside 3–6 h)." with:
"With the `Default` rules these always hold: Pick-Up is ≥ 8 min before Arrival, Drop-Off ≥ 8 min after Departure, and the span is drawn directly within 210–245 min so the session check cannot fail."

Leave sections 1, 5, and "Key files" unchanged.

- [ ] **Step 3: Manual end-to-end against the live DB**

Run:
`python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5 --preview-data`

Expected: authorized days (Mon/Wed/Thu/Fri per `1.3.4.5`) show `arrival` between `08:00` and `11:00`, `departure` = arrival + roughly 3 h 30 m – 4 h 5 m, `time_in` exactly two minutes after `arrival`, `time_out` exactly two minutes before `departure`. If the DB/driver is unavailable in the run environment, that is an environment limitation (note it; Step 1's suite is the gate) — not a code defect.

- [ ] **Step 4: Run the full suite once more**

Run: `python -m pytest -q`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add docs/time-calculation-overview.md
git commit -m "docs: update time-calculation overview for new arrival/span model"
```

---

## Self-Review

**1. Spec coverage:**

- §2 model (Arrival 08:00–11:00 snapped; Span 210–245; Departure = Arrival+Span; Time-In = Arrival+2; Time-Out = Departure−2; Pick-Up/Drop-Off unchanged; no cap) → Task 1 Steps 3–4; verified by the strengthened `test_default_rules_produce_valid_ordering`.
- §3 rule-set changes (exact key add/remove/replace) → Task 1 Step 3; asserted by rewritten `test_default_rules_present_and_shaped` incl. `"…" not in d` for the three removed keys.
- §4 algorithm order → Task 1 Step 4 `build_daily_schedule`.
- §5 invariant (ordering unchanged; session check now minute-span via `session_span_min`) → Task 1 Step 4 `validate_schedule`; covered by `test_validate_schedule_raises_on_session_length` (30-min span → ValueError) and `_raises_on_bad_ordering` / `_time_in_after_time_out` (unchanged, still raise before the session check).
- §6 testing (200-iter specifics, session-violation, ordering-violation, tight-window rewrite, test_rules shape) → Task 1 Steps 1 & 5; manual e2e → Task 2 Step 3.
- §7 out-of-scope (Pick-Up/Drop-Off, non-Default plans, eligibility/layout/CLI, no cap) → none implemented; only the two source files + their tests + the overview doc change.
- Stale doc `docs/time-calculation-overview.md` (created earlier this session, describes the OLD model) → Task 2 Step 2 brings it in line; in-scope because it documents exactly what is changing.

No gaps.

**2. Placeholder scan:** No "TBD/handle errors/similar to". Every code step shows the complete replacement code; every test step shows complete test code; every run step gives the exact command and expected result.

**3. Type/name consistency:** Rule keys are consistent across rules.py, daily_schedule.py, and both test files: `arrival_window`, `session_span_min`, `pickup_lead_min`, `dropoff_trail_min`, `time_in_drift_min`, `time_out_drift_min`, `round_to_minutes`. `build_daily_schedule(rules, rng)` and `validate_schedule(pickup, arrival, time_in, time_out, departure, dropoff, rules)` signatures are unchanged from the current code (only bodies change), so `rows.py`'s call site and the existing tests' calls remain valid. The six output keys (`pickup/arrival/time_in/time_out/departure/dropoff`) are unchanged, so `workbook.py`/`rows.py` are unaffected.

No issues found.
