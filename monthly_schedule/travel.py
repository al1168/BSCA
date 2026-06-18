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
import time

_BACKOFF_SECONDS = [1, 2, 4]        # delays before each retry attempt (3 retries max)
_CACHE_TTL_SECONDS = 7 * 24 * 3600 # 1 week

DEFAULT_DESTINATION = (40.7165774, -73.9954078)  # (latitude, longitude)


class TravelError(Exception):
    """A per-member travel-resolution failure. `stage` is 'geocode'
    or 'route'; `reason` is a concrete message for the run summary."""

    def __init__(self, stage, reason):
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason


def parse_long_lat(text):
    """Parse a 'long,lat' string (matching the Contacts.[Long Lat]
    column name — longitude first, then latitude) and return a
    (lat, long) tuple suitable for the geocoding/routes APIs.

    Returns None for absent, blank, malformed input, or values that
    are out of valid geographic range (lat outside [-90, 90] or
    long outside [-180, 180]). The range guard prevents silently
    sending nonsense to Google's Routes API (which then returns
    "no routes returned" — see members.[Long Lat] values entered in
    'lat,long' order by mistake)."""
    if not text:
        return None
    try:
        long_str, lat_str = str(text).split(",")
        lat = float(lat_str)
        lng = float(long_str)
    except (ValueError, AttributeError):
        return None
    if not (-90.0 <= lat <= 90.0):
        return None
    if not (-180.0 <= lng <= 180.0):
        return None
    return (lat, lng)


def normalize_address(text):
    """Lowercased, whitespace-collapsed address (cache key)."""
    return " ".join(str(text).split()).lower()


def _purge_expired(cache, now=None):
    """Remove geocode/route entries whose timestamp is missing or older
    than _CACHE_TTL_SECONDS. Mutates cache in place."""
    if now is None:
        now = time.time()
    cutoff = now - _CACHE_TTL_SECONDS
    ts = cache.get("ts", {})
    for section in ("geocode", "route"):
        if section not in cache:
            continue
        expired = [
            k for k in list(cache[section])
            if ts.get(f"{section}:{k}", 0) < cutoff
        ]
        for k in expired:
            del cache[section][k]
            ts.pop(f"{section}:{k}", None)
    if ts:
        cache["ts"] = ts
    elif "ts" in cache:
        del cache["ts"]


def load_cache(path):
    """Return the cache dict with expired entries removed, or {} if the
    file is missing, unreadable, or not a JSON object (warns on corrupt)."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("cache root is not an object")
        _purge_expired(data)
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


GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def _http_get_json(url, params):
    """GET `url` with query `params`, return parsed JSON.
    Retries up to 3 times with exponential backoff on HTTP 429.
    Network is isolated here (lazy `requests` import); tests stub this."""
    import requests

    delays = [0] + _BACKOFF_SECONDS
    for i, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code == 429 and i < len(delays) - 1:
            continue
        resp.raise_for_status()
        return resp.json()


def _http_post_json(url, body, headers):
    """POST JSON `body` to `url`, return parsed JSON.
    Retries up to 3 times with exponential backoff on HTTP 429.
    Network is isolated here (lazy `requests` import); tests stub this."""
    import requests

    delays = [0] + _BACKOFF_SECONDS
    for i, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        resp = requests.post(url, json=body, headers=headers, timeout=20)
        if resp.status_code == 429 and i < len(delays) - 1:
            continue
        resp.raise_for_status()
        return resp.json()


def geocode_address(address, api_key):
    """Geocode `address` -> (lat, long). Raises
    TravelError('geocode', ...) on error or no result.
    Retries up to 3 times on OVER_QUERY_LIMIT with exponential backoff."""
    delays = [0] + _BACKOFF_SECONDS
    for i, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            data = _http_get_json(
                GEOCODE_URL, {"address": address, "key": api_key}
            )
        except Exception as exc:
            raise TravelError("geocode", f"request failed: {exc}")
        status = data.get("status")
        results = data.get("results") or []
        if status == "OVER_QUERY_LIMIT" and i < len(delays) - 1:
            continue
        if status != "OK" or not results:
            raise TravelError(
                "geocode", f"{status or 'NO_STATUS'} for {address!r}"
            )
        loc = results[0]["geometry"]["location"]
        return (float(loc["lat"]), float(loc["lng"]))


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
            cache.setdefault("ts", {})[f"geocode:{norm}"] = time.time()
    lat, lng = coords
    key = f"{round(lat, 5)},{round(lng, 5)}"
    route = cache.setdefault("route", {})
    if key in route:
        return route[key]
    minutes = compute_route_minutes(
        (lat, lng), DEFAULT_DESTINATION, api_key
    )
    route[key] = minutes
    cache.setdefault("ts", {})[f"route:{key}"] = time.time()
    return minutes
