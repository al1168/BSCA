# How Times Are Currently Calculated

A brief overview of the placeholder time generation in
`new_monthly_schedule.py`. Times are **synthetic** — randomly drawn
within configured windows, not read from the database. The database
only supplies member identity and authorized weekdays.

## 1. Which days get times

`monthly_schedule/rows.py` walks every calendar day of the month. For
each day, `monthly_schedule/eligibility.py:is_day_eligible` returns
true only if the day's ISO weekday is in the member's authorized set
(parsed from the `SADC` column, encoding `1=Mon … 7=Sun`).

- Eligible day → a full set of times is generated.
- Non-eligible day → every time cell is left blank (`""`).

(The `exclusions` parameter for vacation/termination exists in the
seam but is not yet wired to a data source.)

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

## 4. Invariant check (`validate_schedule`)

Every generated day is validated; a violation raises `ValueError`
(surfaced per-member in the run summary rather than crashing a batch):

```
Pick-Up < Arrival ≤ Time-In ≤ Time-Out ≤ Departure < Drop-Off
session_span_min[0] ≤ (Departure − Arrival) ≤ session_span_min[1]   (210–245 min)
```

With the `Default` rules these always hold: Pick-Up is ≥ 8 min
before Arrival, Drop-Off ≥ 8 min after Departure, and the span is
drawn directly within 210–245 min so the session check cannot fail.

## 5. Output shape

`build_daily_schedule` returns six `HH:MM` strings:
`pickup, arrival, time_in, time_out, departure, dropoff`. The
attendance table uses Time-In/Time-Out; the transport table uses
Pick-Up/Arrival/Departure/Drop-Off — both drawn from the same day's
anchors.

## Key files

- `monthly_schedule/rules.py` — tunable windows/offsets per plan
- `monthly_schedule/daily_schedule.py` — generation + invariant check
- `monthly_schedule/eligibility.py` — which days are eligible
- `monthly_schedule/rows.py` — per-day loop tying it together

Full rationale: `docs/superpowers/specs/2026-05-15-monthly-schedule-design.md` §4.
