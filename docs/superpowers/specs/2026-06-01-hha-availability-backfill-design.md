# HHA → Availability Backfill — Design

**Date:** 2026-06-01
**Scope:** One-shot maintenance script that parses the free-text `Contacts.HHA` column and writes the resulting end-of-day constraints to the `Availability` table. Ambiguous rows are emitted to a CSV for human review.

## 1. Goal

`Contacts.HHA` is a free-text column entered by staff that describes when a member's home-health aide (HHA) is with them. When the HHA window starts mid-afternoon, the member must leave the center by that time, which shortens the day's available-at-center window.

This script reads every non-empty HHA row, classifies it, and:

1. **Applies** end-of-day HHA constraints by inserting or updating rows in `Availability`.
2. **Ignores** rows that contain no time information at all (e.g. agency-only, day-list-only).
3. **Flags** rows that contain time information we can't safely auto-interpret to `hha_backfill_ambiguous_<YYYY-MM-DD>.csv` for human review.

This is a backfill, not an ongoing pipeline. It is expected to be run once after the initial design lands and then re-run only when the HHA column is materially refreshed.

## 2. Conceptual model

- `Availability` holds the **available-at-center window** per `(Center ID, Day Of Week)`.
- Default (no row) = `08:00–16:00`, matching center hours and matching the seeded rows already in the table.
- We only touch the **currently-open** row per (member, day-of-week), defined as the row whose `effective_end_date IS NULL`. Historical rows are left alone.
- We only ever **shorten** an available window. `avail_start` is never lowered; `avail_end` is only moved earlier.

## 3. Inputs and outputs

**Inputs:**

- Access DB path (CLI flag, required) — must contain `Contacts` and `Availability` tables matching the schemas used by [monthly_schedule/db.py](../../../monthly_schedule/db.py).

**Outputs:**

- Mutations to the `Availability` table (skipped under `--dry-run`).
- `hha_backfill_ambiguous_<YYYY-MM-DD>.csv` in `--csv-out` directory (written in every mode).
- Stdout summary at end of run.

## 4. Per-clause classification

A clause is one `(days) time-block` pair extracted from the HHA string. With `HHA_start` parsed to 24h:

| Case | Condition | Action |
|---|---|---|
| End-of-day | `08:00 < HHA_start < 16:00` | **Apply** — emit a write per day with `avail_end = HHA_start` |
| Fully after close | `HHA_start ≥ 16:00` | **Skip silently** — no constraint on center hours |
| Morning / pre-open | `HHA_start ≤ 08:00` | **Ambiguous** — `morning_or_pre_open` |
| Time present but unparseable | n/a | **Ambiguous** — `time_unparseable` |
| Days missing in clause and row | n/a | **Ambiguous** — `days_missing` |
| No time information at all in the row | n/a | **Ignored** (no CSV, no DB change) |

**Row outcome flags** (not mutually exclusive — `applied` and `ambiguous` can both be true on the same row):

- `applied` — at least one clause was applied (DB write emitted).
- `ambiguous` — at least one clause was ambiguous (row appears in CSV).
- `skipped` — had time content but every clause fell after center close (HHA_start ≥ 16:00). No DB write, no CSV row.
- `ignored` — no time content at all (Stage 2 quick reject).

Mixed apply + clause-skip is NOT flagged. Mixed apply + clause-ambiguous IS flagged.

## 5. Parser pipeline

Each HHA row goes through five stages. The first stage that cannot make progress decides the row's outcome.

### Stage 1 — Normalize

- Lowercase.
- Replace Unicode punctuation: `（）：，` → `():,`. Collapse whitespace.
- Strip a leading "agency:" prefix if no digit precedes the `:` (e.g. `PPL: (4.5.6) 2:30-7pm` → `(4.5.6) 2:30-7pm`).
- Keep the **untouched original** aside for CSV output.

### Stage 2 — Quick reject (no time pattern)

If the normalized string contains no `\d{1,2}(:\d{2})?\s*(am|pm)?\s*[-–~]\s*\d` substring, the row has no time. **Ignore** (no CSV, no DB change).

Covers: `1.2.3.7`, `Better Choice`, `ABI`, `Better Choice: 3.4.5.6.7 x 3 Hrs`, agency-with-phone.

### Stage 3 — Clause split

A clause is one `(days) time-block` pair. Split on:

- Top-level commas separating `(...)` groups.
- Sequences of `<digits-and-dots>(time)` patterns even when not comma-separated (e.g. `1.2.3.4(11-2pm) 5.6.7(11-1pm)`).

If splitting yields zero clauses but the row has a time, the row is **ambiguous** with reason `clause_split_failed`.

### Stage 4 — Parse one clause

For each clause, extract:

- **Days** — set of ints 1–7. Accept `1.2.3`, `1,2,3`, `1-5` (range), `1-7`, mixed.
  - If days are missing but a time exists, fall back to "all days mentioned elsewhere in the row".
  - If still none, mark clause ambiguous (`days_missing`).
- **Time block** — start and end times. Accept `2:30-7pm`, `2pm-8pm`, `8-12am`, `2:30pm-7:30pm`, `8:30-11:30PM`, `7am-11am`.
  - Trailing `am`/`pm` applies to both sides if only one side has it.
  - If only the end side has `pm` and start < end numerically, infer `am` for start.
  - If parsing fails, mark clause ambiguous (`time_unparseable`).

### Stage 5 — Classify the clause

Apply the table in §4 to `HHA_start`. Emit zero or more `(day, 08:00, HHA_start)` write directives plus a per-clause status.

### Special-case detectors (run before Stage 3)

- **Date-conditioned** — a `\d+/\d+(?:-\d+/\d+)?` substring (e.g. `6/1-6/30`) flags the row as `date_conditioned` ambiguous, regardless of what else parses.
- **Chinese note** — CJK characters (`[一-鿿]`) appearing **after** the leading agency portion (i.e. after the first `:` or after the first digit group) flag the row as `chinese_note` ambiguous. Leading CJK is treated as agency name and stripped.

These two run early because they indicate the staff was conveying intent we shouldn't auto-parse, even when other parts of the string look clean.

## 6. Database writes

### Upsert logic per `(Center ID, day_of_week)`

```sql
-- Find the currently-open row
SELECT [ID], [avail_start], [avail_end]
FROM [Availability]
WHERE [Center ID] = ?
  AND [Day Of Week] = ?
  AND [effective_end_date] IS NULL
```

- If a row exists: `UPDATE [Availability] SET [avail_end] = ? WHERE [ID] = ?`. Only `avail_end` is touched.
- If no row exists: `INSERT` with `effective_start_date = <today>`, `effective_end_date = NULL`, `avail_start = 08:00`, `avail_end = HHA_start`.

### Multi-clause same-day collision

If two clauses in the same row both write to the same `day_of_week` with different `HHA_start`, take the **earliest** (most restrictive) `HHA_start`. Counted in stats as `multi_clause_same_day`.

### Idempotency

Re-running with unchanged HHA text produces the same final state because `UPDATE` is a no-op when `avail_end` already equals `HHA_start` and the `INSERT` branch only fires when no open row exists.

### Transaction

All writes occur inside one transaction. A mid-run failure leaves the table unchanged. `--dry-run` rolls back instead of committing.

### Bitness note

Same constraint as the rest of the codebase: the installed Microsoft Access ODBC driver must match the Python interpreter's bitness. The script surfaces this with the same error message style used in `monthly_schedule/db.py`.

## 7. Ambiguous CSV

**Path:** `<csv-out-dir>/hha_backfill_ambiguous_<YYYY-MM-DD>.csv` (default `<csv-out-dir>` = current working directory).

**Columns:**

| Column | Source | Example |
|---|---|---|
| `center_id` | `Contacts.[Center ID]` normalized to int | `25088` |
| `last_name` | `Contacts.[Last Name]` | `Wong` |
| `first_name` | `Contacts.[First Name]` | `Mei` |
| `raw_hha` | original HHA text, untouched | `1.2.3(7AM-10AM)` |
| `reason` | short tag from the classifier | `morning_or_pre_open` |
| `attempted_parse` | best-effort dump of what was extracted before bailing | `days=[1,2,3] time_block_raw='7am-10am' parsed_start=07:00 parsed_end=10:00` |

**Reason vocabulary** (closed set):

- `morning_or_pre_open` — HHA_start ≤ 08:00
- `time_unparseable` — found a time substring but couldn't parse start/end
- `days_missing` — time present but no day list in clause or row
- `clause_split_failed` — row has a time but clause splitter returned nothing
- `date_conditioned` — row contains a date range like `6/1-6/30`
- `chinese_note` — row contains CJK text outside the leading agency portion

**One row per ambiguous member**, not per clause. When multiple reasons apply, priority is:

`date_conditioned` > `chinese_note` > `morning_or_pre_open` > `time_unparseable` > `days_missing` > `clause_split_failed`.

The CSV is written even in `--dry-run`.

## 8. CLI surface

```
python scripts/backfill_availability_from_hha.py \
    --db <path-to-accdb>         # required
    [--csv-out <dir>]            # default: current working directory
    [--dry-run]                  # parse + write CSV, do NOT commit DB
    [--quiet]                    # suppress per-row stdout, summary only
```

**Stdout summary** (always printed):

```
HHA backfill summary
  Contacts scanned:        457
  HHA non-empty:           377
  Rows ignored (no time):   83
  Rows skipped (HHA fully after close): 12
  Rows applied:            221    (of which 14 had at least one ambiguous clause)
  Rows fully ambiguous:     73
  Availability rows updated:  148
  Availability rows inserted: 287
  Clauses skipped (HHA_start >= 16:00): 41
  Ambiguous CSV: ./hha_backfill_ambiguous_2026-06-01.csv
  Mode: APPLIED   (or DRY-RUN — no changes committed)
```

## 9. File layout

```
scripts/
  backfill_availability_from_hha.py    # CLI + DB writes (~80 lines)
monthly_schedule/
  hha_parser.py                         # pure parsing — no DB, no IO
tests/
  test_hha_parser.py                    # unit tests on parse_hha_row
```

`hha_parser.py` exports:

```python
def parse_hha_row(text: str) -> ParsedRow: ...

# ParsedRow = {
#   "clauses": list[Clause],
#   "applied": bool,             # any clause status == "apply"
#   "ambiguous": bool,           # any clause status == "ambiguous"
#   "skipped": bool,             # had time, no applied or ambiguous clauses
#   "ignored": bool,             # no time content at all
#   "ambiguous_reason": str | None,
#   "attempted_parse": str,
# }
# Clause = {
#   "days": set[int],
#   "avail_end": str | None,   # "HH:MM" if status == "apply"
#   "status": "apply" | "skip" | "ambiguous",
#   "reason": str | None,
# }
```

The DB write logic lives in `scripts/backfill_availability_from_hha.py`, not in `monthly_schedule/db.py`, because this is a one-shot maintenance op rather than a feature of the main app.

## 10. Testing

`tests/test_hha_parser.py` covers `parse_hha_row` only (no DB). Cases drawn from real samples already pulled from the test DB:

| Input | Expected |
|---|---|
| `PPL: (4.5.6) 2:30-7pm` | apply: `[(4,14:30),(5,14:30),(6,14:30)]` |
| `1-7(2-6pm)` | apply: 7 days at `14:00` |
| `(3.4) 1pm-7pm, (5.6) 1-6pm` | apply: `[(3,13:00),(4,13:00),(5,13:00),(6,13:00)]` |
| `(1.3.5) 8:30-11:30PM, (7) 3pm-6PM` | apply: `[(7,15:00)]`, no CSV flag (mixed apply+skip) |
| `1.2.3(7AM-10AM)` | ambiguous `morning_or_pre_open` |
| `(1.4.6.7) 5-10pm` (HHA 17:00 after close) | skipped (had time, all clauses after close), no CSV, no DB |
| `1.2.3.7` | ignored |
| `Better Choice` | ignored |
| `6/1-6/30 (2.4.6.7) 7am-12pm` | ambiguous `date_conditioned` |
| `占时每天2pm 开始护理 11/1/25有变动` | ambiguous `chinese_note` |
| `1.2.3.4.5.6.7 (8am-12am)` | ambiguous `morning_or_pre_open` (HHA_start 08:00) |

No DB integration tests in v1. The upsert logic is small enough to verify visually via `--dry-run` against `scripts/test_dbs/populate_real_members.accdb`.

## 11. Out of scope

- Mid-day HHA blocks that split availability into two windows (e.g. `(1.3.5) 11am-2pm`). Treated as ambiguous.
- Morning HHA blocks that push `avail_start` later (e.g. `1.2.3(7AM-10AM)`). Treated as ambiguous.
- Reading per-center open/close hours from a config or DB column. The constants `08:00` and `16:00` are baked in.
- Two-pass strategies (LLM-assisted reclassification of the ambiguous CSV). The CSV is the human handoff.
- A separate "applied changes" audit CSV. The DB diff and the stdout summary together cover this need for a one-shot backfill.
