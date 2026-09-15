# Attendance → Availability Backfill — Design

**Date:** 2026-09-15
**Status:** Approved
**Scope:** One-shot maintenance script that estimates each active member's
availability window from the Time-In / Time-Out values on the last three
months of printed Attendance sheets, and writes those estimates to the
`Availability` table. Members, weekdays and settings that need a human
decision are flagged in a report CSV.

## 1. Problem

`Contacts.HHA` describes when a member's home-health aide is with them, but
the text is free-form and often has no times at all (`BetterChoice(6,7)/HHA`,
`爱回家-17hrs`). The scheduler must not generate center times that overlap
those hours, and there is no concrete way to derive them.

The Attendance sheets that were actually handed out over the past months
already embody that knowledge: staff adjusted them by hand so the Time-In /
Time-Out block avoided each member's HHA hours. Per member and weekday
those times are very consistent (typically within 15 minutes month to
month), so the envelope of what was printed is a usable estimate of when
the member can be at the center.

Today every active member's `Availability` rows were reseeded on
2026-09-10 to the 08:00–13:00 default, with about 230 rows hand-edited
since. This script replaces all of those with data-driven windows.

## 2. Inputs

**Attendance sheets** — `\\Dell-NJ02\Desktop\Backup TP System\data\<YYYY>\<MM>\Attendance\`
holds one `.xlsm` per member named `(<center_id>).<Last>, <First> Attendance <YYYY>-<MM>.xlsm`.
The `Attendance` sheet has a header row (`Date`, `Day`, `Time-In`, `Time-Out`)
on row 2 and one row per calendar day from row 3: column A day number,
column B weekday name, column C Time-In, column D Time-Out. Days with no
visit have blank C/D. Times are `datetime.time` values in **12-hour form
without AM/PM**: `02:00` in Time-Out means 14:00. Each workbook also
carries a `Template` sheet, which is ignored.

**Lookback** — July, August and September 2026 (the three most recent
sheets, including the current month, since they carry the latest manual
adjustments). Fixed by CLI flags, defaulting to the three months ending in
the month the script runs.

**Database** — the Cathay Access DB (`dbm-09-15-2026.accdb` for this run),
with `Contacts`, `Enrollment` and `Availability` as documented in
[docs/database.md](../../database.md). "Active member" means a Contact with
an `Enrollment` row whose `end_date IS NULL`.

## 3. Estimation rules

All times are minutes since midnight. A Time-In or Time-Out below 06:00 is
read as PM (+12 h). A row whose Time-Out is not after its Time-In is
dropped and counted (none exist in the current data; the rule is a guard).

For each active member and ISO weekday `d` (1=Mon … 7=Sun):

1. **Per-weekday envelope.** Over every sample for `(member, d)` in the
   lookback: `start = min(Time-In)`, `end = max(Time-Out)`.
2. **Member-wide envelope.** The same over every sample for the member on
   any weekday.
3. **Low-sample widening.** If `(member, d)` has fewer than 4 samples, the
   window becomes the union of the per-weekday and member-wide envelopes.
   Rationale: 97 % of members keep the same window every day, and one or
   two samples of a 4-hour block under-represent a 4h20m envelope.
4. **No-data weekdays.** If `(member, d)` has no samples at all (typically a
   weekday the member is not authorized for), the window is the member-wide
   envelope. The scheduler still gates such days on `auth_days`, so the row
   is inert today but a sensible guess if authorization later changes.
5. **Rounding.** `start` rounds **down** to a multiple of 5 minutes, `end`
   rounds **up** to a multiple of 5 minutes.
6. **No clipping.** The window is written even when `end` is later than the
   `OperatingDays` closing time (14:00 in the current DB) or `start` is
   earlier than the opening time. The scheduler clips at run time; the
   report flags these rows (§6). Changing `OperatingDays` is the
   operator's decision, not this script's.

Members with no samples in the lookback are not written at all and are
listed in the report with flag `no_data`.

## 4. Meaning of the window and required scheduler setting

The window describes when the member is **at the center**: Time-In may not
precede `avail_start`, Time-Out may not exceed `avail_end`, and Pick-Up /
Drop-Off are derived around that block.

The scheduler only interprets `Availability` this way when the two rules
`dropoff_by_avail_end` and `pickup_by_avail_start` are **off** (the
checkboxes "Drop-off by availability end" / "Pick-up by availability start"
in Settings → Scheduling Rules of the Monthly Schedule Generator). With
them on, the scheduler instead treats the window as a Pick-Up / Drop-Off
boundary and reserves drift + drive time + buffer inside it on both ends.
Because the estimated envelopes are only 15–30 minutes wider than the
3h30m–4h session, that would blank most days for members with more than
about a 10-minute drive.

**Operator action:** confirm both checkboxes are unchecked in the Cathay
deployment before the first schedule run that uses these windows. The
script prints this reminder in its summary and writes it to the report.

## 5. Database writes

Only the currently-open row per `(Center ID, Day Of Week)` —
`effective_end_date IS NULL` — is touched, matching the earlier backfills.

- If an open row exists: `UPDATE [Availability] SET [avail_start] = ?,
  [avail_end] = ?, [Notes] = ? WHERE [ID] = ?`. Hand-edited values are
  replaced (user decision); the old window is preserved in the report.
- If no open row exists: `INSERT` with `effective_start_date = <today>`,
  `effective_end_date = NULL`, the estimated times and the note.
- `Notes` records provenance, e.g. `Attendance envelope 2026-07..09, n=13`
  or `member-wide envelope (no Wed data) 2026-07..09, n=39`, so an operator
  looking at the row in Access or the Members app can tell where the
  numbers came from. Any existing note is overwritten (all are empty
  today).
- All writes run in one transaction. `--dry-run` rolls back instead of
  committing; the report is written in both modes.
- Before opening the DB for a non-dry run, the script copies the `.accdb`
  to `<name>.backup_<YYYY-MM-DD-HHMMSS>.accdb` next to it and refuses to
  continue if the copy fails.

Nothing else is modified: `OperatingDays`, `OneOffAvailability`, `Absences`,
`Authorization`, `Enrollment` and `Contacts` are read-only to this script.

## 6. Report CSV

Path: `<csv-out>/attendance_availability_<YYYY-MM-DD>.csv`
(default `<csv-out>` = the DB's directory), UTF-8 with BOM so Excel renders
CJK. One row per active member and weekday (7 rows per covered member), plus
one row per uncovered member.

| Column | Meaning |
| --- | --- |
| `center_id`, `last_name`, `first_name`, `health_plan` | From `Contacts`. |
| `day` | ISO weekday 1–7. Blank on `no_data` rows. |
| `old_window` | The open row's window before the write, `HH:MM-HH:MM`, or blank if no row. |
| `new_window` | The estimate written. |
| `samples` | Number of dated Attendance rows behind the per-weekday envelope. |
| `flags` | Semicolon-separated subset of the vocabulary below. |
| `hha` | Raw `Contacts.HHA` text, for eyeballing against the estimate. |

Flag vocabulary (closed set):

- `past_close` — `new_window` ends after the `OperatingDays` closing time
  for that weekday (or 16:00 if the table has no row). The scheduler will
  clip it.
- `afternoon_only` — `new_window` starts at or after 10:30. Under the
  current 14:00 closing the day cannot fit a session and will be blank.
- `low_samples` — fewer than 4 samples; window widened per §3.3.
- `member_wide` — no samples for this weekday; window is the member-wide
  envelope per §3.4.
- `hand_edit_replaced` — the old window was not the 08:00–13:00 default.
- `narrow` — `new_window` is under 240 minutes wide (cannot happen with the
  current data; guard for future runs).
- `no_data` — member has no Attendance samples in the lookback; nothing
  written.

## 7. CLI surface

```
python scripts/backfill_availability_from_attendance.py
    --db <path.accdb>                     # required
    [--sheets-root <dir>]                 # default \\Dell-NJ02\Desktop\Backup TP System\data
    [--months 2026-07,2026-08,2026-09]    # default: the three months ending this month
    [--csv-out <dir>]                     # default: the DB's directory
    [--min-samples 4]                     # widening threshold (§3.3)
    [--dry-run]                           # report only; roll back DB writes; no backup copy
    [--quiet]                             # summary only
```

Stdout summary (always printed):

```
Attendance availability backfill summary
  Months scanned:                2026-07, 2026-08, 2026-09
  Sheets read / failed:          1283 / 0
  Dated rows with times:         18575   (dropped: 0)
  Active members:                448
    with estimates written:      434
    no attendance data:          14
  Availability rows updated:     3038
  Availability rows inserted:    0
  Weekday rows flagged:          past_close=N  afternoon_only=N  low_samples=N  member_wide=N  hand_edit_replaced=N
  Report CSV: <path>
  Backup:     <path>            (or "none — dry run")
  Mode: APPLIED   (or DRY-RUN — no changes committed)

  Reminder: uncheck "Drop-off by availability end" and "Pick-up by
  availability start" in the Monthly Schedule Generator settings.
```

Exit code 0 on success, 2 on a usage / IO / driver error. A sheet that
fails to open is skipped and counted, not fatal.

## 8. File layout

```
scripts/
  backfill_availability_from_attendance.py   # CLI: sheet walk, DB writes, report (thin)
monthly_schedule/
  attendance_envelope.py                      # pure logic — no IO, no DB
tests/
  test_attendance_envelope.py                 # unit tests on the pure module
  test_backfill_availability_from_attendance.py  # CLI helpers with a fake cursor
```

`attendance_envelope.py` exports:

```python
def normalize_time(value) -> int | None
    # datetime.time / datetime.datetime / Excel fraction / "HH:MM" -> minutes;
    # values before 06:00 are read as PM. None/"" -> None.

def parse_sheet_filename(name) -> tuple[int, str, str] | None
    # "(1001).Zhang, Mingli Attendance 2026-08.xlsm" -> (1001, "Zhang, Mingli", "2026-08")

def collect_samples(rows) -> dict[tuple[int, int], list[tuple[int, int]]]
    # rows: iterable of (center_id, iso_weekday, time_in_min, time_out_min)
    # -> {(center_id, weekday): [(in, out), ...]}, dropping out<=in rows

def estimate_windows(samples_for_member, min_samples=4) -> dict[int, Estimate]
    # {weekday: [(in,out),...]} -> {1..7: Estimate(start, end, samples, flags)}
    # applies §3.1–3.5

def round_window(start, end) -> tuple[int, int]     # §3.5
def hhmm(minutes) -> str
def window_flags(start, end, closing_min) -> list[str]   # past_close / afternoon_only / narrow
```

The script owns: walking the month folders, opening workbooks with
`openpyxl` (`read_only=True, data_only=True`), reading active members and
`OperatingDays`, the upsert, the backup copy, the CSV and the summary.

## 9. Testing

`tests/test_attendance_envelope.py` (no DB, no files):

- `normalize_time`: `time(8,21)` → 501; `time(2,0)` → 840 (PM rule);
  `time(5,59)` → 1079; `time(6,0)` → 360; Excel fraction 0.5 → 720; `None`
  and `""` → `None`.
- `parse_sheet_filename`: the real pattern; names with extra spaces or
  commas; a non-matching name → `None`.
- `collect_samples`: drops `out <= in`; groups by (id, weekday).
- `estimate_windows`: a member with 13 samples on Mon–Fri gets per-weekday
  envelopes; a weekday with 2 samples widens to the member-wide envelope
  and carries `low_samples`; a weekday with none gets the member-wide
  envelope and `member_wide`; rounding goes outward (8:21 → 8:20,
  12:23 → 12:25); a member with zero samples → empty dict.
- `window_flags`: end after closing → `past_close`; start ≥ 10:30 →
  `afternoon_only`; width < 240 → `narrow`; a plain morning window → `[]`.

`tests/test_backfill_availability_from_attendance.py`:

- `_fetch_open_window` / upsert against a fake cursor: existing row →
  UPDATE with Notes; missing row → INSERT; `hand_edit_replaced` set when
  the old window is not 08:00–13:00.
- Report row assembly for a covered member and a `no_data` member.
- `--dry-run` calls `rollback`, not `commit`, and takes no backup.

No live network-share or Access integration test; the dry run against
`dbm-09-15-2026.accdb` is the acceptance check, and its summary numbers are
compared with the exploratory analysis (434 covered, 14 uncovered, 144
members past 14:00, 41 afternoon-only).

## 10. Out of scope

- Parsing `Contacts.HHA`. The raw text is only echoed into the report.
- Changing `OperatingDays` hours (user decision: keep 14:00, flag).
- Padding the window for the transport-reserve rules (user decision: the
  rules are to be turned off instead).
- Reading the TP (transport) sheets. Their Pick-Up / Drop-Off values were
  found to be generated independently of the Attendance sheets and are
  not the source of truth for at-center time.
- Touching `OneOffAvailability`, `Absences`, or already-printed September
  schedules (the scheduler's time cache keeps printed days stable).
- A GUI. This is a one-shot CLI like the other backfills.
