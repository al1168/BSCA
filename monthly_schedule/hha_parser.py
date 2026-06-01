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
