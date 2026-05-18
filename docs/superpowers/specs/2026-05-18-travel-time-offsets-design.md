# Travel-Time Transport Offsets — Design

**Date:** 2026-05-18
**Status:** Approved (design); pending implementation plan
**Builds on:** the monthly-schedule + batch-selection + time-rules specs.

## 1. Purpose & Scope

Replace the random Pick-Up lead / Drop-Off trail with a real estimate
of the car travel time between the member's address and a fixed
default location. Travel time is resolved once per member from their
coordinates (stored, cached, or geocoded) and a Google Routes call,
then applied symmetrically to Pick-Up and Drop-Off.

**Changes:**

- New module `monthly_schedule/travel.py` — coordinate resolution,
  geocoding, routing, and a local cache.
- `monthly_schedule/db.py` — also read `Address` and `Long Lat`.
- `new_monthly_schedule.py` — resolve travel minutes per member and
  feed them into generation via a per-member rule override; surface
  travel failures in the existing batch summary.
- `.gitignore` — ignore the API-key config file and the cache file.
- `requirements.txt` — add `requests` (pinned).

**Unchanged:** `daily_schedule.py`, `rules.py`, `rows.py`,
`workbook.py`, `eligibility.py`, `health_plan.py`. The Access DB stays
**read-only** (no write-back).

## 2. Coordinate & Travel Resolution (per member, once)

Resolve the member's `(lat, long)` by this precedence:

1. **Contacts `Long Lat`** column — if present and parseable.
2. **Local cache file** — keyed by the member's normalized address.
3. **Google Geocoding API** on the `Address` field — on success the
   result is written to the cache file.

Then compute **travel minutes** with the Google **Routes API**
(`directions/v2:computeRoutes`, travel mode `DRIVE`) from the member
coordinates to the fixed default destination
`DEFAULT_DESTINATION = (40.7165774, -73.9954078)` (latitude,
longitude). The response duration (seconds) → minutes via
`max(1, round(seconds / 60))`. The route result is cached in the same
file keyed by the member coordinate pair (each coordinate rounded to
5 decimals). Because the destination is fixed and routing is **not**
traffic/time-aware, a cached member needs **zero** API calls on
re-runs.

### `Long Lat` storage format

A single text column `Long Lat` holding `latitude,longitude`
(latitude first, matching `DEFAULT_DESTINATION`), e.g.
`40.7165774,-73.9954078`. Empty/blank ⇒ "not set". The parser trims
surrounding whitespace and tolerates a space after the comma; a value
that does not parse to two floats is treated as "not set" (fall
through to cache/geocode).

### Cache file

`geo_cache.json` at the repo root (gitignored), JSON:

```json
{
  "geocode": { "<normalized address>": [lat, long] },
  "route":   { "<lat>,<long>": <minutes> }
}
```

`<normalized address>` = address trimmed, internal whitespace
collapsed to single spaces, lowercased. `<lat>,<long>` = member
coords each rounded to 5 decimals. A missing file = empty cache. An
unreadable/corrupt cache file is treated as empty (warn to stderr,
do not crash); writes recreate it.

## 3. Applying the Offset

`process_member` resolves `travel_minutes` (an int ≥ 1) for the
member, then makes a shallow copy of that member's resolved rules
with `pickup_lead_min = (t, t)` and `dropoff_trail_min = (t, t)`.
Since `build_daily_schedule` does `rng.randint(*rule)`,
`randint(t, t) == t`, giving:

- **Pick-Up = Arrival − t**
- **Drop-Off = Departure + t**
- **Departure unchanged** (still Arrival + session span).

This reuses the existing fixed-tuple mechanism (identical to
`time_in_drift_min = (2, 2)`); `daily_schedule.py` and `rules.py` are
not modified.

## 4. Config & Secrets

- **API key:** read from a local gitignored file `google_maps.config`
  at the repo root — the entire file content, trimmed, is the key
  (used for both Geocoding and Routes). Missing file, empty content,
  or whitespace-only ⇒ a clear `RuntimeError` raised **before** any
  member processing (global abort, like a DB error → exit 1).
- `.gitignore` gains `google_maps.config` and `geo_cache.json`.

## 5. Failure Handling

Per the existing batch model (`Failure` namedtuple +
`format_summary`, stages already free-text):

- **Per-member, recorded & skipped** (no workbook, appears in the
  `Failures:` block, exit code 2): no `Long Lat` and no usable
  `Address`; geocoding returns zero results / non-OK status;
  Geocoding or Routes HTTP call fails (network/quota/timeout). Stage
  is `geocode` (coords couldn't be obtained) or `route` (coords ok
  but routing failed); reason is the concrete cause
  (e.g. `geocode — ZERO_RESULTS for '<address>'`,
  `route — HTTPError 429`).
- **Global abort (exit 1, before any member):** missing/empty
  `google_maps.config`.
- Exit codes otherwise unchanged: `0` all succeeded, `2` any
  member failed (now including travel failures) or empty plan.

A single attempt per API call — no retry/backoff (out of scope).

## 6. Components & Interfaces

`monthly_schedule/travel.py`:

- `DEFAULT_DESTINATION = (40.7165774, -73.9954078)`
- `parse_long_lat(text) -> (lat, long) | None` — pure.
- `normalize_address(text) -> str` — pure.
- `load_cache(path) -> dict` / `save_cache(path, cache)` — tolerant
  of missing/corrupt file.
- `_http_get_json(url) -> dict` and `_http_post_json(url, body,
  headers) -> dict` — the **only** functions that touch the network;
  tests stub these.
- `geocode_address(address, api_key) -> (lat, long)` — raises
  `TravelError("geocode", reason)` on zero-results / error.
- `compute_route_minutes(origin, dest, api_key) -> int` — raises
  `TravelError("route", reason)` on error; `max(1, round(sec/60))`.
- `resolve_travel_minutes(member, api_key, cache, cache_path) -> int`
  — applies the §2 precedence, updates+saves cache on geocode/route
  miss, raises `TravelError(stage, reason)` on unresolved.
- `TravelError(Exception)` with `.stage` and `.reason`.
- `load_api_key(config_path) -> str` — raises `RuntimeError` if
  missing/empty.

`monthly_schedule/db.py`:

- `MEMBER_QUERY` / `MEMBERS_BY_PLAN_QUERY` add `[Address]`,
  `[Long Lat]`.
- `map_member_row` adds `"address"` and `"long_lat"` (raw string or
  None) to the member dict. Column order documented in the query.

`new_monthly_schedule.py`:

- Load API key + cache once at startup (key error → exit 1).
- Per member: `resolve_travel_minutes(...)`; on `TravelError`, append
  a `Failure(center_id, "Last, First", e.stage, e.reason)` and
  continue (no workbook). On success, override the two rule keys and
  run the existing pipeline.
- Save the cache once at the end (after the member loop).

## 7. Testing

**No live API calls.** Tests monkeypatch `_http_get_json` /
`_http_post_json` (or `geocode_address` / `compute_route_minutes`).

Unit (`tests/test_travel.py`):

- `parse_long_lat`: `"40.7,-73.9"` → `(40.7,-73.9)`; `" 40.7 , -73.9 "`
  ok; `""`/`None`/`"abc"`/`"1"` → `None`.
- `normalize_address`: trim/collapse/lowercase.
- `load_cache`: missing path → `{}`; corrupt JSON → `{}` (+warn);
  round-trip with `save_cache`.
- `geocode_address`: mocked OK → coords; mocked ZERO_RESULTS →
  `TravelError("geocode", …)`; mocked HTTP error → `TravelError`.
- `compute_route_minutes`: mocked `"754s"` → `13`
  (`round(754/60)=13`); `"20s"` → `1` (min clamp); mocked error →
  `TravelError("route", …)`.
- `resolve_travel_minutes` precedence: DB `Long Lat` used (no API);
  cache hit (no API); geocode miss → geocode called + cache written;
  route cached vs route called.
- `load_api_key`: file present → trimmed key; missing/empty →
  `RuntimeError`.

CLI (`tests/test_cli.py`):

- Member with stored `Long Lat`, route mocked to N min: workbook
  written, Pick-Up = Arrival − N, Drop-Off = Departure + N (assert by
  reading rows / preview).
- Member whose geocode fails (mocked): skipped, summary `Failures:`
  line shows stage `geocode` and the reason; exit 2.
- Missing `google_maps.config`: exit 1, clear message, no members
  processed.

`tests/test_db.py`: `MEMBER_QUERY`/`MEMBERS_BY_PLAN_QUERY` contain
`[Address]` and `[Long Lat]`; `map_member_row` maps `address` /
`long_lat` (extend the existing sample-row tests; keep `center_id`
int-normalization).

Manual e2e deferred (needs a real API key and an unlocked DB):
`--center-id 24010 …` and confirm Pick-Up/Drop-Off reflect a
plausible drive time.

## 8. Out of Scope (YAGNI)

- Traffic/time-aware routing (`departureTime`).
- Writing coordinates back to the Access DB.
- Multiple or per-plan destinations.
- Parallel/batched API calls.
- Retry/backoff beyond a single attempt.
- A `--ignore-travel` / fallback-to-random switch (failure = skip).
