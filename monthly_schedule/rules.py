"""Tunable, per-plan time-generation rules (spec §4b).

Adding a restriction = change a number here, or add a key and one
clamp/validation line in daily_schedule.validate_schedule.
"""

import hashlib

SCHEDULE_RULES = {
    "Default": {
        # Fallback day bounds. In a real run each weekday's bounds come
        # from the OperatingDays table via CenterCalendar.rules_for.
        "earliest_time_in": "08:00",
        "latest_time_out": "16:00",
        # Visit length measured Time-In -> Time-Out (minutes). A random
        # block of this size is placed anywhere inside the member's
        # availability, clipped to the bounds above.
        "session_length_min": (210, 240),   # 3h30m .. 4h00m
        "pickup_lead_min": (8, 12),       # minutes before Arrival
        "dropoff_trail_min": (8, 12),     # minutes after Departure
        "time_in_drift_min": (2, 2),      # Time-In = Arrival + 2 min
        "time_out_drift_min": (2, 2),     # Time-Out = Departure - 2 min
        "round_to_minutes": 1,            # 1 = no snap; 5 = snap to :05
        "travel_buffer_min": (1, 5),      # random buffer added to Google travel time
        # When truthy: on days with a RECURRING availability ending
        # before latest_time_out, Drop-Off must land at or before that
        # end (home care starts then). Enforced by shrinking the
        # placement window in per_day.compute_day_eligibility.
        "dropoff_by_avail_end": True,
        # When truthy: on days with a RECURRING availability starting
        # after earliest_time_in, the member is busy before avail_start,
        # so Pick-Up must not precede it. Enforced by shrinking the
        # placement window in per_day.compute_day_eligibility.
        "pickup_by_avail_start": True,
        # Morning/afternoon distribution (opt-in; spec 2026-07-23).
        # While band_enabled is falsy, Time-In placement is uniform,
        # exactly as before — pins and percentages are ignored.
        "band_enabled": False,
        "morning_percent": 80,       # % of members assigned morning
        "morning_window_min": 180,   # band length from earliest_time_in
        "morning_members": (),       # center_ids pinned morning
        "afternoon_members": (),     # center_ids pinned afternoon
    },
}


def get_rules_for_plan(health_plan, overrides=None):
    """Return the rules dict for the member's plan, falling back to
    'Default' when the plan has no specific entry.

    `overrides` is an optional dict of user-configured values that
    replace the built-in defaults (e.g., the GUI's Scheduling Rules
    section in Settings). Ranges that arrive as lists (from JSON)
    are converted to tuples so callers' tuple-unpacking still works.
    """
    if health_plan and health_plan in SCHEDULE_RULES:
        base = SCHEDULE_RULES[health_plan]
    else:
        base = SCHEDULE_RULES["Default"]
    if not overrides:
        return base
    merged = dict(base)
    for key, value in overrides.items():
        if value is None:
            continue
        merged[key] = tuple(value) if isinstance(value, list) else value
    return merged


def parse_hhmm(text):
    """'HH:MM' -> minutes since midnight."""
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def format_minutes(total):
    """Minutes since midnight -> 'HH:MM' (wraps within a 24h day)."""
    total %= 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"


def band_for_member(center_id, rules):
    """Return 'morning'/'afternoon' for this member, or None when the
    distribution feature is off (or center_id is unknown).

    Pins win over the hash; morning wins if an id is (defensively) in
    both lists. The md5 bucket is stable across runs and months, so a
    member keeps their band until the settings change. Non-integer
    entries in hand-edited pin lists are ignored.
    """
    if not rules.get("band_enabled") or center_id is None:
        return None
    try:
        member_id = int(center_id)
    except (TypeError, ValueError):
        return None

    def pinned(key):
        for raw in rules.get(key) or ():
            try:
                if int(raw) == member_id:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    if pinned("morning_members"):
        return "morning"
    if pinned("afternoon_members"):
        return "afternoon"
    digest = hashlib.md5(
        str(member_id).encode("ascii"), usedforsecurity=False
    ).hexdigest()
    bucket = int(digest, 16) % 100
    if bucket < rules.get("morning_percent", 80):
        return "morning"
    return "afternoon"
