"""Per-day generated-times cache.

When a member has been partially scheduled (e.g., the 1st through the
19th of May), re-running the scheduler for the full month should reuse
the SAME daily times for days 1..19 rather than re-rolling fresh ones.
Operationally: a printed schedule has already been handed to staff and
the member, so the artifact must stay stable across reruns.

The cache is a JSON file keyed by `(center_id, YYYY-MM-DD)`. Each entry
stores the six time fields plus the `plan` and `travel_minutes` that
produced them; on lookup the entry is invalidated (dropped) when:
  * the current plan differs from the stored plan, OR
  * the current travel_minutes differs, OR
  * the cached block (Time-In .. Time-Out) no longer fits inside the
    current placement window (member's availability changed, day bounds
    shifted, etc.).

Independent of geo_cache.json so it can be backed up / cleared on its
own (and so corruption in one doesn't affect the other).
"""

import json
import os
import sys

from monthly_schedule.rules import parse_hhmm


def load_time_cache(path):
    """Return the cache dict from `path`, or {} if the file is missing,
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
            f"Warning: ignoring unreadable time cache {path}: {exc}",
            file=sys.stderr,
        )
        return {}


def save_time_cache(path, cache):
    """Write the cache dict as pretty JSON (UTF-8)."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2, sort_keys=True)


_TIME_KEYS = ("pickup", "arrival", "time_in", "time_out",
              "departure", "dropoff")


def _entry_valid(entry, plan, travel_minutes, window):
    """Is the cached entry still authoritative under current rules?
    Checks plan + travel match and that the cached block (Time-In ..
    Time-Out) still fits inside the current placement window."""
    if entry.get("plan") != plan:
        return False
    if entry.get("travel_minutes") != travel_minutes:
        return False
    try:
        time_in = parse_hhmm(entry["time_in"])
        time_out = parse_hhmm(entry["time_out"])
    except (KeyError, ValueError):
        return False
    lo, hi = window
    return lo <= time_in and time_out <= hi


def lookup_times(cache, center_id, day,
                  plan, travel_minutes, window):
    """Return the cached times dict for (center_id, day) if it is still
    valid under the current plan/travel/window. Otherwise return None
    and (as a side effect) drop the stale entry so save_time_cache won't
    preserve it."""
    members = cache.get("members", {})
    member = members.get(str(center_id))
    if not member:
        return None
    iso = day.isoformat()
    entry = member.get(iso)
    if entry is None:
        return None
    if not _entry_valid(entry, plan, travel_minutes, window):
        del member[iso]
        if not member:
            del members[str(center_id)]
        return None
    return {k: entry[k] for k in _TIME_KEYS}


def store_times(cache, center_id, day, times,
                 plan, travel_minutes):
    """Add (or overwrite) the cache entry for (center_id, day) with
    `times` (a dict produced by build_daily_schedule) plus the plan +
    travel_minutes that produced them (used to invalidate later)."""
    members = cache.setdefault("members", {})
    member = members.setdefault(str(center_id), {})
    member[day.isoformat()] = {
        **{k: times[k] for k in _TIME_KEYS},
        "plan": plan,
        "travel_minutes": travel_minutes,
    }
