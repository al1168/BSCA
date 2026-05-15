# Batch Member Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `new_monthly_schedule.py` select members by single Center ID, a comma-separated ID list, or an MLTC plan code, processing them in one batch with a diagnostic end-of-run summary.

**Architecture:** Add one query/function to `monthly_schedule/db.py` (`get_members_by_plan`). In `new_monthly_schedule.py`, add pure helpers (`parse_center_ids`, `schedule_filename`, `resolve_output_dir`, `format_summary`, a `Failure` namedtuple), convert `--center-id`/`--center-ids`/`--plan` into a required mutually-exclusive argparse group, change `--output-path` to a base directory, and rewrite `main()` to resolve a member list and loop a shared `process_member` helper, collecting per-member failures.

**Tech Stack:** Python 3, pyodbc (lazy), openpyxl, pytest. Tests run from repo root with `python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-05-15-batch-member-selection-design.md`

---

## File Structure

| File | Change |
|------|--------|
| `monthly_schedule/db.py` | ADD `MEMBERS_BY_PLAN_QUERY` + `get_members_by_plan(plan_code, db_path)`; existing `get_member` etc. unchanged |
| `new_monthly_schedule.py` | ADD `import os`, helpers (`parse_center_ids`, `schedule_filename`, `resolve_output_dir`, `Failure`, `format_summary`, `process_member`); REWRITE `parse_args` (mutually-exclusive group, `--output-path` default `.`) and `main()` |
| `tests/test_db.py` | ADD tests for the new query + missing-DB raise |
| `tests/test_cli.py` | ADD helper/selection/batch tests; UPDATE two single-mode tests for the `--output-path`-as-directory change |
| `README.md` | UPDATE usage for the three selectors + output layout |

No other modules change. All new CLI helpers live in `new_monthly_schedule.py` (per spec scope) and are unit-tested via `import new_monthly_schedule as cli`.

---

## Task 1: `get_members_by_plan` in db.py

**Files:**
- Modify: `monthly_schedule/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_db.py`, change the import block (lines 3-8) to add the two new names, and append the two new tests at the end of the file.

Replace:

```python
from monthly_schedule.db import (
    build_connection_string,
    map_member_row,
    MEMBER_QUERY,
    get_member,
)
```

with:

```python
from monthly_schedule.db import (
    build_connection_string,
    map_member_row,
    MEMBER_QUERY,
    MEMBERS_BY_PLAN_QUERY,
    get_member,
    get_members_by_plan,
)
```

Append to the end of `tests/test_db.py`:

```python
def test_members_by_plan_query_columns_and_filter():
    assert "[Center ID]" in MEMBERS_BY_PLAN_QUERY
    assert "[Last Name]" in MEMBERS_BY_PLAN_QUERY
    assert "[First Name]" in MEMBERS_BY_PLAN_QUERY
    assert "[Health Plan]" in MEMBERS_BY_PLAN_QUERY
    assert "[SADC]" in MEMBERS_BY_PLAN_QUERY
    assert "WHERE [Health Plan] = ?" in MEMBERS_BY_PLAN_QUERY
    assert "ORDER BY [Center ID]" in MEMBERS_BY_PLAN_QUERY


def test_get_members_by_plan_missing_db_raises(tmp_path):
    missing = tmp_path / "nope.accdb"
    with pytest.raises(FileNotFoundError):
        get_members_by_plan("HOF", str(missing))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py -q`
Expected: ImportError / collection error — `cannot import name 'MEMBERS_BY_PLAN_QUERY'`.

- [ ] **Step 3: Implement in `monthly_schedule/db.py`**

Append to the end of `monthly_schedule/db.py` (after `get_member`):

```python


MEMBERS_BY_PLAN_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[SADC] FROM [Contacts] WHERE [Health Plan] = ? "
    "ORDER BY [Center ID]"
)


def get_members_by_plan(plan_code, db_path):
    """Return member dicts for every member whose Health Plan equals
    `plan_code`, ordered by Center ID. Access text comparison is
    case-insensitive. Raises FileNotFoundError if the DB path is
    absent, RuntimeError if the ODBC driver cannot open it."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    import pyodbc

    try:
        conn = pyodbc.connect(build_connection_string(db_path))
    except pyodbc.Error as exc:
        raise RuntimeError(
            "Could not open the Access database. Verify the Microsoft "
            "Access ODBC driver is installed and its bitness matches "
            "this Python interpreter (spec section 8). "
            f"Original error: {exc}"
        )
    try:
        cursor = conn.cursor()
        cursor.execute(MEMBERS_BY_PLAN_QUERY, plan_code)
        return [map_member_row(row) for row in cursor.fetchall()]
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -q`
Expected: PASS (existing 4 + 2 new = 6).

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/db.py tests/test_db.py
git commit -m "feat: get_members_by_plan query for plan-based selection"
```

---

## Task 2: `parse_center_ids` helper

**Files:**
- Modify: `new_monthly_schedule.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
import pytest


def test_parse_center_ids_basic():
    assert cli.parse_center_ids("24010,24011") == [24010, 24011]


def test_parse_center_ids_trims_dedupes_drops_blanks_keeps_order():
    assert cli.parse_center_ids("24011, 24010 ,,24011") == [24011, 24010]


def test_parse_center_ids_empty():
    assert cli.parse_center_ids("") == []
    assert cli.parse_center_ids(" , , ") == []


def test_parse_center_ids_non_int_raises():
    with pytest.raises(ValueError):
        cli.parse_center_ids("24010,abc")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -q -k parse_center_ids`
Expected: FAIL — `AttributeError: module 'new_monthly_schedule' has no attribute 'parse_center_ids'`.

- [ ] **Step 3: Implement in `new_monthly_schedule.py`**

Add this function after the `DEFAULT_DB` line (after line 13):

```python


def parse_center_ids(raw):
    """Parse a comma-separated Center ID string into an ordered list
    of unique ints. Whitespace is trimmed, blank entries dropped,
    duplicates removed preserving first-seen order."""
    result = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if value not in result:
            result.append(value)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -q -k parse_center_ids`
Expected: PASS (4).

- [ ] **Step 5: Commit**

```bash
git add new_monthly_schedule.py tests/test_cli.py
git commit -m "feat: parse_center_ids helper"
```

---

## Task 3: `schedule_filename` + `resolve_output_dir` helpers

**Files:**
- Modify: `new_monthly_schedule.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
import os


def test_schedule_filename():
    assert cli.schedule_filename(24010, 2026, 5) == \
        "Schedule_24010_2026-05.xlsx"


def test_resolve_output_dir_non_plan_is_base():
    assert cli.resolve_output_dir(".", None, 2026, 5) == "."
    assert cli.resolve_output_dir("out", None, 2026, 5) == "out"


def test_resolve_output_dir_plan_nests_uppercased_subdir():
    assert cli.resolve_output_dir("out", "hof", 2026, 5) == \
        os.path.join("out", "HOF_2026-05")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -q -k "schedule_filename or resolve_output_dir"`
Expected: FAIL — `AttributeError: ... has no attribute 'schedule_filename'`.

- [ ] **Step 3: Implement in `new_monthly_schedule.py`**

Change the import line `import sys` (line 5) to add `os` immediately before it, so the import block becomes:

```python
import argparse
import os
import random
import sys
```

Add these two functions immediately after `parse_center_ids`:

```python


def schedule_filename(center_id, year, month):
    """Workbook filename for a member/month."""
    return f"Schedule_{center_id}_{year:04d}-{month:02d}.xlsx"


def resolve_output_dir(base, plan_code, year, month):
    """Output directory for the run. Non-plan modes write directly in
    `base`; plan mode nests a `<CODE>_<YYYY-MM>` subdirectory (CODE
    upper-cased). `plan_code` is None for single/list modes."""
    if plan_code is None:
        return base
    sub = f"{plan_code.upper()}_{year:04d}-{month:02d}"
    return os.path.join(base, sub)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -q -k "schedule_filename or resolve_output_dir"`
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add new_monthly_schedule.py tests/test_cli.py
git commit -m "feat: schedule_filename and resolve_output_dir helpers"
```

---

## Task 4: `Failure` record + `format_summary`

**Files:**
- Modify: `new_monthly_schedule.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_format_summary_all_success_headline_only():
    s = cli.format_summary("Wrote", 2, 2, "2026-05", "out", [])
    assert s == "Wrote 2 of 2 member(s) for 2026-05 into out; 0 failed."
    assert "Failures:" not in s


def test_format_summary_preview_no_outdir():
    s = cli.format_summary("Previewed", 1, 1, "2026-05", None, [])
    assert s == "Previewed 1 of 1 member(s) for 2026-05; 0 failed."


def test_format_summary_with_failures_lists_them():
    failures = [
        cli.Failure(24099, "", "lookup", "not found in database"),
        cli.Failure(24100, "Smith, John", "write",
                    "PermissionError — denied"),
    ]
    s = cli.format_summary(
        "Wrote", 18, 20, "plan HOF 2026-05", "out/HOF_2026-05", failures
    )
    lines = s.split("\n")
    assert lines[0] == (
        "Wrote 18 of 20 member(s) for plan HOF 2026-05 "
        "into out/HOF_2026-05; 2 failed."
    )
    assert lines[1] == "Failures:"
    assert lines[2] == "  - ID 24099: lookup — not found in database"
    assert lines[3] == (
        "  - ID 24100 (Smith, John): write — "
        "PermissionError — denied"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -q -k format_summary`
Expected: FAIL — `AttributeError: ... has no attribute 'Failure'`.

- [ ] **Step 3: Implement in `new_monthly_schedule.py`**

Add to the import block (after `import sys`):

```python
from collections import namedtuple
```

Add after `resolve_output_dir`:

```python


Failure = namedtuple("Failure", "center_id name stage reason")


def format_summary(verb, success_count, total, scope, out_dir,
                   failures):
    """Build the end-of-run summary (spec section 5). Headline only on
    full success; an itemized `Failures:` block otherwise."""
    head = f"{verb} {success_count} of {total} member(s) for {scope}"
    if out_dir is not None:
        head += f" into {out_dir}"
    head += f"; {len(failures)} failed."
    if not failures:
        return head
    lines = [head, "Failures:"]
    for f in failures:
        name = f" ({f.name})" if f.name else ""
        lines.append(
            f"  - ID {f.center_id}{name}: {f.stage} — {f.reason}"
        )
    return "\n".join(lines)
```

Note: the separator between stage and reason is an em-dash (`—`,
U+2014), matching the spec example. It is encodable on Windows cp1252.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -q -k format_summary`
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add new_monthly_schedule.py tests/test_cli.py
git commit -m "feat: Failure record and format_summary"
```

---

## Task 5: argparse mutually-exclusive selector group + output dir default

**Files:**
- Modify: `new_monthly_schedule.py` (`parse_args`, lines 16-29)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_parse_args_requires_a_selector():
    with pytest.raises(SystemExit):
        cli.parse_args(["--year", "2026", "--month", "5"])


def test_parse_args_rejects_two_selectors():
    with pytest.raises(SystemExit):
        cli.parse_args(
            ["--center-id", "1", "--plan", "HOF",
             "--year", "2026", "--month", "5"]
        )


def test_parse_args_accepts_each_selector():
    a = cli.parse_args(
        ["--center-ids", "1,2", "--year", "2026", "--month", "5"]
    )
    assert a.center_ids == "1,2"
    assert a.center_id is None and a.plan is None
    b = cli.parse_args(
        ["--plan", "HOF", "--year", "2026", "--month", "5"]
    )
    assert b.plan == "HOF"
    assert b.output_path == "."  # new default: base directory
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -q -k parse_args`
Expected: FAIL — current `parse_args` has no `--center-ids`/`--plan` and `--center-id` is required, so `test_parse_args_accepts_each_selector` errors and the others don't behave as asserted.

- [ ] **Step 3: Implement — replace `parse_args` body**

Replace the entire `parse_args` function (lines 16-29 of the original file) with:

```python
def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Generate printable monthly schedule workbooks."
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--center-id", type=int)
    selector.add_argument("--center-ids")
    selector.add_argument("--plan")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--month", type=int, required=True,
        choices=range(1, 13), metavar="{1-12}",
    )
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--output-path", default=".")
    parser.add_argument("--preview-data", action="store_true")
    return parser.parse_args(argv)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -q -k parse_args`
Expected: PASS (3). (Other CLI tests temporarily fail because `main()` still references the old single-`--center-id` flow — fixed in Task 6.)

- [ ] **Step 5: Commit**

```bash
git add new_monthly_schedule.py tests/test_cli.py
git commit -m "feat: mutually-exclusive selector group; output-path is a dir"
```

---

## Task 6: `process_member` + `main()` rewrite (batch orchestration)

**Files:**
- Modify: `new_monthly_schedule.py` (`main`, lines 32-70; add `process_member`)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Add a second fake member near the top of `tests/test_cli.py` (after the existing `FAKE_MEMBER` block):

```python
FAKE_MEMBER_2 = {
    "center_id": 24011,
    "last_name": "Smith",
    "first_name": "John",
    "health_plan": "HOF",
    "auth_days": "1.3.4.5",
}
```

Append these tests:

```python
def test_single_writes_into_output_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 0
    assert (tmp_path / "Schedule_24010_2026-05.xlsx").exists()


def test_center_ids_batch_one_not_found(monkeypatch, tmp_path, capsys):
    def fake_get_member(cid, db):
        return FAKE_MEMBER if cid == 24010 else None
    monkeypatch.setattr(cli, "get_member", fake_get_member)
    rc = cli.main(
        ["--center-ids", "24010,24099", "--year", "2026",
         "--month", "5", "--output-path", str(tmp_path)]
    )
    assert rc == 2
    assert (tmp_path / "Schedule_24010_2026-05.xlsx").exists()
    err = capsys.readouterr().err
    assert "Wrote 1 of 2 member(s) for 2026-05" in err
    assert "Failures:" in err
    assert "ID 24099: lookup — not found in database" in err


def test_plan_writes_into_subdir(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli, "get_members_by_plan",
        lambda code, db: [FAKE_MEMBER, FAKE_MEMBER_2],
    )
    rc = cli.main(
        ["--plan", "hof", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 0
    sub = tmp_path / "HOF_2026-05"
    assert (sub / "Schedule_24010_2026-05.xlsx").exists()
    assert (sub / "Schedule_24011_2026-05.xlsx").exists()
    assert "for plan HOF 2026-05" in capsys.readouterr().err


def test_plan_no_members(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli, "get_members_by_plan", lambda code, db: []
    )
    rc = cli.main(
        ["--plan", "HOF", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 2
    assert "No members found for plan HOF" in capsys.readouterr().err
    assert not (tmp_path / "HOF_2026-05").exists()


def test_preview_batch_prints_headers_no_files(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli, "get_members_by_plan",
        lambda code, db: [FAKE_MEMBER, FAKE_MEMBER_2],
    )
    rc = cli.main(
        ["--plan", "hof", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path), "--preview-data"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "=== ID 24010 (Cheng, Lizhu) ===" in out
    assert "=== ID 24011 (Smith, John) ===" in out
    assert not (tmp_path / "HOF_2026-05").exists()


def test_write_failure_reported_in_summary(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)

    def boom(member, rows, path):
        raise PermissionError("denied")
    monkeypatch.setattr(cli, "build_workbook", boom)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "Failures:" in err
    assert "ID 24010 (Cheng, Lizhu): write — PermissionError — denied" \
        in err
```

Also UPDATE the two existing tests that assumed the old behavior.

Replace `test_no_member_returns_2` (original lines 24-31) with:

```python
def test_no_member_returns_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: None)
    rc = cli.main(
        ["--center-id", "999", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "ID 999: lookup — not found in database" in err
```

Replace `test_writes_workbook` (original lines 34-42) with:

```python
def test_writes_workbook(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 0
    assert (tmp_path / "Schedule_24010_2026-05.xlsx").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -q`
Expected: FAIL — `main()` still uses the old single-member flow (`args.center_id` required, `--output-path` as file), so the new batch tests fail.

- [ ] **Step 3: Implement — add `process_member`, replace `main`**

Replace the entire `main` function (original lines 32-70) with the following `process_member` + `main`:

```python
def process_member(member, year, month, out_dir, preview):
    """Run the per-member pipeline. Returns (ok, stage, reason).
    On success ok is True and stage/reason are None. On failure ok
    is False, stage is 'generate' or 'write', reason is the
    exception text."""
    authorized = get_authorized_weekdays(member["auth_days"])
    if not authorized:
        print(
            f"Warning: no authorized weekdays parsed from SADC "
            f"{member['auth_days']!r} for ID {member['center_id']}; "
            f"all time cells will be blank.",
            file=sys.stderr,
        )
    rules = get_rules_for_plan(member["health_plan"])
    rng = random.Random()
    try:
        rows = build_rows(year, month, authorized, rules, rng)
    except Exception as exc:  # reported in the run summary
        return (False, "generate", f"{type(exc).__name__} — {exc}")

    if preview:
        print(
            f"=== ID {member['center_id']} "
            f"({member['last_name']}, {member['first_name']}) ==="
        )
        for row in rows:
            print({**row, "date": str(row["date"])})
        return (True, None, None)

    path = os.path.join(
        out_dir, schedule_filename(member["center_id"], year, month)
    )
    try:
        build_workbook(member, rows, path)
    except Exception as exc:  # reported in the run summary
        return (False, "write", f"{type(exc).__name__} — {exc}")
    print(f"Wrote {path}")
    return (True, None, None)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.center_id is not None:
        plan_code = None
        id_list = [args.center_id]
    elif args.center_ids is not None:
        plan_code = None
        id_list = parse_center_ids(args.center_ids)
        if not id_list:
            print("No valid Center IDs provided", file=sys.stderr)
            return 2
    else:
        plan_code = args.plan
        id_list = None

    members = []
    failures = []
    try:
        if plan_code is not None:
            members = get_members_by_plan(plan_code, args.db_path)
        else:
            for cid in id_list:
                member = get_member(cid, args.db_path)
                if member is None:
                    failures.append(
                        Failure(cid, "", "lookup",
                                "not found in database")
                    )
                else:
                    members.append(member)
    except (FileNotFoundError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1

    period = f"{args.year:04d}-{args.month:02d}"
    if plan_code is not None:
        scope = f"plan {plan_code.upper()} {period}"
        if not members:
            print(
                f"No members found for plan {plan_code.upper()}",
                file=sys.stderr,
            )
            return 2
    else:
        scope = period

    out_dir = resolve_output_dir(
        args.output_path, plan_code, args.year, args.month
    )
    if not args.preview_data:
        os.makedirs(out_dir, exist_ok=True)

    success = 0
    for member in members:
        ok, stage, reason = process_member(
            member, args.year, args.month, out_dir, args.preview_data
        )
        if ok:
            success += 1
        else:
            failures.append(
                Failure(
                    member["center_id"],
                    f"{member['last_name']}, {member['first_name']}",
                    stage, reason,
                )
            )

    total = success + len(failures)
    verb = "Previewed" if args.preview_data else "Wrote"
    summary_dir = None if args.preview_data else out_dir
    print(
        format_summary(verb, success, total, scope, summary_dir,
                       failures),
        file=sys.stderr,
    )
    if failures or total == 0:
        return 2
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -q`
Expected: PASS — all CLI tests (helpers, parse_args, batch, updated single-mode).

- [ ] **Step 5: Commit**

```bash
git add new_monthly_schedule.py tests/test_cli.py
git commit -m "feat: batch member resolution, process_member, summary in main()"
```

---

## Task 7: Full suite, README, manual e2e

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: ALL pass (prior 49 + the new db/cli tests; existing non-CLI tests unaffected).

- [ ] **Step 2: Manual end-to-end against the live DB**

Run, in order:

```
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5 --output-path .\out
python new_monthly_schedule.py --center-ids 24010,24011 --year 2026 --month 5 --output-path .\out
python new_monthly_schedule.py --plan HOF --year 2026 --month 5 --output-path .\out
python new_monthly_schedule.py --plan HOF --year 2026 --month 5 --preview-data
```

Expected: first two write `out\Schedule_<id>_2026-05.xlsx`; the third writes `out\HOF_2026-05\Schedule_<id>_2026-05.xlsx` for each HOF member with a `Wrote N of N member(s) for plan HOF 2026-05 into out\HOF_2026-05; 0 failed.` summary on stderr; the fourth prints `=== ID <id> (...) ===` blocks and writes nothing. If the ODBC driver/share is unavailable in the run environment, that is an environment limitation (exit 1 with the clear DB message) — note it, not a code defect; the automated suite in Step 1 is the gate. Do NOT commit any generated `out/` files (they are gitignored via `Schedule_*.xlsx`; the `out/` dir itself should not be added).

- [ ] **Step 3: Update README**

Replace the `## new_monthly_schedule.py` section of `README.md` (original lines 13-42, from `## new_monthly_schedule.py` to the end of file) with:

```markdown
## new_monthly_schedule.py

Generates printable monthly schedule workbooks (attendance +
transportation tables). Select members one of three ways (exactly
one required):

```
# single member
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5

# explicit list
python new_monthly_schedule.py --center-ids 24010,24011 --year 2026 --month 5

# every member on an MLTC plan code
python new_monthly_schedule.py --plan HOF --year 2026 --month 5
```

Setup:

```
python -m pip install -r requirements.txt
```

Options:

- `--output-path DIR` — base output directory (default `.`). Single
  and list modes write `DIR/Schedule_<id>_<YYYY-MM>.xlsx`; `--plan`
  writes into `DIR/<CODE>_<YYYY-MM>/`.
- `--db-path PATH` — Access DB path (default the BOWERY3 share)
- `--preview-data` — print computed rows per member, write nothing

A batch run continues past a member that fails and prints a summary
to stderr (`Wrote N of M ... ; K failed.` plus an itemized
`Failures:` block). Exit code is `0` on full success, `2` if any
member failed or a plan matched nobody, `1` on a DB/driver error.

Times are placeholder values (see
`docs/superpowers/specs/2026-05-15-monthly-schedule-design.md`,
section 4; batch design in
`docs/superpowers/specs/2026-05-15-batch-member-selection-design.md`).
The Microsoft Access ODBC driver must match the Python interpreter's
bitness.

Run tests: `python -m pytest`
```

- [ ] **Step 4: Run the full suite once more**

Run: `python -m pytest -q`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: README usage for batch member selection"
```

---

## Self-Review

**1. Spec coverage:**

- §2 three mutually-exclusive selectors, required group, `--output-path` as dir → Task 5 (+ Task 2 list parsing).
- §3 output layout (filename, list in base, plan subdir uppercased, makedirs) → Tasks 3, 6.
- §4 data flow: resolve list/single via `get_member`, plan via `get_members_by_plan`; extracted `process_member`; preview header `=== ID <id> (Last, First) ===` → Tasks 1, 6.
- §5 error handling: per-member continue, lookup/generate/write stages, blank SADC not a failure (warning only), global DB error → exit 1, empty plan → exit 2, exit `2` on any failure / none selected → Task 6; summary format → Task 4.
- §6 testing: db query/missing-DB (Task 1), center-ids parsing & exclusivity (Tasks 2, 5), plan subdir paths, batch-continue, empty plan, preview headers, write-failure stage, updated single-mode tests (Task 6) → covered. Manual e2e (Task 7).
- §7 out-of-scope items: none implemented (no combined selectors, no combined workbook, no id-file, no parallelism, no friendly-name matching). Respected.

No gaps.

**2. Placeholder scan:** No "TBD/handle errors/similar to". Every code step shows complete code; every test step shows complete test code; every run step gives the exact command and expected result.

**3. Type/name consistency:** `parse_center_ids` (str→list[int]), `schedule_filename(center_id, year, month)`, `resolve_output_dir(base, plan_code, year, month)`, `Failure(center_id, name, stage, reason)`, `format_summary(verb, success_count, total, scope, out_dir, failures)`, `process_member(member, year, month, out_dir, preview) -> (ok, stage, reason)`, `get_members_by_plan(plan_code, db_path)` / `MEMBERS_BY_PLAN_QUERY` — used identically across `main()`, tests, and db.py. Member dict keys (`center_id`, `last_name`, `first_name`, `health_plan`, `auth_days`) match the existing `map_member_row` output and current `tests/test_cli.py` fixtures. `cli.build_workbook` / `cli.get_member` / `cli.get_members_by_plan` are module-level names in `new_monthly_schedule.py` (imported at top), so the monkeypatch targets in the tests are valid.

No issues found.
