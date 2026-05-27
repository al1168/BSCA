"""Per-member view of the four supporting tables, with most-recent-wins
date lookups."""

from datetime import date


class MemberContext:
    """Holds a member's enrollment / authorization / absence /
    availability rows (as dicts from db.py) and answers per-day queries.

    On overlapping rows the latest start-date wins; ties on start break
    to the largest `id` (deliberate, see spec section "Overlap Resolution").
    """

    def __init__(self, enrollments, authorizations, absences, availabilities):
        self._enrollments = list(enrollments)
        self._authorizations = list(authorizations)
        self._absences = list(absences)
        self._availabilities = list(availabilities)

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
