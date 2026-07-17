"""Parse reviewed HHA answer strings and subtract home-care windows
from availability windows. Pure logic — no DB, no IO.

Answer grammar (spec §3): pipe-separated groups of `days (start - end)`,
days dot-separated ISO weekdays 1-7, times `H[:MM]` with AM/PM on each
side, whitespace flexible:

    1.5 (8:30 AM - 5:30 PM) | 3.6 (12 PM - 5 PM) | 7 (12:30 PM - 2:30 PM)

Times are minutes since midnight throughout this module.
"""
import re


class AnswerParseError(ValueError):
    """An answer string that cannot be safely interpreted. Callers flag
    the whole row for review rather than guessing."""


_GROUP_RE = re.compile(r"^\s*([0-9.]+?)\s*\(\s*([^)]+?)\s*\)\s*$")
_TIME_RE = re.compile(r"^(\d{1,2})(?::([0-5]\d))?\s*(am|pm)$", re.IGNORECASE)


def parse_time(text):
    """'8:30 AM' -> 510. Hour 1-12 with AM/PM required; 12 AM -> 0,
    12 PM -> 720 (noon)."""
    m = _TIME_RE.match(text.strip())
    if not m:
        raise AnswerParseError(f"unparseable time: {text!r}")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    if not 1 <= hour <= 12:
        raise AnswerParseError(f"hour out of range: {text!r}")
    if hour == 12:
        hour = 0
    if m.group(3).lower() == "pm":
        hour += 12
    return hour * 60 + minute


def parse_answer(text):
    """Parse one answer cell into a list of
    `{"days": set[int], "start": int, "end": int}` groups.
    Raises AnswerParseError on anything malformed — no guessing."""
    groups = []
    for part in text.split("|"):
        m = _GROUP_RE.match(part)
        if not m:
            raise AnswerParseError(f"unrecognized group: {part.strip()!r}")
        days_raw, time_raw = m.group(1), m.group(2)
        days = set()
        for tok in days_raw.split("."):
            tok = tok.strip()
            if not tok:
                continue
            if not tok.isdigit() or not 1 <= int(tok) <= 7:
                raise AnswerParseError(
                    f"bad day {tok!r} in group {part.strip()!r}")
            days.add(int(tok))
        if not days:
            raise AnswerParseError(f"no days in group {part.strip()!r}")
        sides = time_raw.split("-")
        if len(sides) != 2:
            raise AnswerParseError(
                f"bad time block in group {part.strip()!r}")
        start, end = parse_time(sides[0]), parse_time(sides[1])
        if start >= end:
            raise AnswerParseError(
                f"start not before end in group {part.strip()!r}")
        groups.append({"days": days, "start": start, "end": end})
    return groups


def subtract_care_window(avail, care):
    raise NotImplementedError  # Task 2


def hhmm(minutes):
    """510 -> '08:30'."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
