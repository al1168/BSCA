"""Pure logic for estimating Availability windows from Attendance sheets.

No IO, no DB. See
docs/superpowers/specs/2026-09-15-attendance-availability-backfill-design.md
"""
import datetime
import re
from dataclasses import dataclass, field

# Attendance sheets store clock times in 12-hour form without AM/PM.
# Anything before this is read as PM (a member never signs in before 06:00).
PM_CUTOFF_MIN = 6 * 60


def hhmm(minutes):
    """Minutes since midnight -> 'HH:MM'."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _apply_pm_rule(minutes):
    return minutes + 12 * 60 if minutes < PM_CUTOFF_MIN else minutes


def normalize_time(value):
    """Cell value -> minutes since midnight, or None when blank/unparseable.

    Accepts datetime.time, datetime.datetime (Access placeholder date),
    an Excel day fraction, or an 'H:MM' string. Values before 06:00 are
    read as PM.
    """
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        value = value.time()
    if isinstance(value, datetime.time):
        return _apply_pm_rule(value.hour * 60 + value.minute)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _apply_pm_rule(int(round(value * 24 * 60)) % (24 * 60))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
        if not m:
            return None
        return _apply_pm_rule(int(m.group(1)) * 60 + int(m.group(2)))
    return None


_FILENAME_RE = re.compile(
    r"^\((\d+)\)\.(.+?)\s+Attendance\s+(\d{4}-\d{2})\.xlsm$", re.IGNORECASE,
)


def parse_sheet_filename(name):
    """'(1001).Zhang, Mingli Attendance 2026-08.xlsm'
    -> (1001, 'Zhang, Mingli', '2026-08'); None for anything else
    (Excel lock files starting with '~$' included)."""
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    return int(m.group(1)), m.group(2).strip(), m.group(3)


def collect_samples(rows):
    """Group (center_id, iso_weekday, in_min, out_min) rows into
    {(center_id, weekday): [(in, out), ...]}.

    Rows with either time missing are skipped silently (a day with no
    visit). Rows whose Time-Out is not after Time-In are dropped and
    counted; returns (samples, dropped_count).
    """
    samples = {}
    dropped = 0
    for center_id, weekday, time_in, time_out in rows:
        if time_in is None or time_out is None:
            continue
        if time_out <= time_in:
            dropped += 1
            continue
        samples.setdefault((center_id, weekday), []).append(
            (time_in, time_out))
    return samples, dropped


ROUND_STEP_MIN = 5
AFTERNOON_START_MIN = 10 * 60 + 30   # Time-In at/after this -> afternoon_only
NARROW_WIDTH_MIN = 240               # under this -> narrow


def round_window(start, end):
    """Round start DOWN and end UP to ROUND_STEP_MIN (outward)."""
    lo = (start // ROUND_STEP_MIN) * ROUND_STEP_MIN
    hi = -(-end // ROUND_STEP_MIN) * ROUND_STEP_MIN
    return lo, hi


def window_flags(start, end, closing_min):
    """Report flags for a window against the day's closing time.
    Order is fixed: past_close, afternoon_only, narrow."""
    flags = []
    if end > closing_min:
        flags.append("past_close")
    if start >= AFTERNOON_START_MIN:
        flags.append("afternoon_only")
    if end - start < NARROW_WIDTH_MIN:
        flags.append("narrow")
    return flags


DEFAULT_MIN_SAMPLES = 4


@dataclass
class Estimate:
    """One weekday's estimated window (minutes since midnight, already
    rounded) with the per-weekday sample count and provenance flags
    (subset of: low_samples, member_wide)."""
    start: int
    end: int
    samples: int
    flags: list = field(default_factory=list)


def _envelope(pairs):
    return min(p[0] for p in pairs), max(p[1] for p in pairs)


def estimate_windows(samples_by_weekday, min_samples=DEFAULT_MIN_SAMPLES):
    """Spec §3. `samples_by_weekday` is {iso_weekday: [(in, out), ...]}
    for ONE member. Returns {1..7: Estimate}, or {} when the member has
    no samples at all.

    - A weekday with >= min_samples samples gets its own envelope.
    - A weekday with 1..min_samples-1 samples gets the union of its own
      envelope and the member-wide envelope (flag low_samples).
    - A weekday with no samples gets the member-wide envelope
      (flag member_wide).
    Windows are rounded outward to 5 minutes.
    """
    all_pairs = [p for pairs in samples_by_weekday.values() for p in pairs]
    if not all_pairs:
        return {}
    member_lo, member_hi = _envelope(all_pairs)

    result = {}
    for weekday in range(1, 8):
        pairs = samples_by_weekday.get(weekday) or []
        flags = []
        if not pairs:
            lo, hi = member_lo, member_hi
            flags.append("member_wide")
        else:
            lo, hi = _envelope(pairs)
            if len(pairs) < min_samples:
                lo, hi = min(lo, member_lo), max(hi, member_hi)
                flags.append("low_samples")
        lo, hi = round_window(lo, hi)
        result[weekday] = Estimate(start=lo, end=hi, samples=len(pairs),
                                   flags=flags)
    return result
