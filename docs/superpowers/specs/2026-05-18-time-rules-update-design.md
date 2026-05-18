# Time-Generation Rules Update — Design

**Date:** 2026-05-18
**Status:** Approved (design); pending implementation plan
**Builds on:** `docs/superpowers/specs/2026-05-15-monthly-schedule-design.md` §4

## 1. Purpose & Scope

Change how daily times are generated. Today **Arrival** and
**Departure** are drawn independently from two fixed windows. The new
model draws **Arrival** from a wide morning window, then derives
**Departure** as Arrival plus a random session span, and pins
**Time-In/Time-Out** to exactly ±2 minutes.

Only two files change:

- `monthly_schedule/rules.py` — the `Default` rule set.
- `monthly_schedule/daily_schedule.py` — `build_daily_schedule` and
  `validate_schedule`.

`eligibility.py`, `rows.py`, `workbook.py`, `new_monthly_schedule.py`,
and `db.py` are unchanged. Per-plan keying via `get_rules_for_plan`
(Default fallback) is preserved.

## 2. New Generation Model

For each eligible day:

- **Arrival** = uniform random minute in **08:00–11:00**, snapped by
  `round_to_minutes` (currently `1` ⇒ no snap).
- **Span** = uniform random **210–245 minutes** (3 h 30 m – 4 h 5 m).
- **Departure** = Arrival + Span. Derived (not separately snapped).
  Natural maximum = 11:00 + 4 h 5 m = **15:05**, which is within the
  user's 4 pm comfort ceiling — **no cap logic is added** (a cap would
  never trigger given the arithmetic).
- **Time-In** = Arrival + **exactly 2 minutes**.
- **Time-Out** = Departure − **exactly 2 minutes**.
- **Pick-Up** = Arrival − random 8–12 minutes (unchanged).
- **Drop-Off** = Departure + random 8–12 minutes (unchanged).

Both output tables remain mutually consistent because Pick-Up,
Time-In, Time-Out, and Drop-Off are all derived from the same
Arrival/Departure pair.

## 3. Rule-Set Changes (`SCHEDULE_RULES["Default"]`)

| Key | Before | After |
|-----|--------|-------|
| `arrival_window` | `("08:05", "08:25")` | `("08:00", "11:00")` |
| `departure_window` | `("12:05", "12:25")` | **removed** |
| `session_span_min` | — | `(210, 245)` (new: min/max span, minutes) |
| `time_in_drift_min` | `(0, 3)` | `(2, 2)` (exactly 2) |
| `time_out_drift_min` | `(0, 3)` | `(2, 2)` (exactly 2) |
| `min_session_hours` | `3` | **removed** |
| `max_session_hours` | `6` | **removed** |
| `pickup_lead_min` | `(8, 12)` | unchanged |
| `dropoff_trail_min` | `(8, 12)` | unchanged |
| `round_to_minutes` | `1` | unchanged |

`time_in_drift_min` / `time_out_drift_min` stay as `(2, 2)` tuples
(min == max == 2) rather than becoming scalars, so the rules schema
and the existing `rng.randint(*rule)` call shape are unchanged —
`randint(2, 2)` returns `2`.

`min_session_hours` / `max_session_hours` are removed because the
session length is now drawn directly from `session_span_min`; the
hours-based bound is replaced by a minute-based span check (§5).

## 4. Algorithm (`build_daily_schedule`)

1. Parse `arrival_window` to minutes; `arrival = round_to(
   rng.randint(a_lo, a_hi), step)`.
2. `span = rng.randint(*rules["session_span_min"])`.
3. `departure = arrival + span`.
4. `pickup = arrival - rng.randint(*rules["pickup_lead_min"])`.
5. `dropoff = departure + rng.randint(*rules["dropoff_trail_min"])`.
6. `time_in = arrival + rng.randint(*rules["time_in_drift_min"])`
   (= arrival + 2).
7. `time_out = departure - rng.randint(*rules["time_out_drift_min"])`
   (= departure − 2).
8. `validate_schedule(...)`, then return the six `HH:MM` strings.

The randomness source remains an injected `random.Random`, so a given
seed reproduces the same schedule (tests rely on this).

## 5. Invariant (`validate_schedule`)

Ordering check is unchanged and still holds:

```
Pick-Up < Arrival ≤ Time-In ≤ Time-Out ≤ Departure < Drop-Off
```

`Time-In = Arrival + 2` and `Time-Out = Departure − 2`; since
`Span ≥ 210`, `Time-Out − Time-In = Span − 4 ≥ 206 > 0`, so the
middle inequalities hold. Pick-Up is ≥ 8 min before Arrival and
Drop-Off ≥ 8 min after Departure, so the outer strict inequalities
hold.

The session-length check **changes** from "hours within
`[min_session_hours, max_session_hours]`" to a minute-span check:

```
session_span_min[0] ≤ (Departure − Arrival) ≤ session_span_min[1]
```

i.e. `210 ≤ Span ≤ 245`. A violation raises `ValueError` (surfaced
per-member in the batch run summary, not a crash).

## 6. Testing

`tests/test_daily_schedule.py`:

- The 200-iteration invariant test asserts, every iteration: Arrival
  ∈ [08:00, 11:00] (480–660 min), Span = Departure − Arrival ∈
  [210, 245], Time-In = Arrival + 2, Time-Out = Departure − 2,
  Pick-Up < Arrival, Departure < Drop-Off.
- The session-violation test calls `validate_schedule` with a span
  outside [210, 245] (e.g. 200 min) and expects `ValueError`.
- The ordering-violation test is unchanged in intent (e.g. Pick-Up
  not before Arrival → `ValueError`).
- The previous "tight window + 5-minute snap" test is rewritten
  against the new keys (custom rules with `arrival_window`,
  `session_span_min`, `round_to_minutes: 5`; assert Arrival snapped to
  a multiple of 5 and Span within the custom bound).

`tests/test_rules.py`:

- Update the `Default`-shape assertions: `arrival_window ==
  ("08:00","11:00")`, `session_span_min == (210, 245)`,
  `time_in_drift_min == (2, 2)`, `time_out_drift_min == (2, 2)`,
  no `departure_window` / `min_session_hours` / `max_session_hours`
  keys; `pickup_lead_min`, `dropoff_trail_min`, `round_to_minutes`
  unchanged. `get_rules_for_plan` / `parse_hhmm` / `format_minutes`
  tests unchanged.

No other test files are affected (eligibility/rows/workbook/cli/db
do not depend on the rule-set internals).

Manual: regenerate for member 24010, May 2026, and confirm authorized
days show Arrival in 08:00–11:00, Departure = Arrival + ~3.5–4 h,
Time-In two minutes after Arrival, Time-Out two minutes before
Departure.

## 7. Out of Scope (YAGNI)

- Changing Pick-Up / Drop-Off lead/trail.
- Per-plan rule sets other than `Default`.
- Any change to eligibility, output layout, or the CLI.
- A Departure cap (unnecessary — natural max 15:05).
