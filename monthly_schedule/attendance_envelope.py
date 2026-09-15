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
