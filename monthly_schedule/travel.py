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
