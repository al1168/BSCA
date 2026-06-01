"""Parse the free-text Contacts.HHA column into Availability writes.

Public surface: parse_hha_row(text) -> dict with keys
  clauses, applied, ambiguous, skipped, ignored,
  ambiguous_reason, attempted_parse.

See docs/superpowers/specs/2026-06-01-hha-availability-backfill-design.md
for the full classification rules. Helpers prefixed with _ are private.
"""
import re

# A loose "time-range-looking substring" pattern: two number groups
# (each up to "12:34" or "12.34") joined by a dash (ASCII or unicode).
# Used by Stage 2 quick reject. We post-filter matches with
# _MARKER_PATTERN below — a real time block must contain ":MM" or
# "am"/"pm" somewhere. This prevents pure day-ranges like "1-7" or
# phone fragments like "390-5496" from being mistaken for times.
_TIME_PATTERN = re.compile(
    r"\d{1,2}\s*[:.]?\s*\d{0,2}\s*(?:am|pm)?"
    r"\s*[-–~]\s*"
    r"\d{1,2}\s*[:.]?\s*\d{0,2}\s*(?:am|pm)?",
    re.IGNORECASE,
)

# A real time block must have ":<digit>" or "am"/"pm" somewhere
# inside. "1-7" and "390-5496" have neither.
_MARKER_PATTERN = re.compile(r":\d|am|pm", re.IGNORECASE)

# Match a single side of a time block: 1-2 digit hour, optional
# minutes via ":MM" or ".MM", optional am/pm suffix. Tolerates
# spaces around the colon ("8: 30PM" is real data).
_TIME_SIDE = re.compile(
    r"(\d{1,2})\s*[:.]?\s*(\d{2})?\s*(am|pm)?",
    re.IGNORECASE,
)

# Match a full time block: <side> <dash> <side>. The dash may be
# ASCII '-' or unicode en-dash. Anchored with re.search so the
# caller can pass a substring or full clause body.
_TIME_BLOCK = re.compile(
    r"(\d{1,2}\s*[:.]?\s*\d{0,2}\s*(?:am|pm)?)"
    r"\s*[-–~]\s*"
    r"(\d{1,2}\s*[:.]?\s*\d{0,2}\s*(?:am|pm)?)",
    re.IGNORECASE,
)


def _parse_one_side(side_text, fallback_suffix):
    """Parse one side of a time block to ('HH', 'MM', 'am'|'pm'|None).
    fallback_suffix is used when the side has no explicit am/pm but the
    other side does."""
    m = _TIME_SIDE.fullmatch(side_text.strip())
    if not m:
        return None
    hour, minute, suffix = m.group(1), m.group(2) or "00", m.group(3)
    if suffix:
        suffix = suffix.lower()
    else:
        suffix = fallback_suffix
    return hour, minute, suffix


def _to_24h(hour, minute, suffix):
    """Convert ('7','30','pm') to '19:30'. suffix may be None
    meaning 'no am/pm and no fallback' — caller decides."""
    h = int(hour)
    m = int(minute)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    if suffix == "pm":
        if h < 12:
            h += 12
    elif suffix == "am":
        if h == 12:
            h = 0
    elif suffix is None:
        # No am/pm anywhere. Caller has already failed if this is
        # unsafe; we just emit the raw hour.
        pass
    return f"{h:02d}:{m:02d}"


def _parse_time_block(text):
    """Return ('HH:MM', 'HH:MM') or None.

    Suffix propagation: if only one side has am/pm, that suffix is
    inferred for the other side. If neither side has a suffix, we
    can't safely classify so return None.
    """
    if not text:
        return None
    m = _TIME_BLOCK.search(text)
    if not m:
        return None
    left_raw, right_raw = m.group(1), m.group(2)
    right = _parse_one_side(right_raw, None)
    if right is None:
        return None
    left = _parse_one_side(left_raw, right[2])
    if left is None:
        return None
    # If right has no suffix either, try left's
    if right[2] is None and left[2] is not None:
        right = (right[0], right[1], left[2])
    if left[2] is None or right[2] is None:
        return None
    start = _to_24h(*left)
    end = _to_24h(*right)
    if start is None or end is None:
        return None
    # Special case: "12am" normally converts to 00:00 (midnight), but
    # when that produces an illogical backwards range (e.g. "8-12am"
    # -> 08:00 to 00:00) treat the 12 as noon (12:00) instead. This
    # matches real-world HHA data where "12am" in a daytime range
    # means midday.
    #
    # The heuristic fires only when left has NO explicit am/pm suffix
    # (it inherited the suffix via fallback from right). When left has
    # an explicit suffix — whether am ("1am-12am") or pm ("11pm-12am")
    # — "12am" genuinely means midnight and we leave end as 00:00.
    left_explicit = _parse_one_side(left_raw, None)
    left_has_explicit_suffix = left_explicit is not None and left_explicit[2] is not None
    if not left_has_explicit_suffix and end <= start and right[0] == "12" and right[2] == "am":
        end = f"12:{right[1]}"
    return (start, end)


def _empty_result():
    return {
        "clauses": [],
        "applied": False,
        "ambiguous": False,
        "skipped": False,
        "ignored": False,
        "ambiguous_reason": None,
        "attempted_parse": "",
    }


def _has_time_pattern(text):
    """True iff text contains at least one time-range substring with
    an explicit time marker (':MM' or 'am'/'pm')."""
    for m in _TIME_PATTERN.finditer(text):
        if _MARKER_PATTERN.search(m.group(0)):
            return True
    return False


def parse_hha_row(text):
    if text is None or not text.strip():
        return {**_empty_result(), "ignored": True}
    if not _has_time_pattern(text):
        return {**_empty_result(), "ignored": True}
    # No further stages wired yet — placeholder.
    return {**_empty_result(), "ignored": True}
