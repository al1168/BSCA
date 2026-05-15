# BSCA

Tools for Bowery Senior Care Inc member data.

## Get-Contact.ps1

Interactive PowerShell lookup of a member by Center ID:

```
pwsh ./Get-Contact.ps1 -CenterID 24010
```

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
