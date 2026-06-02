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
# spaces around the colon ("8: 30PM" is real data). The colon/dot
# separator is required when minutes are present — bare whitespace
# between hour and minute digits is not accepted.
_TIME_SIDE = re.compile(
    r"(\d{1,2})(?:\s*[:.]\s*(\d{1,2}))?\s*(am|pm)?",
    re.IGNORECASE,
)

# Match a full time block: <side> <dash> <side>. The dash may be
# ASCII '-' or unicode en-dash. Anchored with re.search so the
# caller can pass a substring or full clause body. Minutes require
# an explicit colon/dot separator so "3 4-8pm" is not treated as
# a time block (the "3 4" part has no separator).
_TIME_BLOCK = re.compile(
    r"(\d{1,2}(?:\s*[:.]\s*\d{1,2})?\s*(?:am|pm)?)"
    r"\s*[-–~]\s*"
    r"(\d{1,2}(?:\s*[:.]\s*\d{1,2})?\s*(?:am|pm)?)",
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


# Match either a "N-M" range or a single digit N in 1..7.
_DAY_TOKEN = re.compile(r"(\d)\s*-\s*(\d)|(\d)")


def _parse_days(text):
    """Extract day-of-week ints (1..7) from a string fragment.

    Accepts dot-, comma-, or hyphen-separated digits, including ranges
    like '1-5'. Returns a set. Out-of-range digits (0, 8, 9) are
    dropped silently — they're not valid weekdays in this convention
    (1=Mon..7=Sun).
    """
    if not text:
        return set()
    out = set()
    for m in _DAY_TOKEN.finditer(text):
        if m.group(1) and m.group(2):
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo <= hi:
                for d in range(lo, hi + 1):
                    if 1 <= d <= 7:
                        out.add(d)
        elif m.group(3):
            d = int(m.group(3))
            if 1 <= d <= 7:
                out.add(d)
    return out


# Center open/close, baked in per spec.
_CENTER_OPEN = "08:00"
_CENTER_CLOSE = "16:00"


def _split_clauses(text):
    """Yield (days_text, time_text) pairs.

    Strategy: find every time block in `text` via _TIME_BLOCK.finditer
    and post-filter with _MARKER_PATTERN so day-ranges like "1-7" are
    skipped (they get absorbed into the days_text of the next real
    time block).

    For each accepted match, "days_text" is the substring between the
    previous accepted time-end (or start of string) and this match's
    start. Handles both forms naturally:
      "(4.5.6) 2:30-7pm"         -> [("(4.5.6) ", "2:30-7pm")]
      "5.6.7(2pm-6pm)"           -> [("5.6.7(",   "2pm-6pm")]
      "1-7(2-6pm)"               -> [("1-7(",     "2-6pm")]
      "(d1) t1, (d2) t2"         -> [("(d1) ", t1), (", (d2) ", t2)]
      "d1(t1) d2(t2)"            -> [("d1(", t1), (") d2(", t2)]
    """
    pairs = []
    cursor = 0
    for m in _TIME_BLOCK.finditer(text):
        time_text = m.group(0)
        if not _MARKER_PATTERN.search(time_text):
            # Looks dash-joined but no real time marker — skip without
            # advancing cursor so the next accepted clause's days_text
            # subsumes it.
            continue
        days_text = text[cursor:m.start()]
        pairs.append((days_text, time_text))
        cursor = m.end()
    return pairs


def _classify_clause(days, time_block):
    """Given a set of days and a (start, end) tuple, return a Clause
    dict. Pure classification — no side effects.
    """
    if time_block is None:
        return {
            "days": days,
            "avail_end": None,
            "status": "ambiguous",
            "reason": "time_unparseable",
        }
    start, _end = time_block
    if not days:
        return {
            "days": set(),
            "avail_end": None,
            "status": "ambiguous",
            "reason": "days_missing",
        }
    if start >= _CENTER_CLOSE:
        return {
            "days": days,
            "avail_end": None,
            "status": "skip",
            "reason": None,
        }
    if start <= _CENTER_OPEN:
        return {
            "days": days,
            "avail_end": None,
            "status": "ambiguous",
            "reason": "morning_or_pre_open",
        }
    return {
        "days": days,
        "avail_end": start,
        "status": "apply",
        "reason": None,
    }


def _aggregate_row(clauses, attempted_parse):
    """Combine clause outcomes into a ParsedRow dict."""
    applied = any(c["status"] == "apply" for c in clauses)
    ambiguous = any(c["status"] == "ambiguous" for c in clauses)
    skipped_only = (
        not applied and not ambiguous
        and any(c["status"] == "skip" for c in clauses)
    )
    # Reason priority per spec; only set when ambiguous.
    reason = None
    if ambiguous:
        priority = [
            "date_conditioned", "chinese_note", "morning_or_pre_open",
            "time_unparseable", "days_missing", "clause_split_failed",
        ]
        present = {c["reason"] for c in clauses if c["status"] == "ambiguous"}
        for p in priority:
            if p in present:
                reason = p
                break
    return {
        "clauses": clauses,
        "applied": applied,
        "ambiguous": ambiguous,
        "skipped": skipped_only,
        "ignored": False,
        "ambiguous_reason": reason,
        "attempted_parse": attempted_parse,
    }


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
    pairs = _split_clauses(text)
    if not pairs:
        # Time-looking substring exists but the stricter _TIME_BLOCK
        # regex couldn't lock onto a clause. Flag for review.
        return _aggregate_row(
            [{"days": set(), "avail_end": None,
              "status": "ambiguous", "reason": "clause_split_failed"}],
            attempted_parse=f"raw={text!r}",
        )
    # Collect row-wide days so a clause missing its own days can fall
    # back to "all days mentioned elsewhere in the row".
    row_days = set()
    for days_text, _ in pairs:
        row_days |= _parse_days(days_text)
    clauses = []
    for days_text, time_text in pairs:
        days = _parse_days(days_text) or row_days
        time_block = _parse_time_block(time_text)
        clauses.append(_classify_clause(days, time_block))
    attempted = "; ".join(
        f"days={sorted(c['days'])} end={c['avail_end']} "
        f"status={c['status']} reason={c['reason']}"
        for c in clauses
    )
    return _aggregate_row(clauses, attempted)
