# How Times Are Currently Calculated

A brief overview of the time generation in `new_monthly_schedule.py`.
The specific clock times are **synthetic** — randomly drawn within the
day's placement window — but that window is shaped by real database
data: the member's authorized weekdays, recurring/one-off availability,
and absences.

## 1. Which days get times

`monthly_schedule/rows.py` walks every calendar day of the month and
asks `monthly_schedule/per_day.py:compute_day_eligibility` whether the
day is eligible (enrollment, authorization, authorized weekday,
one-off/recurring availability, absence, and a wide-enough placement
window — see `docs/scheduling-flow.md`).

- Eligible day → a full set of times is generated.
- Non-eligible day → every time cell is left blank (`""`).

## 2. The rule set

`monthly_schedule/rules.py` holds `SCHEDULE_RULES`, keyed by Health
Plan with a `"Default"` entry used when the plan has no specific
override (`get_rules_for_plan`). Current `Default` values:

| Rule | Value | Meaning |
|------|-------|---------|
| `earliest_time_in` | 08:00 | Time-In may not start before this |
| `latest_time_out` | 16:00 | Time-Out may not end after this |
| `session_length_min` | 210–240 min | Visit length (Time-In → Time-Out), a random 3 h 30 m – 4 h 0 m, capped to the free time in the window |
| `pickup_lead_min` | 8–12 min | Pick-Up is this many minutes **before** Arrival. **Overridden per member at run time**: replaced with `travel_minutes + travel_buffer_min` (drive time + 1–5 min) |
| `dropoff_trail_min` | 8–12 min | Drop-Off is this many minutes **after** Departure. Same per-member travel override as above |
| `travel_buffer_min` | 1–5 min | Random pad added to the Google drive time when building the per-member Pick-Up/Drop-Off offsets |
| `time_in_drift_min` | (2, 2) | Time-In is exactly 2 minutes **after** Arrival |
| `time_out_drift_min` | (2, 2) | Time-Out is exactly 2 minutes **before** Departure |
| `round_to_minutes` | 1 | Snap step for Time-In (1 = no snap; 5 = snap to :05) |
| `dropoff_by_avail_end` | on | When a recurring availability ends before `latest_time_out`, shrink the window so Drop-Off lands at or before `avail_end` (home care). Day goes blank if under 3h30m. |

The earliest/latest bounds and the session length are editable in
**Settings → Scheduling Rules**; availability further narrows them per
day.

## 3. Generating one day (`daily_schedule.build_daily_schedule`)

The attendance block (**Time-In → Time-Out**) is the anchor; the
transport times are derived around it. The day is given a **placement
window** `(in_lo, out_hi)` — the 08:00–16:00 day bounds intersected
with the member's availability — minus the drop-off reserve (max drift
+ drive time + max buffer) when `dropoff_by_avail_end` applies (just
08:00–16:00 when there is no availability rule).

1. **Length** = random minute count in `session_length_min` (210–240),
   capped to `out_hi − in_lo` so it can't exceed the free time.
2. **Time-In** = a random position in `[in_lo, out_hi − Length]`,
   snapped by `round_to_minutes`, so the whole block fits the window.
3. **Time-Out** = Time-In + Length.
4. Derived (exact offsets):
   - **Arrival** = Time-In − random(`time_in_drift_min`)
   - **Departure** = Time-Out + random(`time_out_drift_min`)
   - **Pick-Up** = Arrival − random(`pickup_lead_min`)
   - **Drop-Off** = Departure + random(`dropoff_trail_min`)

Randomness comes from an injected `random.Random` instance, so a
given seed reproduces the same schedule (used in tests).

## 4. Invariant check (`validate_schedule`)

Every generated day is validated; a violation raises `ValueError`
(surfaced per-member in the run summary rather than crashing a batch):

```
Pick-Up < Arrival ≤ Time-In ≤ Time-Out ≤ Departure < Drop-Off
session_length_min[0] ≤ (Time-Out − Time-In) ≤ session_length_min[1]   (210–240 min)
```

With the `Default` rules these always hold: Pick-Up is ≥ 8 min
before Arrival, Drop-Off ≥ 8 min after Departure, and the length is
drawn directly within 210–240 min so the session check cannot fail.

## 5. Output shape

`build_daily_schedule` returns six `HH:MM` strings:
`pickup, arrival, time_in, time_out, departure, dropoff`. The
attendance table uses Time-In/Time-Out; the transport table uses
Pick-Up/Arrival/Departure/Drop-Off — both drawn from the same day's
anchors.

## Key files

- `monthly_schedule/rules.py` — tunable bounds/length/offsets per plan
- `monthly_schedule/daily_schedule.py` — generation + invariant check
- `monthly_schedule/per_day.py` — per-day eligibility + placement window
- `monthly_schedule/rows.py` — per-day loop tying it together

Full rationale: `docs/superpowers/specs/2026-05-15-monthly-schedule-design.md` §4.
