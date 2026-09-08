# Contacts Group Column

Status: Approved
Date: 2026-09-08

## Goal

Give every member a `Group` label on `Contacts`, set once at setup time
from a text box in the BSCA Setup GUI. The operator types a short
tag (one character or a word), runs setup, and every Contacts row
ends up with that tag in its new `[Group]` column.

## Scope

In scope:

- New idempotent migration `scripts/add_group_to_contacts.py`:
  adds `[Group] TEXT(255)` to `Contacts` if absent, then optionally
  fills blank rows with a given text.
- New setup-chain step, placed right after `add_long_lat_to_contacts`.
- New "Group" text field in the Setup GUI, passed through
  `SetupWorker` to the script.
- PyInstaller hidden import, docs, and tests.

Out of scope:

- Reading `[Group]` anywhere in the scheduler or workbooks. Nothing
  consumes the column yet.
- Remembering the last Group text between runs (the Setup GUI keeps
  no persistent settings).
- Overwriting existing values. The fill only touches rows whose
  `[Group]` is `NULL` or empty, so re-running setup never clobbers a
  value edited by hand in Access.

## Design

### Migration script

`scripts/add_group_to_contacts.py` follows the same shape as
`add_long_lat_to_contacts.py`:

```
--db PATH        required
--group TEXT     optional; when non-blank, fills blank [Group] rows
--quiet          suppress per-column stdout
```

Behavior:

1. Add `[Group] TEXT(255)` to `Contacts` when `_column_exists` says
   it is missing. Print `Added: Contacts.[Group]`; otherwise print
   `already exists`. (`Group` is a reserved word in Access SQL, so
   every reference is bracketed.)
2. If `--group` is non-blank after `strip()`, run

   ```sql
   UPDATE [Contacts] SET [Group] = ?
   WHERE [Group] IS NULL OR [Group] = ''
   ```

   and print `Filled N Contacts row(s) with Group = '<text>'`.
   Blank `--group` skips this and prints nothing extra.
3. Commit once, exit 0. Missing DB or ODBC failure exits 2, matching
   the sibling scripts.

### Setup worker

`SetupWorker.__init__` gains `group_text: str = ""`. `SETUP_STEPS`
gains `("add_group_to_contacts", "scripts.add_group_to_contacts")`
after `add_long_lat_to_contacts` (15 steps total). When running that
one step and `group_text` is non-blank, the argv becomes
`["--db", path, "--group", group_text]`; every other step, and this
step with blank text, keeps `["--db", path]`.

### GUI

Between the DB picker and the Run button:

```
Group (optional):
[ text field, placeholder "e.g. A" ]
Written to the new Contacts [Group] column for every member that does not already have one.
```

The field is disabled while the worker runs and re-enabled after,
like the other inputs. `_on_run_clicked` passes
`self._group_edit.text().strip()` as `group_text`.

### Packaging and docs

- `BSCASetup.spec` lists `scripts.add_group_to_contacts` in
  `hiddenimports`.
- `docs/database.md` adds a `Group` row to the Contacts table.
- `scripts/README.md` adds the script to its table.

## Testing

- `tests/test_add_group_to_contacts.py`: mirrors the plan-type tests
  (connection string, ALTER shape, arg parsing, missing DB, column
  exists true/false), plus: blank `--group` adds the column and issues
  no UPDATE; non-blank `--group` issues the parameterized UPDATE
  after the ALTER and reports the row count; existing column plus
  `--group` issues only the UPDATE.
- `tests/test_setup_worker.py`: step count becomes 15 with
  `add_group_to_contacts` in position 4; new test that
  `group_text="A"` passes `--group A` only to that step; existing
  default-argv assertions stay unchanged.
