# Morning/Afternoon Distribution Bands — Design

**Date:** 2026-07-23
**Status:** Approved

## Problem

Time-In is currently placed uniformly at random across the whole
placement window (08:00–12:30 with default rules), so member start
times spread evenly across the day. Operationally most members should
arrive in the morning: the user wants roughly 80% of members' visits
to start in a "morning" band (earliest Time-In .. earliest + 3h) and
the remaining ~20% later, with both the percentage and the band length
configurable.

## Priority: validity first (user-confirmed)

The distribution is a **soft preference, strictly subordinate to
schedule validity**. Eligibility checks, availability intersection,
session-length minimums, and the drop-off deadline all run exactly as
today and always win:

- The band only narrows *where inside an already-valid placement
  window* Time-In is drawn. It never widens a window, never schedules
  an unauthorized/absent day, and never changes which days are
  eligible.
- If a member's band does not intersect the day's valid Time-In range
  (e.g. an afternoon member available only mornings, or a narrow
  one-off window), the band is **ignored for that day** and the full
  valid range is used. No day is ever rejected because of the band.
- Consequence: the realized split is only approximately the configured
  percentage — accepted trade-off ("around it, not exact").

## Decision summary (user-confirmed)

- **Per person**, not per day: a member's band applies to all their
  days (a "morning person" all month).
- **Stable across months and runs**: assignment is derived
  deterministically from the member's `center_id` — no new state file.
- **Morning band length is configurable** (default 3h from
  `earliest_time_in`), alongside a configurable morning percentage
  (default 80).
- **Manual pinning**: specific members can be forced into the morning
  or afternoon band via two ID-list settings; pins skip the hash but
  still obey validity-first.

## Approach (chosen: A — deterministic hash threshold)

`band_for_member(center_id, rules)`:

```
if center_id in morning_members:    return "morning"
if center_id in afternoon_members:  return "afternoon"
bucket = int(md5(str(center_id)).hexdigest(), 16) % 100
return "morning" if bucket < morning_percent else "afternoon"
```

Properties: stable across runs/months with zero stored state; over the
member population the split lands near the configured percentage
without being exact; raising 80 → 90 moves only members whose bucket
is 80–89 instead of reshuffling everyone.

Rejected alternatives:

- **Exact-quota draw per run** — hits the percentage exactly but
  assignments flip between runs and months (user chose stability).
- **Persisted assignment file** — stable and hand-editable but adds a
  state file to manage; the ID-list pin settings cover the
  "hand-pick specific members" need without it.

## Components

### 1. Rule keys + defaults

`monthly_schedule/rules.py` `SCHEDULE_RULES["Default"]` and
`gui/app_settings.py` `DEFAULTS["schedule_rules"]` (both required —
the settings loader's known-key filter drops keys absent from
DEFAULTS):

- `"morning_percent": 80` — share of members assigned morning, 0–100.
- `"morning_window_min": 180` — morning band length in minutes,
  measured from `earliest_time_in`.
- `"morning_members": []` — center_ids always morning.
- `"afternoon_members": []` — center_ids always afternoon.

`get_rules_for_plan` needs no change for the ints; the ID lists arrive
as JSON lists and its existing list→tuple conversion is harmless
(membership checks work on tuples). If an ID somehow appears in both
lists (GUI blocks this at save), **morning wins** — deterministic.

`band_for_member(center_id, rules)` lives in `rules.py` next to the
other rule helpers. Edge values behave as expected: percent 100 → all
morning, 0 → all afternoon (pins still win).

### 2. Placement (`monthly_schedule/daily_schedule.py`)

`build_daily_schedule(rules, rng, window=None, band=None)` — new
optional `band` ("morning" / "afternoon" / None = today's behavior).

Today: length is drawn, then `latest_in = max(in_lo, out_hi - length)`
and Time-In is uniform on `[in_lo, latest_in]`. With a band, that
interval is narrowed first:

```
cutoff = parse_hhmm(rules["earliest_time_in"]) + rules["morning_window_min"]
morning:   eff_lo, eff_hi = in_lo, min(latest_in, cutoff)
afternoon: eff_lo, eff_hi = max(in_lo, cutoff), latest_in
fallback:  if eff_lo > eff_hi → eff_lo, eff_hi = in_lo, latest_in
```

Time-In is drawn (and, after `round_to_minutes` snapping, clamped)
within `[eff_lo, eff_hi]`. Everything downstream — session length,
drift, pickup/drop-off derivation, `validate_schedule` — is untouched.
Since `[eff_lo, eff_hi] ⊆ [in_lo, latest_in]`, every banded draw is a
draw the old code could have produced: the invariants and the drop-off
deadline guarantee hold unchanged.

Note the band constrains **Time-In only**: a morning member starting
at 10:59 with a 4h session ends at 14:59 — intended (the user's
definition is about start times).

Escape hatch: setting the morning window length to cover the whole
schedulable day (e.g. 05:00) makes the cutoff exceed every
`latest_in`, so morning members get the full range and afternoon
members hit the fallback — i.e. today's uniform behavior.

### 3. Wiring (`monthly_schedule/rows.py`)

`build_rows` already receives `center_id` and `plan_rules`: compute
`band = band_for_member(center_id, plan_rules)` once (None when
`center_id` is None, e.g. bare library callers) and pass it to every
`build_daily_schedule` call.

### 4. Time cache — no change

Deliberate contrast with the drop-off-deadline feature: the cache's
window guard checks the *validity* window, which the band does not
change, so **already-cached (printed) days keep their exact times**
when the feature is turned on or the percentage changes. Only freshly
generated days follow the band. Operationally: printed schedules never
reshuffle.

### 5. Debug output

`build_debug_rows` gains an optional `center_id` param (callers in
`new_monthly_schedule.collect_debug_rows` pass it) and a new `band`
column: "morning" / "afternoon" on every row (band is a per-member
property), "" when no center_id. `write_debug_csv` adds the header. This lets the user
verify the realized distribution across a run's CSVs.

### 6. GUI (`gui/settings_dialog.py`)

Four new rows in the Scheduling Rules group:

- **Morning members (%)** — `QSpinBox` 0–100, from
  `morning_percent`.
- **Morning window length (HH:MM)** — `QTimeEdit` rendered as a
  duration (same pattern as visit length), from `morning_window_min`.
- **Always-morning member IDs** — `QLineEdit`, comma-separated
  integers, from `morning_members`.
- **Always-afternoon member IDs** — `QLineEdit`, same, from
  `afternoon_members`.

Save-time validation (extends the existing guardrail message box):

- ID fields must parse as comma-separated integers (blank = empty
  list; whitespace tolerated).
- The same ID in both lists → warn and block save.

`gui/i18n.py`: new keys `settings.rules.morning_percent`,
`settings.rules.morning_window`, `settings.rules.morning_members`,
`settings.rules.afternoon_members`, plus a
`settings.rules.band_conflict` warning body — English and Chinese,
same pattern as the other rule labels.

### 7. Docs

- `docs/scheduling-flow.md`: band step in the flow + glossary rows.
- `docs/time-calculation-overview.md`: new rules in the rules table;
  note that banding narrows the Time-In draw, not the validity window.

## Error handling

- Malformed ID lists are blocked at GUI save; if a hand-edited
  settings file contains junk in the lists, non-integer entries are
  ignored at load (defensive cast in `band_for_member`).
- `validate_schedule` invariants unchanged and still hold (banding
  only shrinks the Time-In draw interval inside the valid window).
- No new failure stages in the run summary — the feature cannot fail a
  member or a day.

## Testing

- `tests/test_rules.py` — `band_for_member`: deterministic across
  calls; distribution over ~1,000 synthetic IDs within a few points of
  80/20; percent 0/100 edges; pins win over the hash; pins obey
  morning-wins on (defensive) overlap; non-integer junk in lists
  ignored.
- `tests/test_daily_schedule.py` — across many seeds: morning band →
  every Time-In ≤ cutoff (when the window allows); afternoon band →
  every Time-In ≥ cutoff; band ∩ window empty → falls back to full
  window and still validates; `band=None` → behavior identical to
  today; all ordering/session invariants hold for banded draws.
- `tests/test_rows.py` — band computed from center_id and honored;
  `band` column present in debug rows; no center_id → no band.
- Settings round-trip — new keys survive save/load, defaults fill in
  for older settings files, ID lists round-trip through JSON.
- GUI validation — overlapping ID lists and malformed IDs block save.
