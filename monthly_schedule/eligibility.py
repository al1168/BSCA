"""The single seam deciding whether a date should get generated times.

Today it checks only the authorized-weekday rule. The optional
`exclusions` argument is the future plug-in point for vacation ranges,
termination dates, auth-period limits, and other visit types
(spec §4a). With the default empty exclusions, behavior is unchanged.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Tuple


@dataclass(frozen=True)
class Exclusions:
    """ranges: tuple of (start_date, end_date) inclusive vacation ranges.
    termination_date: if set, this date and all later dates are ineligible."""

    ranges: Tuple[Tuple[date, date], ...] = field(default_factory=tuple)
    termination_date: Optional[date] = None


def is_day_eligible(day, authorized_weekdays, exclusions=None):
    """Return True if `day` should get generated times."""
    if day.isoweekday() not in authorized_weekdays:
        return False
    if exclusions is None:
        return True
    if (
        exclusions.termination_date is not None
        and day >= exclusions.termination_date
    ):
        return False
    for start, end in exclusions.ranges:
        if start <= day <= end:
            return False
    return True
