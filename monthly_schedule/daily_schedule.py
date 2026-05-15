"""Generate one coherent daily schedule and assert its invariants.

The two output tables (attendance + transportation) are both derived
from the same Arrival/Departure anchors so they stay mutually
consistent (spec §4b). Only the anchors are snapped by
`round_to_minutes`; derived offsets stay exact so the ordering
invariant cannot be broken by rounding.
"""

from monthly_schedule.rules import parse_hhmm, format_minutes


def _round_to(value, step):
    if step <= 1:
        return value
    return int(round(value / step)) * step


def validate_schedule(pickup, arrival, time_in, time_out, departure, dropoff, rules):
    """Raise ValueError if the generated minutes violate ordering or
    the configured session-length bounds (spec §4b)."""
    if not (pickup < arrival <= time_in):
        raise ValueError(
            f"Start ordering violated: pickup={pickup} arrival={arrival} "
            f"time_in={time_in}"
        )
    if not (time_in <= time_out):
        raise ValueError(
            f"Mid ordering violated: time_in={time_in} time_out={time_out}"
        )
    if not (time_out <= departure < dropoff):
        raise ValueError(
            f"End ordering violated: time_out={time_out} "
            f"departure={departure} dropoff={dropoff}"
        )
    session_hours = (departure - arrival) / 60
    lo = rules["min_session_hours"]
    hi = rules["max_session_hours"]
    if not (lo <= session_hours <= hi):
        raise ValueError(
            f"Session length {session_hours}h outside [{lo}, {hi}]"
        )


def build_daily_schedule(rules, rng):
    """Return a dict of 'HH:MM' strings for one eligible day's visit."""
    a_lo, a_hi = (parse_hhmm(x) for x in rules["arrival_window"])
    d_lo, d_hi = (parse_hhmm(x) for x in rules["departure_window"])
    step = rules["round_to_minutes"]

    arrival = _round_to(rng.randint(a_lo, a_hi), step)
    departure = _round_to(rng.randint(d_lo, d_hi), step)

    pickup = arrival - rng.randint(*rules["pickup_lead_min"])
    dropoff = departure + rng.randint(*rules["dropoff_trail_min"])
    time_in = arrival + rng.randint(*rules["time_in_drift_min"])
    time_out = departure - rng.randint(*rules["time_out_drift_min"])

    validate_schedule(
        pickup, arrival, time_in, time_out, departure, dropoff, rules
    )

    return {
        "pickup": format_minutes(pickup),
        "arrival": format_minutes(arrival),
        "time_in": format_minutes(time_in),
        "time_out": format_minutes(time_out),
        "departure": format_minutes(departure),
        "dropoff": format_minutes(dropoff),
    }
