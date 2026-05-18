# Travel-Time Transport Offsets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pick-Up = Arrival − T and Drop-Off = Departure + T, where T is the Google Routes drive-time (minutes) from the member's coordinates to a fixed default, with coordinates resolved Contacts → local cache → Geocoding API.

**Architecture:** A new `monthly_schedule/travel.py` owns coordinate parsing, the JSON cache, the API-key file, the two Google HTTP calls (lazy `import requests`, like the lazy `pyodbc` pattern), and `resolve_travel_minutes` (precedence + cache mutation). `db.py` additionally returns `address`/`long_lat`. `new_monthly_schedule.py` loads the key+cache once, resolves T per member, and applies it by shallow-copying that member's rules with `pickup_lead_min`/`dropoff_trail_min` set to `(T, T)` — the existing fixed-tuple trick — so `daily_schedule.py`/`rules.py`/`rows.py`/`workbook.py` are untouched. Travel failures become per-member entries in the existing batch summary.

**Tech Stack:** Python 3.13, `requests` (lazy import), pytest (all network mocked). Tests run from repo root with `python -m pytest`. Windows, `python`.

**Spec:** `docs/superpowers/specs/2026-05-18-travel-time-offsets-design.md`

**Note on a deliberate spec refinement:** spec §6's component bullet says `resolve_travel_minutes` "updates+saves cache"; spec §6's CLI bullet says "Save the cache once at the end". This plan implements the single-save form: `resolve_travel_minutes(member, api_key, cache)` mutates the in-memory `cache` dict and the CLI calls `save_cache` once after the member loop. One disk write, no per-member churn.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `monthly_schedule/travel.py` | NEW — `DEFAULT_DESTINATION`, `TravelError`, `parse_long_lat`, `normalize_address`, `load_cache`/`save_cache`, `load_api_key`, `_http_get_json`/`_http_post_json` (lazy `requests`), `geocode_address`, `compute_route_minutes`, `resolve_travel_minutes` |
| `monthly_schedule/db.py` | Add `[Address]`,`[Long Lat]` to both queries; `map_member_row` adds `address`,`long_lat` |
| `new_monthly_schedule.py` | Load key+cache once; per-member resolve T; rule override; save cache once; travel failures in summary; `--google-config`/`--geo-cache` args |
| `tests/test_travel.py` | NEW — unit tests for every `travel.py` function (network mocked) |
| `tests/test_db.py` | Extend query/row tests for the two new columns |
| `tests/test_cli.py` | Autouse travel stub for legacy tests + new travel-integration tests |
| `requirements.txt` | Add `requests==2.32.3` |
| `.gitignore` | Add `google_maps.config`, `geo_cache.json` |

Tests use `from monthly_schedule import travel` and reference `travel.X`, so later tasks append without import churn and monkeypatch via `monkeypatch.setattr(travel, "_http_get_json", ...)`.

---

## Task 1: Scaffolding + pure helpers (`parse_long_lat`, `normalize_address`)

**Files:** Create `monthly_schedule/travel.py`, `tests/test_travel.py`; modify `requirements.txt`, `.gitignore`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_travel.py`:

```python
import pytest

from monthly_schedule import travel


def test_default_destination_is_lat_long():
    assert travel.DEFAULT_DESTINATION == (40.7165774, -73.9954078)


def test_travel_error_carries_stage_and_reason():
    e = travel.TravelError("geocode", "boom")
    assert e.stage == "geocode"
    assert e.reason == "boom"
    assert isinstance(e, Exception)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("40.7165774,-73.9954078", (40.7165774, -73.9954078)),
        (" 40.7 , -73.9 ", (40.7, -73.9)),
        ("", None),
        (None, None),
        ("abc", None),
        ("1", None),
        ("1,2,3", None),
    ],
)
def test_parse_long_lat(text, expected):
    assert travel.parse_long_lat(text) == expected


def test_normalize_address():
    assert travel.normalize_address("  123  Main   St ") == "123 main st"
    assert travel.normalize_address("A,B") == "a,b"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_travel.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'monthly_schedule.travel'`.

- [ ] **Step 3: Create `monthly_schedule/travel.py`**

```python
"""Resolve per-member car travel time to a fixed destination.

Coordinates come from the Contacts `Long Lat` column, a local JSON
cache, or the Google Geocoding API (in that order). Travel minutes
come from the Google Routes API. `requests` is imported lazily inside
the two HTTP helpers (mirroring the lazy `pyodbc` pattern) so the
pure helpers are testable without the dependency or the network.
"""

import json
import os
import sys

DEFAULT_DESTINATION = (40.7165774, -73.9954078)  # (latitude, longitude)


class TravelError(Exception):
    """A per-member travel-resolution failure. `stage` is 'geocode'
    or 'route'; `reason` is a concrete message for the run summary."""

    def __init__(self, stage, reason):
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason


def parse_long_lat(text):
    """Parse a 'lat,long' string into a (lat, long) float tuple, or
    None if absent/blank/malformed."""
    if not text:
        return None
    try:
        lat_str, long_str = str(text).split(",")
        return (float(lat_str), float(long_str))
    except (ValueError, AttributeError):
        return None


def normalize_address(text):
    """Lowercased, whitespace-collapsed address (cache key)."""
    return " ".join(str(text).split()).lower()
```

- [ ] **Step 4: Add the dependency, gitignore entries, and run tests**

Append `requests==2.32.3` as a new line to `requirements.txt` (keep the existing three lines).

Append to `.gitignore` (after the existing entries):

```
# Google API key + geo cache (local only)
google_maps.config
geo_cache.json
```

Run: `python -m pip install -r requirements.txt`
Then: `python -m pytest tests/test_travel.py -q`
Expected: PASS (all parse/normalize/constant/error tests).

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/travel.py tests/test_travel.py requirements.txt .gitignore
git commit -m "feat: travel.py scaffolding + parse_long_lat/normalize_address"
```

---

## Task 2: Cache load/save

**Files:** Modify `monthly_schedule/travel.py`, `tests/test_travel.py`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_travel.py`:

```python
def test_load_cache_missing_returns_empty(tmp_path):
    assert travel.load_cache(str(tmp_path / "nope.json")) == {}


def test_load_cache_corrupt_returns_empty_and_warns(tmp_path, capsys):
    p = tmp_path / "c.json"
    p.write_text("not json{", encoding="utf-8")
    assert travel.load_cache(str(p)) == {}
    assert "geo cache" in capsys.readouterr().err


def test_cache_round_trip(tmp_path):
    p = str(tmp_path / "c.json")
    data = {"geocode": {"a": [1.0, 2.0]}, "route": {"1.0,2.0": 7}}
    travel.save_cache(p, data)
    assert travel.load_cache(p) == data


def test_load_cache_non_dict_returns_empty(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert travel.load_cache(str(p)) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_travel.py -q -k cache`
Expected: FAIL — `AttributeError: module 'monthly_schedule.travel' has no attribute 'load_cache'`.

- [ ] **Step 3: Implement** — append to `monthly_schedule/travel.py`:

```python
def load_cache(path):
    """Return the cache dict, or {} if the file is missing,
    unreadable, or not a JSON object (warns on corrupt)."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("cache root is not an object")
        return data
    except (OSError, ValueError) as exc:
        print(
            f"Warning: ignoring unreadable geo cache {path}: {exc}",
            file=sys.stderr,
        )
        return {}


def save_cache(path, cache):
    """Write the cache dict as pretty JSON (UTF-8)."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2, sort_keys=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_travel.py -q -k cache`
Expected: PASS (4).

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/travel.py tests/test_travel.py
git commit -m "feat: travel geo-cache load/save"
```

---

## Task 3: API-key config loader

**Files:** Modify `monthly_schedule/travel.py`, `tests/test_travel.py`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_travel.py`:

```python
def test_load_api_key_reads_trimmed(tmp_path):
    p = tmp_path / "k.config"
    p.write_text("  my-secret-key\n", encoding="utf-8")
    assert travel.load_api_key(str(p)) == "my-secret-key"


def test_load_api_key_missing_raises(tmp_path):
    with pytest.raises(RuntimeError):
        travel.load_api_key(str(tmp_path / "absent.config"))


def test_load_api_key_empty_raises(tmp_path):
    p = tmp_path / "k.config"
    p.write_text("   \n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        travel.load_api_key(str(p))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_travel.py -q -k api_key`
Expected: FAIL — `AttributeError: ... has no attribute 'load_api_key'`.

- [ ] **Step 3: Implement** — append to `monthly_schedule/travel.py`:

```python
def load_api_key(config_path):
    """Return the trimmed Google API key from `config_path`. Raises
    RuntimeError if the file is missing or empty."""
    if not os.path.exists(config_path):
        raise RuntimeError(
            f"Google API key config not found: {config_path}"
        )
    with open(config_path, "r", encoding="utf-8") as fh:
        key = fh.read().strip()
    if not key:
        raise RuntimeError(
            f"Google API key config is empty: {config_path}"
        )
    return key
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_travel.py -q -k api_key`
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/travel.py tests/test_travel.py
git commit -m "feat: travel API-key config loader"
```

---

## Task 4: HTTP helpers + `geocode_address`

**Files:** Modify `monthly_schedule/travel.py`, `tests/test_travel.py`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_travel.py`:

```python
def test_geocode_address_ok(monkeypatch):
    def fake_get(url, params):
        assert params["address"] == "1 Main St"
        assert params["key"] == "K"
        return {
            "status": "OK",
            "results": [
                {"geometry": {"location": {"lat": 40.5, "lng": -73.5}}}
            ],
        }
    monkeypatch.setattr(travel, "_http_get_json", fake_get)
    assert travel.geocode_address("1 Main St", "K") == (40.5, -73.5)


def test_geocode_address_zero_results(monkeypatch):
    monkeypatch.setattr(
        travel, "_http_get_json",
        lambda url, params: {"status": "ZERO_RESULTS", "results": []},
    )
    with pytest.raises(travel.TravelError) as ei:
        travel.geocode_address("nowhere", "K")
    assert ei.value.stage == "geocode"


def test_geocode_address_http_error(monkeypatch):
    def boom(url, params):
        raise RuntimeError("network down")
    monkeypatch.setattr(travel, "_http_get_json", boom)
    with pytest.raises(travel.TravelError) as ei:
        travel.geocode_address("1 Main St", "K")
    assert ei.value.stage == "geocode"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_travel.py -q -k geocode`
Expected: FAIL — `AttributeError: ... has no attribute 'geocode_address'`.

- [ ] **Step 3: Implement** — append to `monthly_schedule/travel.py`:

```python
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def _http_get_json(url, params):
    """GET `url` with query `params`, return parsed JSON. Network is
    isolated here (lazy `requests` import); tests stub this."""
    import requests

    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _http_post_json(url, body, headers):
    """POST JSON `body` to `url`, return parsed JSON. Network is
    isolated here (lazy `requests` import); tests stub this."""
    import requests

    resp = requests.post(url, json=body, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()


def geocode_address(address, api_key):
    """Geocode `address` -> (lat, long). Raises
    TravelError('geocode', ...) on error or no result."""
    try:
        data = _http_get_json(
            GEOCODE_URL, {"address": address, "key": api_key}
        )
    except Exception as exc:
        raise TravelError("geocode", f"request failed: {exc}")
    status = data.get("status")
    results = data.get("results") or []
    if status != "OK" or not results:
        raise TravelError(
            "geocode", f"{status or 'NO_STATUS'} for {address!r}"
        )
    loc = results[0]["geometry"]["location"]
    return (float(loc["lat"]), float(loc["lng"]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_travel.py -q -k geocode`
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/travel.py tests/test_travel.py
git commit -m "feat: HTTP helpers + geocode_address (mocked tests)"
```

---

## Task 5: `compute_route_minutes`

**Files:** Modify `monthly_schedule/travel.py`, `tests/test_travel.py`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_travel.py`:

```python
def test_compute_route_minutes_rounds(monkeypatch):
    captured = {}

    def fake_post(url, body, headers):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        return {"routes": [{"duration": "754s"}]}
    monkeypatch.setattr(travel, "_http_post_json", fake_post)
    assert travel.compute_route_minutes((40.5, -73.5),
                                        (40.7, -73.9), "K") == 13
    assert captured["headers"]["X-Goog-Api-Key"] == "K"
    assert captured["headers"]["X-Goog-FieldMask"] == "routes.duration"
    assert captured["body"]["travelMode"] == "DRIVE"


def test_compute_route_minutes_min_one(monkeypatch):
    monkeypatch.setattr(
        travel, "_http_post_json",
        lambda url, body, headers: {"routes": [{"duration": "20s"}]},
    )
    assert travel.compute_route_minutes((1, 2), (3, 4), "K") == 1


def test_compute_route_minutes_no_routes(monkeypatch):
    monkeypatch.setattr(
        travel, "_http_post_json",
        lambda url, body, headers: {"routes": []},
    )
    with pytest.raises(travel.TravelError) as ei:
        travel.compute_route_minutes((1, 2), (3, 4), "K")
    assert ei.value.stage == "route"


def test_compute_route_minutes_http_error(monkeypatch):
    def boom(url, body, headers):
        raise RuntimeError("429")
    monkeypatch.setattr(travel, "_http_post_json", boom)
    with pytest.raises(travel.TravelError) as ei:
        travel.compute_route_minutes((1, 2), (3, 4), "K")
    assert ei.value.stage == "route"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_travel.py -q -k route`
Expected: FAIL — `AttributeError: ... has no attribute 'compute_route_minutes'`.

- [ ] **Step 3: Implement** — append to `monthly_schedule/travel.py`:

```python
def _lat_lng(point):
    lat, lng = point
    return {"location": {"latLng": {"latitude": lat,
                                    "longitude": lng}}}


def compute_route_minutes(origin, dest, api_key):
    """Driving minutes origin -> dest via Google Routes. Raises
    TravelError('route', ...) on error. Minutes = max(1,
    round(seconds / 60))."""
    body = {
        "origin": _lat_lng(origin),
        "destination": _lat_lng(dest),
        "travelMode": "DRIVE",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.duration",
    }
    try:
        data = _http_post_json(ROUTES_URL, body, headers)
    except Exception as exc:
        raise TravelError("route", f"request failed: {exc}")
    routes = data.get("routes") or []
    if not routes:
        raise TravelError("route", "no routes returned")
    duration = routes[0].get("duration")
    try:
        seconds = int(str(duration).rstrip("s"))
    except (TypeError, ValueError):
        raise TravelError("route", f"bad duration {duration!r}")
    return max(1, round(seconds / 60))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_travel.py -q -k route`
Expected: PASS (4).

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/travel.py tests/test_travel.py
git commit -m "feat: compute_route_minutes (mocked tests)"
```

---

## Task 6: `resolve_travel_minutes` (precedence + cache)

**Files:** Modify `monthly_schedule/travel.py`, `tests/test_travel.py`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_travel.py`:

```python
def _no_geocode(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("geocode_address should not be called")
    monkeypatch.setattr(travel, "geocode_address", fail)


def test_resolve_uses_db_long_lat_no_geocode(monkeypatch):
    _no_geocode(monkeypatch)
    monkeypatch.setattr(
        travel, "compute_route_minutes",
        lambda origin, dest, key: 9,
    )
    cache = {}
    member = {"long_lat": "40.5,-73.5", "address": "ignored"}
    assert travel.resolve_travel_minutes(member, "K", cache) == 9
    assert cache["route"]["40.5,-73.5"] == 9


def test_resolve_geocode_cache_hit_no_api(monkeypatch):
    _no_geocode(monkeypatch)
    monkeypatch.setattr(
        travel, "compute_route_minutes",
        lambda origin, dest, key: 4,
    )
    cache = {"geocode": {"1 main st": [40.5, -73.5]}}
    member = {"long_lat": None, "address": " 1  Main  St "}
    assert travel.resolve_travel_minutes(member, "K", cache) == 4


def test_resolve_geocode_miss_calls_api_and_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(
        travel, "geocode_address",
        lambda addr, key: calls.append(addr) or (40.5, -73.5),
    )
    monkeypatch.setattr(
        travel, "compute_route_minutes",
        lambda origin, dest, key: 6,
    )
    cache = {}
    member = {"long_lat": "", "address": "1 Main St"}
    assert travel.resolve_travel_minutes(member, "K", cache) == 6
    assert calls == ["1 Main St"]
    assert cache["geocode"]["1 main st"] == [40.5, -73.5]
    assert cache["route"]["40.5,-73.5"] == 6


def test_resolve_route_cache_hit_no_route_call(monkeypatch):
    _no_geocode(monkeypatch)

    def fail_route(*a, **k):
        raise AssertionError("compute_route_minutes should not run")
    monkeypatch.setattr(travel, "compute_route_minutes", fail_route)
    cache = {"route": {"40.5,-73.5": 11}}
    member = {"long_lat": "40.5,-73.5", "address": None}
    assert travel.resolve_travel_minutes(member, "K", cache) == 11


def test_resolve_no_coords_no_address_raises(monkeypatch):
    _no_geocode(monkeypatch)
    member = {"long_lat": None, "address": "   "}
    with pytest.raises(travel.TravelError) as ei:
        travel.resolve_travel_minutes(member, "K", {})
    assert ei.value.stage == "geocode"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_travel.py -q -k resolve`
Expected: FAIL — `AttributeError: ... has no attribute 'resolve_travel_minutes'`.

- [ ] **Step 3: Implement** — append to `monthly_schedule/travel.py`:

```python
def resolve_travel_minutes(member, api_key, cache):
    """Resolve drive-time minutes for `member`. Precedence: Contacts
    `long_lat` -> cache -> Geocoding API. Mutates `cache` in place
    (caller persists it). Raises TravelError(stage, reason) when
    unresolved."""
    coords = parse_long_lat(member.get("long_lat"))
    if coords is None:
        address = member.get("address")
        if not address or not str(address).strip():
            raise TravelError(
                "geocode", "no Long Lat and no address"
            )
        norm = normalize_address(address)
        geo = cache.setdefault("geocode", {})
        if norm in geo:
            coords = tuple(geo[norm])
        else:
            coords = geocode_address(address, api_key)
            geo[norm] = [coords[0], coords[1]]
    lat, lng = coords
    key = f"{round(lat, 5)},{round(lng, 5)}"
    route = cache.setdefault("route", {})
    if key in route:
        return route[key]
    minutes = compute_route_minutes(
        (lat, lng), DEFAULT_DESTINATION, api_key
    )
    route[key] = minutes
    return minutes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_travel.py -q -k resolve`
Then: `python -m pytest tests/test_travel.py -q`
Expected: PASS (all travel tests).

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/travel.py tests/test_travel.py
git commit -m "feat: resolve_travel_minutes precedence + cache"
```

---

## Task 7: db.py — read `Address` and `Long Lat`

**Files:** Modify `monthly_schedule/db.py`, `tests/test_db.py`.

The two new columns are appended at the END of the SELECT lists so existing `row[0..4]` indices are unchanged; `row[5]`=Address, `row[6]`=Long Lat.

- [ ] **Step 1: Write the failing tests** — in `tests/test_db.py`:

Replace `test_member_query_columns_and_filter` with:

```python
def test_member_query_columns_and_filter():
    assert "[Center ID]" in MEMBER_QUERY
    assert "[Last Name]" in MEMBER_QUERY
    assert "[First Name]" in MEMBER_QUERY
    assert "[Health Plan]" in MEMBER_QUERY
    assert "[SADC]" in MEMBER_QUERY
    assert "[Address]" in MEMBER_QUERY
    assert "[Long Lat]" in MEMBER_QUERY
    assert "[SADC Auth]" not in MEMBER_QUERY
    assert "WHERE [Center ID] = ?" in MEMBER_QUERY
```

Replace `test_map_member_row` with:

```python
def test_map_member_row():
    # Access returns [Center ID] as a float; normalize to int.
    row = (24010.0, "Cheng", "Lizhu", "Elderplan Homefirst",
           "1.3.4.5", "1 Main St, NY", "40.71,-73.99")
    result = map_member_row(row)
    assert result["center_id"] == 24010
    assert isinstance(result["center_id"], int)
    assert result == {
        "center_id": 24010,
        "last_name": "Cheng",
        "first_name": "Lizhu",
        "health_plan": "Elderplan Homefirst",
        "auth_days": "1.3.4.5",
        "address": "1 Main St, NY",
        "long_lat": "40.71,-73.99",
    }
```

Replace `test_members_by_plan_query_columns_and_filter` with:

```python
def test_members_by_plan_query_columns_and_filter():
    assert "[Center ID]" in MEMBERS_BY_PLAN_QUERY
    assert "[Last Name]" in MEMBERS_BY_PLAN_QUERY
    assert "[First Name]" in MEMBERS_BY_PLAN_QUERY
    assert "[Health Plan]" in MEMBERS_BY_PLAN_QUERY
    assert "[SADC]" in MEMBERS_BY_PLAN_QUERY
    assert "[Address]" in MEMBERS_BY_PLAN_QUERY
    assert "[Long Lat]" in MEMBERS_BY_PLAN_QUERY
    assert "WHERE [Health Plan] = ?" in MEMBERS_BY_PLAN_QUERY
    assert "ORDER BY [Center ID]" in MEMBERS_BY_PLAN_QUERY
```

Leave the other `test_db.py` tests unchanged.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py -q`
Expected: FAIL — `[Address]` not in `MEMBER_QUERY`; `map_member_row` raises `IndexError`/wrong dict.

- [ ] **Step 3: Implement** — in `monthly_schedule/db.py`:

Replace the `MEMBER_QUERY` assignment with:

```python
MEMBER_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[SADC], [Address], [Long Lat] FROM [Contacts] "
    "WHERE [Center ID] = ?"
)
```

Replace the `MEMBERS_BY_PLAN_QUERY` assignment with:

```python
MEMBERS_BY_PLAN_QUERY = (
    "SELECT [Center ID], [Last Name], [First Name], [Health Plan], "
    "[SADC], [Address], [Long Lat] FROM [Contacts] "
    "WHERE [Health Plan] = ? ORDER BY [Center ID]"
)
```

Replace `map_member_row` with:

```python
def map_member_row(row):
    return {
        # Access returns [Center ID] as a float; normalize to int so
        # the header reads "ID: 24010", not "ID: 24010.0".
        "center_id": int(row[0]),
        "last_name": row[1],
        "first_name": row[2],
        "health_plan": row[3],
        "auth_days": row[4],
        "address": row[5],
        "long_lat": row[6],
    }
```

Leave `build_connection_string`, `get_member`, `get_members_by_plan`, and the docstring unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -q`
Then: `python -m pytest -q`
Expected: `test_db.py` passes; full suite still green EXCEPT `tests/test_cli.py` (its `main()`-using tests now hit travel resolution / missing config — fixed in Task 8). Report the exact failing set; only `test_cli.py` `main()` tests may fail, nothing else.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/db.py tests/test_db.py
git commit -m "feat: db reads Address and Long Lat columns"
```

---

## Task 8: CLI integration + test_cli updates

**Files:** Modify `new_monthly_schedule.py`, `tests/test_cli.py`.

- [ ] **Step 1: Update tests first**

In `tests/test_cli.py`, add `"address"`/`"long_lat"` to both fakes. Replace the `FAKE_MEMBER`/`FAKE_MEMBER_2` blocks (lines 3–17) with:

```python
import new_monthly_schedule as cli

FAKE_MEMBER = {
    "center_id": 24010,
    "last_name": "Cheng",
    "first_name": "Lizhu",
    "health_plan": "HOF",
    "auth_days": "1.3.4.5",
    "address": "1 Main St, NY",
    "long_lat": None,
}

FAKE_MEMBER_2 = {
    "center_id": 24011,
    "last_name": "Smith",
    "first_name": "John",
    "health_plan": "HOF",
    "auth_days": "1.3.4.5",
    "address": "2 Main St, NY",
    "long_lat": None,
}


import pytest


@pytest.fixture(autouse=True)
def _stub_travel(monkeypatch):
    """Neutralize travel for legacy tests: no key file, no network,
    fixed 10-minute offset. Travel-specific tests re-monkeypatch."""
    monkeypatch.setattr(cli, "load_api_key", lambda path: "K")
    monkeypatch.setattr(cli, "load_cache", lambda path: {})
    monkeypatch.setattr(cli, "save_cache", lambda path, cache: None)
    monkeypatch.setattr(
        cli, "resolve_travel_minutes",
        lambda member, api_key, cache: 10,
    )
```

Then DELETE the now-duplicate `import pytest` line that currently sits at line 95 (there must be exactly one `import pytest`, the one added above; the later bare `import pytest` and `import os` further down stay only if not duplicated — keep the `import os` at ~line 116, remove only the second `import pytest`).

Append these new tests at the end of `tests/test_cli.py`:

```python
def test_travel_minutes_applied_to_pickup_and_dropoff(
        monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    monkeypatch.setattr(
        cli, "resolve_travel_minutes",
        lambda member, api_key, cache: 7,
    )
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--preview-data"]
    )
    assert rc == 0
    out = capsys.readouterr().out

    def to_min(hhmm):
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    seen = False
    for line in out.splitlines():
        if not line.startswith("{"):
            continue
        row = eval(line)  # printed dict literal
        if row["arrival"] == "":
            continue
        assert to_min(row["arrival"]) - to_min(row["pickup"]) == 7
        assert to_min(row["dropoff"]) - to_min(row["departure"]) == 7
        seen = True
    assert seen  # at least one eligible day was checked


def test_travel_failure_skips_member_in_summary(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)

    def boom(member, api_key, cache):
        raise cli.TravelError("geocode", "ZERO_RESULTS for 'x'")
    monkeypatch.setattr(cli, "resolve_travel_minutes", boom)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "Failures:" in err
    assert ("ID 24010 (Cheng, Lizhu): geocode — "
            "ZERO_RESULTS for 'x'") in err
    assert not (tmp_path / "Schedule_24010_2026-05.xlsx").exists()


def test_missing_api_key_config_aborts(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)

    def no_key(path):
        raise RuntimeError(
            "Google API key config not found: google_maps.config"
        )
    monkeypatch.setattr(cli, "load_api_key", no_key)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--preview-data"]
    )
    assert rc == 1
    assert "Google API key config not found" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -q`
Expected: FAIL — `new_monthly_schedule` has no `load_api_key`/`resolve_travel_minutes`/`TravelError`/`save_cache`/`load_cache` attributes (the autouse fixture's `monkeypatch.setattr(cli, "load_api_key", ...)` raises `AttributeError`), and the new tests fail.

- [ ] **Step 3: Implement — `new_monthly_schedule.py`**

Replace the import block + `DEFAULT_DB` line (lines 9–15) with:

```python
from monthly_schedule.db import get_member, get_members_by_plan
from monthly_schedule.auth_days import get_authorized_weekdays
from monthly_schedule.rules import get_rules_for_plan
from monthly_schedule.rows import build_rows
from monthly_schedule.workbook import build_workbook
from monthly_schedule.travel import (
    load_api_key,
    load_cache,
    save_cache,
    resolve_travel_minutes,
    TravelError,
)

DEFAULT_DB = r"\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb"
DEFAULT_GOOGLE_CONFIG = "google_maps.config"
DEFAULT_GEO_CACHE = "geo_cache.json"
```

In `parse_args`, add these two arguments immediately before
`parser.add_argument("--preview-data", action="store_true")`:

```python
    parser.add_argument("--google-config", default=DEFAULT_GOOGLE_CONFIG)
    parser.add_argument("--geo-cache", default=DEFAULT_GEO_CACHE)
```

Replace the `process_member` signature and travel resolution. Change the `def process_member(...)` line and the body up to and including the `rules = get_rules_for_plan(...)` line. The new function head (everything from `def` through the `build_rows` call) becomes:

```python
def process_member(member, year, month, out_dir, preview,
                   api_key, cache):
    """Run the per-member pipeline. Returns (ok, stage, reason).
    On success ok is True and stage/reason are None. On failure
    stage is 'geocode'/'route'/'generate'/'write' with the reason."""
    try:
        travel_minutes = resolve_travel_minutes(member, api_key, cache)
    except TravelError as exc:
        return (False, exc.stage, exc.reason)
    rng = random.Random()
    try:
        authorized = get_authorized_weekdays(member["auth_days"])
        if not authorized:
            print(
                f"Warning: no authorized weekdays parsed from SADC "
                f"{member['auth_days']!r} for ID {member['center_id']}; "
                f"all time cells will be blank.",
                file=sys.stderr,
            )
        rules = dict(get_rules_for_plan(member["health_plan"]))
        rules["pickup_lead_min"] = (travel_minutes, travel_minutes)
        rules["dropoff_trail_min"] = (travel_minutes, travel_minutes)
        rows = build_rows(year, month, authorized, rules, rng)
    except Exception as exc:  # reported in the run summary
        return (False, "generate", f"{type(exc).__name__} — {exc}")
```

(The remainder of `process_member` — the `if preview:` block and the workbook-write block — is unchanged.)

In `main`, immediately after `args = parse_args(...)` and before the
`if args.center_id is not None:` block, insert:

```python
    try:
        api_key = load_api_key(args.google_config)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    cache = load_cache(args.geo_cache)
```

In `main`, change the `process_member(...)` call inside the member
loop to pass the two new arguments:

```python
        ok, stage, reason = process_member(
            member, args.year, args.month, out_dir,
            args.preview_data, api_key, cache,
        )
```

In `main`, immediately AFTER the `for member in members:` loop ends
and BEFORE `total = success + len(failures)`, insert:

```python
    save_cache(args.geo_cache, cache)
```

Leave everything else in `new_monthly_schedule.py` unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -q`
Then: `python -m pytest -q`
Expected: ALL pass (legacy CLI tests via the autouse stub; the three new travel tests; full suite green).

- [ ] **Step 5: Commit**

```bash
git add new_monthly_schedule.py tests/test_cli.py
git commit -m "feat: per-member travel-time offsets wired into the CLI"
```

---

## Task 9: Full suite, README, gitignore/requirements verify, manual e2e

**Files:** Modify `README.md`.

- [ ] **Step 1: Full suite**

Run: `python -m pytest -q`
Expected: ALL pass.

- [ ] **Step 2: Verify ignores & deps**

Run (Grep tool or `git status --porcelain`): confirm `.gitignore` contains `google_maps.config` and `geo_cache.json`; `requirements.txt` contains `requests==2.32.3`; no `google_maps.config`, `geo_cache.json`, or generated workbooks are tracked/staged.

- [ ] **Step 3: Update README**

In `README.md`, in the `## new_monthly_schedule.py` section, replace the `Options:` bullet list with:

```markdown
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
```

Then add this paragraph immediately after that list (before the
"A batch run continues..." paragraph):

```markdown
Pick-Up = Arrival − T and Drop-Off = Departure + T, where T is the
estimated car-drive minutes from the member's address to a fixed
default location. Coordinates come from the Contacts `Long Lat`
column, else the local cache, else the Google Geocoding API. A
member whose travel time cannot be resolved (no coords/address, or
an API error) is skipped and listed in the run summary. See
`docs/superpowers/specs/2026-05-18-travel-time-offsets-design.md`.
```

- [ ] **Step 4: Manual e2e (deferred — document only)**

A real run needs a valid key in `google_maps.config` and an
unlocked DB. Record this command for the user to run later:
`python new_monthly_schedule.py --center-id 24010 --year 2026 --month 5 --preview-data`
Expected then: an eligible day's Pick-Up = Arrival − T and Drop-Off
= Departure + T for the member's resolved drive time. (Not run in
CI; the mocked suite in Step 1 is the automated gate.)

- [ ] **Step 5: Run the full suite once more and commit**

Run: `python -m pytest -q`
Expected: ALL pass.

```bash
git add README.md
git commit -m "docs: README usage for travel-time offsets"
```

Confirm only `README.md` is staged (no cache/key/workbook files).

---

## Self-Review

**1. Spec coverage:**

- §1 scope / unchanged modules → new `travel.py` (Tasks 1–6), `db.py` (Task 7), CLI override via `dict(...)` shallow copy + `(T,T)` (Task 8); `daily_schedule`/`rules`/`rows`/`workbook` untouched; DB read-only (no UPDATE anywhere).
- §2 precedence (Long Lat → cache → geocode), route via Routes API, `max(1, round(sec/60))`, route cache key rounded to 5 dp, `Long Lat` = `lat,long` text parsed by `parse_long_lat`, cache JSON shape, missing/corrupt cache → {} + warn → Tasks 1, 2, 4, 5, 6.
- §3 apply offset: `pickup_lead_min`/`dropoff_trail_min` = `(T,T)`, Departure unchanged, generator untouched → Task 8 (asserted by `test_travel_minutes_applied_to_pickup_and_dropoff`).
- §4 config: key from gitignored `google_maps.config` (whole file trimmed), missing/empty → RuntimeError → exit 1 before processing; `.gitignore` entries → Tasks 3, 1, 8.
- §5 failure handling: per-member `TravelError(stage, reason)` → skipped + in `Failures:` (stage geocode/route), global abort for missing key (exit 1), exit codes unchanged → Tasks 6, 8 (`test_travel_failure_skips_member_in_summary`, `test_missing_api_key_config_aborts`). Single attempt, no retry → Tasks 4/5 (one call, no loop).
- §6 components/interfaces → Tasks 1–8 implement each named symbol with the spec signatures (cache-save-once refinement called out at the top of this plan and in Task 6/8).
- §7 testing: every `travel.py` function unit-tested with network mocked (Tasks 1–6), CLI integration tests (Task 8), db query/row tests (Task 7), manual e2e deferred (Task 9).
- §8 out-of-scope: no traffic/`departureTime`, no DB write-back, single fixed `DEFAULT_DESTINATION`, no parallel calls, no retry, no fallback switch — none implemented.

No gaps.

**2. Placeholder scan:** No "TBD/handle errors/similar to". Every code step has complete code; every test step complete test code; every run step an exact command + expected outcome.

**3. Type/name consistency:** `TravelError(stage, reason)` (attributes `.stage`/`.reason`) consistent Tasks 1/4/5/6/8. `parse_long_lat`→`(lat,long)|None`, `normalize_address`→str, `load_cache`/`save_cache`, `load_api_key`, `_http_get_json(url,params)` / `_http_post_json(url,body,headers)`, `geocode_address(address,api_key)`→`(lat,long)`, `compute_route_minutes(origin,dest,api_key)`→int, `resolve_travel_minutes(member,api_key,cache)`→int — used identically across `travel.py`, `tests/test_travel.py`, and the CLI. Member dict keys `center_id/last_name/first_name/health_plan/auth_days/address/long_lat` consistent between `map_member_row` (Task 7), the test fakes (Task 8), and `resolve_travel_minutes`'s `member.get("long_lat")`/`member.get("address")`. `process_member` new signature `(member, year, month, out_dir, preview, api_key, cache)` matches its only call site in `main` (Task 8). The CLI imports `load_api_key/load_cache/save_cache/resolve_travel_minutes/TravelError` as module-level names so the autouse fixture's `monkeypatch.setattr(cli, ...)` targets resolve.

No issues found.
