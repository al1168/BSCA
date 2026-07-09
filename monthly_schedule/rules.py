"""Tunable, per-plan time-generation rules (spec §4b).

Adding a restriction = change a number here, or add a key and one
clamp/validation line in daily_schedule.validate_schedule.
"""

SCHEDULE_RULES = {
    "Default": {
        # Hard day bounds: the attendance block must not start (Time-In)
        # before this, nor end (Time-Out) after it.
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
