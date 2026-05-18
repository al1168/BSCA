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
