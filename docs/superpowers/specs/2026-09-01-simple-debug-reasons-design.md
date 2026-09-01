# Simple Debug Reasons, Full-Month Coverage

Date: 2026-09-01
Status: Approved

## Problem

The per-member debug CSV is hard for non-technical users to read:

- The `reason` column holds internal constant strings ("weekday not in
  authorized days") and the arithmetic in `reason_detail` is opaque.
- Only authorized days get rows (`build_debug_rows` skips days with no
  active authorization or a weekday outside `auth_days`), so the file
  does not explain most of the month.

## Decision

1. **Every day of the selected month (or day range) gets a row**,
   weekends included. The two `continue` skips in `build_debug_rows`
   are removed; `compute_day_eligibility` already returns the correct
   rejection for non-enrolled / no-auth / wrong-weekday days. On days
   with no active authorization the `auth_days` column is blank.
2. **The CSV `reason` column becomes a plain-English sentence** built
   by a new formatter in `monthly_schedule/rows.py`. The internal
   `REASON_DAY_*` constants are unchanged; only the CSV text changes.
3. **Columns are unchanged in name and order**: `center_id, name,
   date, day, scheduled, reason, reason_detail, availability,
   availability_source, absent, auth_days, placement_window,
   max_length, band`. All technical arithmetic stays in
   `reason_detail`.

## Reason sentences

| Situation | CSV `reason` text |
|---|---|
| Scheduled | `Scheduled` |
| Not enrolled | `Not enrolled at the center on this day` |
| No authorization | `No authorization covers this day` |
| Wrong weekday | `Tuesday is not an authorized day (authorized: Mon, Wed, Fri)` — full weekday name of the date, plus the formatted auth days |
| Absent | `Marked absent (Vacation)` — leave type included when present, otherwise `Marked absent` |
| Window too narrow | `Available time (08:00-11:00) is too short to fit a session` — the effective availability window when known, otherwise `Available time is too short to fit a session` |
| One-off duplicate | `Two conflicting one-off availability entries exist for this day` |
| One-off vs absence | `A one-off availability entry conflicts with an absence on this day` |

## Out of scope / unchanged

- GUI debug checkbox, worker wiring, and file naming.
- The CSV stays English-only (GUI summary translation is separate).
- Scheduling logic (`compute_day_eligibility`, `check_month_failure`)
  and the stable `REASON_DAY_*` constants.
- The travel-failure stamp appended to `reason_detail`.

## Testing

- Update `tests/test_rows.py` and `tests/test_cli.py` expectations.
- New tests: a month renders one row per calendar day (weekends and
  no-auth days included); each rejection situation produces its
  sentence; wrong-weekday sentence names the day and the auth days.
