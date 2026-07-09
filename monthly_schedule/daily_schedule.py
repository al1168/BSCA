"""Generate one coherent daily schedule and assert its invariants.

A single attendance block (Time-In -> Time-Out) of a random length is
placed anywhere inside the member's availability, clipped to the hard
day bounds (Time-In not before `earliest_time_in`, Time-Out not after
`latest_time_out`). The transport anchors (Arrival/Departure) and the
two tables are derived from that block so they stay mutually consistent
(spec §4b). Only the anchors are snapped by `round_to_minutes`; derived
offsets stay exact so the ordering invariant cannot be broken by
rounding.
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
    length = time_out - time_in
    lo, hi = rules["session_length_min"]
    if not (lo <= length <= hi):
        raise ValueError(
            f"Session length {length} min outside [{lo}, {hi}]"
        )


def build_daily_schedule(rules, rng, window=None):
    """Return a dict of 'HH:MM' strings for one eligible day's visit.

    `window` (optional) is a (in_lo, out_hi) tuple in minutes: the
    earliest allowed Time-In and the latest allowed Time-Out for the
    day, already narrowed by the member's availability. When omitted it
    defaults to the plan's `earliest_time_in`/`latest_time_out` bounds
    (the open-day case, member with no availability rule).

    A random length is drawn from `session_length_min`, capped to the
    free time in the window, and the block is dropped at a random
    position so the whole of it (Time-In .. Time-Out) fits inside the
    window. Arrival/Departure and pickup/drop-off are derived around it.
    """
    if window is None:
        in_lo = parse_hhmm(rules["earliest_time_in"])
        out_hi = parse_hhmm(rules["latest_time_out"])
    else:
        in_lo, out_hi = window
    step = rules["round_to_minutes"]

    len_lo, len_hi = rules["session_length_min"]
    # Cap the length at the free time in the window; never below the
    # configured minimum (callers guarantee the window is at least that
    # wide, but max() keeps a too-narrow window from crashing).
    len_hi = max(len_lo, min(len_hi, out_hi - in_lo))
    length = rng.randint(len_lo, len_hi)

    # Place the block: Time-In anywhere that keeps Time-Out <= out_hi.
    latest_in = max(in_lo, out_hi - length)
    time_in = _round_to(rng.randint(in_lo, latest_in), step)
    # Snapping can nudge Time-In past the edges — clamp so it still fits.
    time_in = min(max(time_in, in_lo), latest_in)
    time_out = time_in + length

    arrival = time_in - rng.randint(*rules["time_in_drift_min"])
    departure = time_out + rng.randint(*rules["time_out_drift_min"])
    pickup = arrival - rng.randint(*rules["pickup_lead_min"])
    dropoff = departure + rng.randint(*rules["dropoff_trail_min"])

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
