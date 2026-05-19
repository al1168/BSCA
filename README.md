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

Then provide a Google Maps API key (used for geocoding + Routes).
Copy the template and replace the single line with your real key:

```
copy google_maps.config.example google_maps.config
```

`google_maps.config` is gitignored. The file's entire contents (the
one line, trimmed) are used as the key — no comments. Point
`--google-config PATH` elsewhere if you keep the key file at another
location.

Options:

- `--output-path DIR` — base output directory (default `.`). Single
  and list modes write `DIR/Schedule_<id>_<YYYY-MM>.xlsx`; `--plan`
  writes into `DIR/<CODE>_<YYYY-MM>/`.
- `--db-path PATH` — Access DB path (default the BOWERY3 share)
- `--google-config PATH` — file containing the Google Maps API key
  (default `google_maps.config`, gitignored). Required: Pick-Up/
  Drop-Off use a Google Routes drive-time estimate.
- `--geo-cache PATH` — local JSON cache of geocoded coords + route
  minutes (default `geo_cache.json`, gitignored)
- `--preview-data` — print computed rows per member, write nothing

Full examples (run from the repo root, with `google_maps.config` in
place):

```
# One member -> .\out\Schedule_24010_2026-05.xlsx
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5 --output-path .\out

# Several members by id, all into .\out
python new_monthly_schedule.py --center-ids 24010,24011,24015 --year 2026 --month 5 --output-path .\out

# Every member on a plan -> .\out\HOF_2026-05\Schedule_<id>_2026-05.xlsx
python new_monthly_schedule.py --plan HOF --year 2026 --month 5 --output-path .\out

# Dry run: print the computed rows for a plan, write nothing
python new_monthly_schedule.py --plan HOF --year 2026 --month 5 --preview-data

# Custom key + cache locations
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5 --output-path .\out --google-config C:\keys\gmaps.config --geo-cache .\out\geo_cache.json
```

Pick-Up = Arrival − T and Drop-Off = Departure + T, where T is the
estimated car-drive minutes from the member's address to a fixed
default location. Coordinates come from the Contacts `Long Lat`
column, else the local cache, else the Google Geocoding API. A
member whose travel time cannot be resolved (no coords/address, or
an API error) is skipped and listed in the run summary. See
`docs/superpowers/specs/2026-05-18-travel-time-offsets-design.md`.

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
