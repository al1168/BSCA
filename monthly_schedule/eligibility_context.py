"""Per-member view of the four supporting tables, with most-recent-wins
date lookups."""

from datetime import date


class MemberContext:
    """Holds a member's enrollment / authorization / absence /
    availability rows (as dicts from db.py) and answers per-day queries.

    On overlapping rows the latest start-date wins; ties on start break
    to the largest `id` (deliberate, see spec section "Overlap Resolution").
    """

    def __init__(self, enrollments, authorizations, absences,
                 availabilities, one_offs):
        self._enrollments = list(enrollments)
        self._authorizations = list(authorizations)
        self._absences = list(absences)
        self._availabilities = list(availabilities)
        self._one_offs = list(one_offs)

    def is_enrolled(self, day: date) -> bool:
        for row in self._enrollments:
            start = row["start_date"]
            end = row["end_date"]
            if start <= day and (end is None or day <= end):
                return True
        return False

    def active_authorization(self, day: date):
        candidates = [
            row for row in self._authorizations
            if row["effective_start"] <= day <= row["effective_end"]
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: (r["effective_start"], r["id"]))

    def is_absent(self, day: date) -> bool:
        for row in self._absences:
            if row["start_date"] <= day <= row["end_date"]:
                return True
        return False

    def availability_for(self, day: date):
        """Return the most relevant Availability row for `day`'s weekday
        whose effective-date window includes `day`. effective_end_date
        is nullable (NULL = ongoing). Tie-break: latest
        effective_start_date, then largest `id`."""
        weekday = day.isoweekday()
        candidates = []
        for row in self._availabilities:
            if row["day_of_week"] != weekday:
                continue
            start = row["effective_start_date"]
            end = row["effective_end_date"]
            if start <= day and (end is None or day <= end):
                candidates.append(row)
        if not candidates:
            return None
        return max(candidates, key=lambda r: (r["effective_start_date"], r["id"]))

    def one_offs_for(self, day: date):
        """Return list of one-off rows whose date equals `day`.

        Empty list if none. May contain more than one row — the caller
        (compute_day_eligibility) flags the duplicate as a conflict."""
        return [r for r in self._one_offs if r["date"] == day]
