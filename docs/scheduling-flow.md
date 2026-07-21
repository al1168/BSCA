# How the Scheduler Decides to Schedule a Day

For every member in a run, the scheduler walks every day of the target
month and asks a series of questions. The first answer that says "no"
makes that day **ineligible** (blank cells in the workbook); only days
that pass every check get a generated set of times.

This page is the plain-English version of `compute_day_eligibility` in
`monthly_schedule/per_day.py` and `process_member` in
`new_monthly_schedule.py`.

## The flow

```mermaid
flowchart TD
    A([Start: one member, one calendar day]) --> B{Enrolled<br/>on this day?}
    B -- No --> X1[/Ineligible: not enrolled/]
    B -- Yes --> C{Active<br/>authorization<br/>covers this day?}
    C -- No --> X2[/Ineligible: no active authorization/]
    C -- Yes --> D{Day's weekday<br/>is in auth_days?<br/>e.g. Mon/Wed/Fri}
    D -- No --> X3[/Ineligible: weekday not authorized/]
    D -- Yes --> E{One-off<br/>availability row<br/>for this date?}
    E -- "Yes, two or more" --> X4[/Conflict: duplicate one-off rows/]
    E -- "Yes, one row<br/>+ absence" --> X5[/Conflict: one-off vs absence/]
    E -- "Yes, one row" --> H[Use one-off avail_start/avail_end<br/>recurring availability ignored]
    E -- No --> F{Absent<br/>on this day?}
    F -- Yes --> X6[/Ineligible: absent/]
    F -- No --> G{Recurring<br/>Availability row<br/>for this weekday?}
    G -- No --> Y1([Eligible — open day: use the<br/>08:00–16:00 bounds])
    G -- Yes --> H
    H --> I{Day bounds 08:00-16:00<br/>intersected with avail,<br/>minus drop-off reserve when<br/>avail ends early — at least<br/>3h30m wide?}
    I -- No --> X7[/Ineligible: availability window too narrow/]
    I -- Yes --> Y2([Eligible — placement window<br/>clipped to availability])

    Y1 --> Z[Generate times: pickup, arrival,<br/>time_in, time_out, departure, dropoff]
    Y2 --> Z
    Z --> ZA[Write row to the workbook]
```

## What each check actually looks at

| # | Question | Data source | Code |
|---|---|---|---|
| 1 | Is the member enrolled on this date? | `Enrollment.start_date` ≤ day ≤ `Enrollment.end_date` (or open-ended) | `MemberContext.is_enrolled` |
| 2 | Is there an active authorization on this date? | `Authorization.effective_start` ≤ day ≤ `Authorization.effective_end` | `MemberContext.active_authorization` |
| 3 | Is the day's weekday in `auth_days`? | `Authorization.auth_days` (e.g. `"1,3,5"` = Mon/Wed/Fri) | `get_authorized_weekdays` |
| 4 | Is there a `OneOffAvailability` row for this exact date? | `OneOffAvailability.date == day` | `MemberContext.one_offs_for` |
| 5 | Is the member absent on this date? | Any `Absences.start_date` ≤ day ≤ `Absences.end_date` | `MemberContext.is_absent` |
| 6 | Is there a recurring `Availability` row for this weekday? | `Availability.day_of_week == day.isoweekday()` whose effective-date window includes the day | `MemberContext.availability_for` |
| 7 | Is the placement window wide enough for a session? | `min(latest_time_out, avail_end) − max(earliest_time_in, avail_start)` ≥ `session_length_min` (3h30m) | `compute_day_eligibility` |

## What each attribute means

Two kinds of "start/end" appear in this flow and they are easy to
confuse: **date ranges** (which *days* something applies to) and
**clock times** (which *hours within one day*). Every attribute below
is one or the other.

### Date-range attributes (which days)

| Attribute | Meaning |
|---|---|
| `Enrollment.start_date` / `end_date` | The first and last calendar day the member is part of the program. A blank `end_date` means still enrolled (open-ended). A day outside this range is never scheduled. |
| `Authorization.effective_start` / `effective_end` | The calendar-day range an authorization covers. A day must fall inside an authorization's range to be schedulable, even if the member is enrolled. |
| `Absences.start_date` / `end_date` | The first and last day of an absence. Any day inside the range is skipped (unless a one-off availability row exists for it, which is a conflict). |
| `Availability` effective dates | A recurring availability row can itself carry an effective-date window; the row only applies to days inside that window. |
| `OneOffAvailability.date` | A single exact date. When present, this row's times replace the recurring availability for that one day. |

### Clock-time attributes (hours within a day)

| Attribute | Meaning |
|---|---|
| `avail_start` | The earliest clock time the member can **start the visit** (earliest allowed Time-In) on days this availability row applies. It does not limit Pick-Up/Arrival — those may fall slightly before it, since they are derived backwards from Time-In. |
| `avail_end` | The latest clock time the member's visit can **end** (latest allowed Time-Out) on those days. Departure/Drop-Off may fall slightly after it. |
| `earliest_time_in` (default 08:00) | Program-wide hard floor: Time-In may never be earlier than this, no matter how early `avail_start` is. Editable in **Settings → Scheduling Rules**. |
| `latest_time_out` (default 16:00) | Program-wide hard ceiling: Time-Out may never be later than this, no matter how late `avail_end` runs. |
| **Placement window** `(in_lo, out_hi)` | The overlap of the two pairs above: `in_lo = max(earliest_time_in, avail_start)`, `out_hi = min(latest_time_out, avail_end)`. With **Drop off by availability end** on (the default), a recurring availability ending before 16:00 further lowers `out_hi` by the drop-off reserve. The whole attendance block (Time-In → Time-Out) must fit inside it. If the member has no availability row, the window is simply 08:00–16:00 (an "open day"). |
| **Drop-off reserve** | Minutes subtracted from an early `avail_end` so the whole ride home fits before home care starts: max Time-Out drift (2) + drive time + max travel buffer (5). Applies only to recurring availability, only when the **Drop off by availability end** checkbox (Settings → Scheduling Rules, on by default) is checked. Guarantees Drop-Off ≤ `avail_end`. One-off rows are exempt. |
| `session_length_min` (default 210–240) | The allowed visit length in minutes, measured Time-In → Time-Out. A day is only eligible if its placement window is at least the minimum (3 h 30 m) wide. |

### Other scheduling inputs

| Attribute | Meaning |
|---|---|
| `auth_days` | Comma-separated ISO weekday numbers on the authorization, e.g. `"1,3,5"` = Monday/Wednesday/Friday (1 = Mon … 7 = Sun). Only these weekdays can ever be scheduled. |
| `travel_minutes` | The one-way drive time (in minutes) from the member's home address to the center, from Google Routes (cached in `geo_cache.json`). |
| `travel_buffer_min` (default 1–5) | A small random pad added to `travel_minutes` when deriving Pick-Up and Drop-Off, so transport times don't all sit exactly one drive-time away. |

### The six generated times

All six describe **one visit on one day**, and are derived from a
single anchor: the attendance block. Time-In is placed at a random spot
in the placement window, and everything else is offsets from it.

| Time | Meaning | How it's computed |
|---|---|---|
| **Pick-Up** | Transport collects the member at home. | Arrival − (`travel_minutes` + 1–5 min buffer) |
| **Arrival** | The member arrives at the center. | Time-In − 2 min |
| **Time-In** | The member is clocked in — the official start of the visit. This is the anchor everything else hangs off. | Random position in the placement window such that the whole block fits |
| **Time-Out** | The member is clocked out — the official end of the visit. Time-Out − Time-In is the visit length. | Time-In + random length (3 h 30 m – 4 h 0 m) |
| **Departure** | The member leaves the center. | Time-Out + 2 min |
| **Drop-Off** | Transport returns the member home. | Departure + (`travel_minutes` + 1–5 min buffer) |

Only Time-In and Time-Out are constrained by the placement window. With
**Drop off by availability end** off, the transport times deliberately
spill just outside it; with it on (the default), days whose recurring
availability ends before 16:00 reserve the whole transport tail inside
the window, so Drop-Off lands at or before `avail_end`. Every generated day
must satisfy this ordering, or the run reports an error for that member:

```
Pick-Up < Arrival ≤ Time-In ≤ Time-Out ≤ Departure < Drop-Off
```

The attendance table in the workbook uses Time-In/Time-Out; the
transport table uses Pick-Up/Arrival/Departure/Drop-Off — both from the
same day's anchors, so they always agree.

## Whole-month early skip

Before walking days, `compute_month_failure` does three coarse checks
across the whole month. If any of them is true, the member is skipped
entirely and surfaces in `skipped_members_<YYYY-MM-DD>.csv`:

- **Not enrolled any day this month** → `"not enrolled during this month"`
- **No active authorization any day this month** → `"no active authorization for this month"`
- **Absent every authorized day this month** → `"absent for the entire month"`

## After eligibility passes

Once a day is eligible:

1. **Travel time.** `resolve_travel_minutes` either reuses a cached
   route (from `geo_cache.json`) or asks Google Routes for the drive
   time from the member's address to the configured destination.
2. **Time generation.** `build_daily_schedule` picks a random visit
   length (3h30m–4h00m, capped to the free time), then drops that block
   at a random position inside the placement window so the whole of it
   (Time-In → Time-Out) fits. Pickup / arrival / departure / dropoff are
   derived around it using the configurable buffer values in **Settings
   → Scheduling Rules**. Arrival never lands before the member's
   availability start by more than the small Time-In offset, and
   Time-In/Time-Out stay within the 08:00–16:00 day bounds.
3. **Time cache.** If a row for this `(center_id, date)` already exists
   in `time_cache.json`, the plan + travel match, and the cached block
   still fits the current placement window, the cached times are reused
   verbatim. This is what makes a partial-month rerun (May 1–19) produce
   the **same printed times** when the full month (May 1–31) is
   regenerated later.

## Why each check is in this order

The checks are ordered from **cheap to expensive** and from **member
absent to member partially constrained**:

1. Enrollment + authorization gate the entire month — failing here
   means we don't bother loading anything else.
2. Weekday in auth_days is a constant-time set lookup.
3. One-offs and absences come next because they can produce different
   surfaced reasons (silent skip vs. conflict in the failures CSV).
4. The placement-window check is last because it depends on the plan's
   day bounds and the chosen availability row.

If you turn on the **Debug** checkbox in the GUI, each authorized day
gets a row in `Debug_<YYYY-MM>.csv` recording which of these checks
made it ineligible (or `yes` if it was scheduled), a `reason_detail`
column with the arithmetic behind window rejections (availability,
drop-off reserve, usable width vs. required minimum), along with the
availability used, absence/leave type, authorized weekdays, the
placement window, and the maximum session length that fit.
