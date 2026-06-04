"""Parse the Access `SADC` field into a set of weekday numbers.

Encoding: 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat, 7=Sun
(matches datetime.date.isoweekday()).
"""

import re


_ARROW_SPLIT = re.compile(r"-+>")
_PAREN_STRIP = re.compile(r"\([^)]*\)")
_HAS_ASCII_ALPHA = re.compile(r"[A-Za-z]")
_DIGITS = re.compile(r"\d+")


def _digits_in_range(text):
    return {int(n) for n in _DIGITS.findall(text) if 1 <= int(n) <= 7}


def get_authorized_weekdays(sadc_auth):
    """Return the set of authorized weekday ints (1-7) parsed from the
    raw `SADC` value.

    Notation handled (grounded in the audit at
    `scripts/audit_sadc.py`):

    - **Plain digit lists** with any separators: `"1.2.3"`, `"1,2,3"`,
      `"1 3 4 5"`.
    - **Parenthetical annotations are stripped** before parsing, so
      digits in dates/times don't leak through:
      `"1.4.5.6(7/23/25)"` -> `{1,4,5,6}`,
      `"3.4.5.6.7(9am-1pm)"` -> `{3,4,5,6,7}`,
      `"1.2.3(早上)"` -> `{1,2,3}`.
    - **Supersession via `->`** (also `-->`, `--->`): the right-hand
      segment represents the current authorization. If it parses to a
      non-empty 1-7 set, it wins:
      `"1.2.3.4.5.6.7->1.2.3"` -> `{1,2,3}`,
      `"1.2.3.4.5.6.7->1.3.5(4/6/26)"` -> `{1,3,5}`.
      If the right side contains ASCII letters (`"3DAYS"`,
      `"2 days per week"`), it's treated as free-text and we fall
      back to the left segment:
      `"1.2.3.4.5.6.7->3DAYS"` -> `{1,2,3,4,5,6,7}`.
    - **Multiple arrows** are walked right-to-left; the first segment
      that's a valid list wins:
      `"2.3.4 (4/1/26)->3.4.5(5/1/26)"` -> `{3,4,5}`.

    None/empty/unparseable -> empty set.
    """
    if not sadc_auth:
        return set()
    s = _PAREN_STRIP.sub("", str(sadc_auth))
    parts = _ARROW_SPLIT.split(s)
    for part in reversed(parts):
        if _HAS_ASCII_ALPHA.search(part):
            continue
        days = _digits_in_range(part)
        if days:
            return days
    return _digits_in_range(s)


def format_auth_days(days):
    """Inverse of get_authorized_weekdays: render a set of weekday
    ints (1-7) as the canonical "d,d,d" form used by the Access
    `auth_days` column. Empty set -> empty string."""
    return ",".join(str(n) for n in sorted(days))
