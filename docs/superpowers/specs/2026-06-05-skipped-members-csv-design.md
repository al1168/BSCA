# Skipped-Members CSV

Status: Draft
Date: 2026-06-05

## Goal

Write every skipped member (regardless of failure stage) to a single CSV per schedule run, in both the GUI and the CLI. Replaces the existing `one_off_conflicts_<date>.csv` (which covered only one specific failure stage) with a broader `skipped_members_<date>.csv`.

## Motivation

Today, when the scheduler skips a member, every skip is itemized in the on-screen failure summary (GUI log / CLI stderr), but only one specific failure stage — `one_off_conflict` — produces a CSV (`one_off_conflicts_<date>.csv`). The other common skip reasons (`lookup`, `eligibility`, `geocode`, `route`, `generate`, `write`) only land in the run-time summary, which is harder to filter, share, or re-open later. A single rolled-up CSV gives the user a durable record per run that they can open in Excel, filter, and act on.

## Scope

In scope:

- `new_monthly_schedule.py` — rename `write_one_off_conflict_csv` to `write_skipped_members_csv`; expand it to write every `Failure` in the list; update its filename, call site, and stderr message.
- `gui/worker.py` — call the renamed function; update the surrounding comment; change the emitted log-line i18n key.
- `gui/i18n.py` — replace `worker.wrote_conflict_csv` with `worker.wrote_skipped_csv` in both `en` and `zh`.
- `tests/test_cli.py` — replace the three `test_write_one_off_conflict_csv_*` tests with four updated tests covering the new function.
- `tests/test_smoke.py` — update the end-to-end test to look for the new CSV name.

Out of scope:

- No new CLI flags. The CSV is written automatically when there are skips, same as today's conflict CSV.
- No changes to the on-screen / log failure summary — that text already lists every skip.
- No new dependencies.
- No GUI affordance for "Open Skipped CSV". The user opens it from the output folder via the existing "Open Output Folder" button.

## Design

### `new_monthly_schedule.py`

Rename `write_one_off_conflict_csv(failures, out_dir, today=None)` → `write_skipped_members_csv(failures, out_dir, today=None)`. Same signature, same return contract (path written, or `None`).

Body changes:

- Iterate over **every** entry in `failures` (drop the `stage == "one_off_conflict"` filter).
- Filename becomes `skipped_members_<YYYY-MM-DD>.csv` using `today or _date.today()`.
- Header row stays `["center_id", "name", "stage", "reason", "day"]`.
- Per-row `day` cell: ISO date when `failure.day` is set (only `one_off_conflict` failures carry it), empty string otherwise. Already matches today's logic — no special-casing needed.
- Return `None` (and write nothing) when `failures` is empty.

In `main()`:

- Update the call site name.
- Change the stderr message from `Wrote conflict report: <filename>` to `Wrote skipped members report: <filename>`.

### `gui/worker.py`

- Update the import: `write_skipped_members_csv` instead of `write_one_off_conflict_csv`.
- Update the call site at the end of `_run_inner` (after `save_cache`); arguments unchanged.
- Update the multi-line comment immediately above the call. It currently says "Conflict CSV lives at the base output dir even in 'all' mode — conflicts can span multiple plans, so a single roll-up file is more useful than per-plan duplicates." Rewrite to refer to the skipped-members CSV; the rationale (multi-plan roll-up) is unchanged.
- Emit the new log key: `worker.wrote_skipped_csv` instead of `worker.wrote_conflict_csv`.

### `gui/i18n.py`

- Remove `worker.wrote_conflict_csv` from both `en` and `zh` dicts.
- Add `worker.wrote_skipped_csv`:
  - `en`: `"Wrote skipped members report: {filename}"`
  - `zh`: `"已写入跳过成员报告：{filename}"`

Both dicts must end with the same key set (enforced by `tests/test_i18n.py::test_key_parity`).

### Tests

`tests/test_cli.py` — replace the three `test_write_one_off_conflict_csv_*` tests with:

1. `test_write_skipped_members_csv_empty_returns_none` — empty `failures` list returns `None`, no file created in `tmp_path`.
2. `test_write_skipped_members_csv_includes_all_stages` — failures across `lookup`, `eligibility`, `geocode`, `one_off_conflict` all appear as rows. Verify the `day` column is the ISO date for the conflict row and empty for the rest.
3. `test_write_skipped_members_csv_filename_uses_today` — the returned path ends with `skipped_members_<today>.csv` using the `today=` parameter.
4. `test_write_skipped_members_csv_preserves_input_order` — multiple failures land in the CSV in input order (matches today's contract).

`tests/test_smoke.py` — update `test_one_off_conflict_writes_conflict_csv`:

- Rename to `test_one_off_conflict_writes_skipped_csv`.
- Update the docstring and the glob: `out_dir.glob("skipped_members_*.csv")`.
- The seed scenario only triggers a single `one_off_conflict` failure, so the row count assertion stays at 1. The stage column for that row is still `one_off_conflict`.

### Preview-mode and "no skips" behavior

Unchanged. The CLI's `if not args.preview_data:` guard and the worker's `if not self.preview:` guard around the CSV call both stay in place. Empty `failures` list returns `None` so no file is written. Both behaviors continue to work; no new code paths needed.

### Output location

Same as today's conflict CSV: the schedule's `out_dir`. In GUI "all members" mode this is the *base* output directory (not a per-plan subdirectory) because failures can span plans — a single roll-up file is more useful than per-plan duplicates. This rationale is preserved in the updated comment.

## Migration / compatibility

No on-disk data format depends on the old filename. Users may have older `one_off_conflicts_<date>.csv` files in their output folders from prior runs — those are left alone (no cleanup). New runs produce `skipped_members_<date>.csv` instead. No setting needs updating.

## Testing

- Automated: the new unit tests in `test_cli.py` cover the rename + behavior expansion. The smoke test (when the Access driver is available) confirms the end-to-end path.
- Manual: run the GUI with a member set that includes at least one skip-able member (e.g., a member who isn't enrolled in the target month), confirm `skipped_members_<today>.csv` appears in the output folder with that member's row.
