"""Parse the Access `SADC Auth` field into a set of weekday numbers.

Encoding: 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat, 7=Sun
(matches datetime.date.isoweekday()).
"""

import re


def get_authorized_weekdays(sadc_auth):
    """Return the set of authorized weekday ints (1-7) parsed from the
    raw `SADC Auth` value. Non-digits are separators; values outside
    1-7 are discarded; None/empty/unparseable -> empty set."""
    if not sadc_auth:
        return set()
    found = re.findall(r"\d+", str(sadc_auth))
    return {n for n in (int(x) for x in found) if 1 <= n <= 7}
