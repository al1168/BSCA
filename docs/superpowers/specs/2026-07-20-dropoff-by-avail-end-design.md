# Drop-Off by Availability End (Home Care Deadline) — Design

**Date:** 2026-07-20
**Status:** Approved

## Problem

Members whose availability ends before the 16:00 day bound (e.g.
08:00–15:00) usually have home care starting at that end time. Today the
scheduler only constrains Time-In/Time-Out to the availability window;
the transport tail (Departure, Drop-Off) deliberately spills past
`avail_end` by ~2 min drift + drive time + a 1–5 min buffer. That means
the member is still on the road when their home care aide arrives.

Separately, when a day is rejected as "availability window too narrow",
the debug CSV gives no numbers: `placement_window` and `max_length` are
blank for rejected days, and the debug builder computes its windows with
the *default* drop-off offsets (8–12 min) instead of the travel-adjusted
ones the real run uses.

## Decision summary (user-confirmed)

- **New checkbox setting** in Settings → Scheduling Rules, global for
  all members.
- Applies only to days whose availability comes from a **recurring**
  `Availability` row; **one-off** rows keep today's behavior.
- Kicks in only when `avail_end < latest_time_out` (16:00 by default).
  Days at or past the bound, and open days, are unchanged.
- When the day can't fit the minimum session under the deadline, the day
  is **left blank** (same as the existing "window too narrow" rule).
- Session length logic is untouched: the full 3h30m–4h target is used
  whenever the shrunken window allows it.
- Debug CSV gains the numbers behind every window decision.

## Approach (chosen: A — reserve the tail at eligibility time)

`compute_day_eligibility` already computes the placement window
`(in_lo, out_hi)` that Time-In/Time-Out must fit. With the checkbox on,
for a recurring-availability day with `avail_end < latest_time_out`:

```
reserve = time_out_drift_min[1] + dropoff_trail_min[1]
out_hi  = avail_end - reserve          # instead of min(latest_out, avail_end)
```

By the time eligibility runs in a real run, `new_monthly_schedule`
has already rewritten `dropoff_trail_min` to
`(travel + buf_lo, travel + buf_hi)`, so the reserve automatically
equals `time_out_drift_max + travel_minutes + travel_buffer_max`.

**Guarantee:** for any random draw,
`Drop-Off = Time-Out + drift + trail ≤ out_hi + drift_max + trail_max
= avail_end`. No generation-time clamping needed.

If `out_hi − in_lo < session_length_min[0]`, the day is rejected with
the existing `REASON_DAY_WINDOW_TOO_NARROW` (blank cells).

Rejected alternatives:
- **Clamp at generation time** — eligibility wouldn't know a day can't
  fit (contradicts the leave-blank decision) and stale cached times
  would bypass the deadline.
- **Compress the transport tail** — drive time is physical; the ride
  home can't be shortened.

## Components

### 1. Rule key + defaults

- `monthly_schedule/rules.py` `SCHEDULE_RULES["Default"]`: add
  `"dropoff_by_avail_end": False`.
- `gui/app_settings.py` `DEFAULTS["schedule_rules"]`: add the same key
  (required — the loader's `known`-key filter drops keys absent from
  DEFAULTS).
- `get_rules_for_plan` needs no change: booleans pass through the
  overrides merge untouched (only lists become tuples).

### 2. Eligibility (`monthly_schedule/per_day.py`)

- Track whether the availability row is a one-off
  (`is_one_off = bool(one_offs)`).
- After computing `avail_hi`: if `plan_rules.get("dropoff_by_avail_end")`
  and not `is_one_off` and `avail_hi < latest_out`, set
  `out_hi = avail_hi - reserve` (reserve as above). `in_lo` unchanged.
- `DayEligibility` changes:
  - `placement_window` is now also populated on the too-narrow
    rejection (previously None), so debug output can show it.
  - New optional field `dropoff_reserve: int = 0` — minutes subtracted
    from `avail_end`, 0 when the deadline didn't apply. Used only for
    debug output.

### 3. Generation & time cache

- `build_daily_schedule` — **no change**; it already honors the window.
- Time cache — **no change**; `lookup_times`' window guard invalidates
  cached rows whose block no longer fits the (now smaller) window, so
  toggling the checkbox regenerates exactly the affected days.

### 4. Debug output

- `new_monthly_schedule.collect_debug_rows`: use the same
  travel-adjusted rules as the run. Extract the travel adjustment from
  `process_member` into a shared helper; `collect_debug_rows` resolves
  travel via the geo cache (a cache hit in practice, since the run
  resolved it moments earlier) and falls back to unadjusted defaults on
  `TravelError`.
- `monthly_schedule/rows.py` `build_debug_rows`:
  - `placement_window` / `max_length` columns now filled for
    too-narrow rejections (from the populated `placement_window`).
  - New `reason_detail` column (after `reason`; `reason` strings stay
    stable for i18n). Populated when the numbers explain the decision:
    - Too-narrow day, deadline active:
      `avail 08:00-12:00 minus 34m drop-off reserve → usable
      08:00-11:26 (3h26m) < min 3h30m`
    - Too-narrow day, deadline not active:
      `usable 08:00-11:00 (3h00m) < min 3h30m`
    - Eligible day with deadline active:
      `drop-off reserve 34m before 15:00 avail end`
    - Other reasons: empty.
- `new_monthly_schedule.write_debug_csv`: add the `reason_detail`
  header/field.

### 5. GUI

- `gui/settings_dialog.py`: `QCheckBox` in the Scheduling Rules group,
  initialized from `schedule_rules.get("dropoff_by_avail_end", False)`,
  saved back as a plain bool.
- `gui/i18n.py`: new key `settings.rules.dropoff_by_avail_end`, label
  (en): "End day by availability end (drop-off before home care)" —
  translated for every supported language, same pattern as the other
  rule labels.

### 6. Docs

- `docs/scheduling-flow.md`: flow diagram note + glossary rows for the
  new rule and the drop-off reserve; update the placement-window
  definition.
- `docs/time-calculation-overview.md`: add the rule to the rules table
  and note the shrunken window in §3.

## Error handling

- Duplicate one-off / one-off-vs-absence conflicts unchanged.
- Travel resolution failure already fails the member before generation;
  debug rows fall back to unadjusted defaults (documented in the CSV by
  the numbers themselves).
- `validate_schedule` invariants unchanged and still hold (the window
  shrink only tightens `out_hi`).

## Testing

- `tests/test_per_day.py`: deadline shrinks `out_hi` only for recurring
  rows with `avail_end < latest_time_out`; one-off days and
  `avail_end == 16:00` unchanged; checkbox off → unchanged; too-narrow
  under the deadline → ineligible with populated `placement_window` and
  `dropoff_reserve`.
- Property test: with the flag on, across many seeds/draws,
  parsed `dropoff ≤ avail_end` for recurring days.
- `tests/test_rows.py`: `reason_detail` content for the three populated
  cases; columns filled for rejected days.
- `tests/test_rules.py` / settings round-trip: bool default present,
  survives save/load, overrides merge.
- CLI/debug test: `write_debug_csv` includes the new column; debug rows
  use travel-adjusted rules.
