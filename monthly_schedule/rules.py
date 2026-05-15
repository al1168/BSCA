"""Tunable, per-plan time-generation rules (spec §4b).

Adding a restriction = change a number here, or add a key and one
clamp/validation line in daily_schedule.validate_schedule.
"""

SCHEDULE_RULES = {
    "Default": {
        "arrival_window": ("08:05", "08:25"),
        "departure_window": ("12:05", "12:25"),
        "min_session_hours": 3,
        "max_session_hours": 6,
        "pickup_lead_min": (8, 12),     # minutes before Arrival
        "dropoff_trail_min": (8, 12),   # minutes after Departure
        "time_in_drift_min": (0, 3),    # Time-In after Arrival
        "time_out_drift_min": (0, 3),   # Time-Out before Departure
        "round_to_minutes": 1,          # 1 = no snap; 5 = snap to :05
    },
}


def get_rules_for_plan(health_plan):
    """Return the rules dict for the member's plan, falling back to
    'Default' when the plan has no specific entry."""
    if health_plan and health_plan in SCHEDULE_RULES:
        return SCHEDULE_RULES[health_plan]
    return SCHEDULE_RULES["Default"]


def parse_hhmm(text):
    """'HH:MM' -> minutes since midnight."""
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def format_minutes(total):
    """Minutes since midnight -> 'HH:MM' (wraps within a 24h day)."""
    total %= 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"
