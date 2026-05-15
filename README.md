# BSCA

Tools for Bowery Senior Care Inc member data.

## Get-Contact.ps1

Interactive PowerShell lookup of a member by Center ID:

```
pwsh ./Get-Contact.ps1 -CenterID 24010
```

## new_monthly_schedule.py

Generates a printable monthly schedule workbook (attendance +
transportation tables) for one member.

Setup:

```
python -m pip install -r requirements.txt
```

Usage:

```
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5
```

Options:

- `--output-path PATH` — workbook path (default
  `./Schedule_<id>_<YYYY-MM>.xlsx`)
- `--db-path PATH` — Access DB path (default the BOWERY3 share)
- `--preview-data` — print computed rows, skip the workbook

Times are placeholder values (see
`docs/superpowers/specs/2026-05-15-monthly-schedule-design.md`,
section 4). The Microsoft Access ODBC driver must match the Python
interpreter's bitness (spec section 8).

Run tests: `python -m pytest`
