# Pick-Up by Availability Start (Busy-Morning Constraint) — Design

**Date:** 2026-07-31
**Status:** Approved

## Problem

Members whose availability starts after the 08:00 day bound (e.g.
Fri/Sat 12:00–16:00) are busy until that start time. The scheduler only
constrained Time-In to the availability window; the transport head
(Pick-Up, Arrival) deliberately reached back before `avail_start` by
~2 min drift + drive time + a 1–5 min buffer. Member 25182 (recurring
Fri/Sat availability 12:00–16:00, 22-minute drive from Brooklyn) got
Pick-Up times like 11:33 — while she was still busy.

Investigated and ruled out: Google Maps *was* queried and applied (the
geo cache held her geocode and a 22-minute route; the printed pickup
leads of 25–29 min = 22 travel + 1–5 buffer + 2 drift match exactly).
The bug was purely the missing head-side constraint.

## Decision summary (user-confirmed)

- Exact mirror of `dropoff_by_avail_end` (spec 2026-07-20), at the head
  of the day: new rule flag **`pickup_by_avail_start`**, **on by
  default**, exposed as a checkbox in Settings → Scheduling Rules.
- Applies only to days whose availability comes from a **recurring**
  `Availability` row; **one-off** rows keep legacy behavior.
- Kicks in only when `avail_start > earliest_time_in` (08:00 by
  default). Days starting at or before the bound, and open days, are
  unchanged.
- When the reserved window can't fit the minimum session, the day is
  **left blank** via the existing `REASON_DAY_WINDOW_TOO_NARROW` path —
  consistent with the drop-off deadline decision.
- **No routing changes** (explicitly out of scope): travel stays
  free-flow Google routing; traffic-aware departure times were offered
  and declined.

## Approach — reserve the head at eligibility time

In `compute_day_eligibility`, after the existing tail reserve:

```
head_reserve = time_in_drift_min[1] + pickup_lead_min[1]
in_lo        = avail_start + head_reserve
```

By eligibility time `apply_travel_offsets` has already rewritten
`pickup_lead_min` to `(travel + buf_lo, travel + buf_hi)`, so the
reserve equals `time_in_drift_max + travel_minutes + travel_buffer_max`
automatically.

**Guarantee:** for any random draw,
`Pick-Up = Time-In − drift − lead ≥ in_lo − drift_max − lead_max
= avail_start`. No generation-time clamping; `build_daily_schedule` and
`validate_schedule` are untouched.

**Worked example (member 25182, travel 22):** reserve = 2 + (22+5) =
29 → Fri/Sat window 12:29–16:00, width 211 ≥ 210 → still eligible;
Pick-Up lands in [12:00, ~12:04]. A member with ≥ ~24 min travel and
the same 12:00–16:00 window would blank instead.

Time cache: no change needed — the placement window is part of entry
validation, so previously printed days whose Time-In now falls before
the raised `in_lo` regenerate on the next run.

## Components

1. **Rule key** — `monthly_schedule/rules.py` and
   `gui/app_settings.py` DEFAULTS both gain
   `"pickup_by_avail_start": True` (the loader's known-key filter
   requires the DEFAULTS entry; the default fill turns it on for
   existing installs).
2. **Eligibility** — `monthly_schedule/per_day.py`: head-reserve block
   mirroring the tail; `DayEligibility` gains `pickup_reserve: int = 0`.
   Both reserves can apply on the same day (e.g. 09:00–15:00); they
   shrink the window independently from each end.
3. **Debug CSV** — `monthly_schedule/rows.py` `_reason_detail` names
   the pick-up reserve on eligible days
   (`pick-up reserve 29m after 12:00 avail start`, joined to the
   drop-off note with `; `) and in the too-narrow arithmetic
   (`avail 13:00-16:00 minus 29m pick-up reserve -> usable 13:29-16:00
   (2h31m) < min 3h30m`). No new column.
4. **GUI** — checkbox row after the drop-off one; i18n key
   `settings.rules.pickup_deadline` (en/zh).

## Testing

- `tests/test_per_day.py`: reserve raises `in_lo` only for recurring
  rows with `avail_start > earliest_time_in`; flag off / one-off /
  at-bound exempt; too-narrow blanks with populated window + reserve;
  head and tail combine; tail-only Sunday shape regression.
- `tests/test_rows.py`: 50-seed property fences — `pickup ≥
  avail_start`, both bounds together, and flag-off proves early pickups
  return; debug `reason_detail` for all reserve combinations.
- `tests/test_rules.py` / `tests/test_app_settings.py`: default on,
  override passes through, missing key filled on, saved False
  respected.
