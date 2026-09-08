"""The center's own calendar: company holidays plus weekly operating
hours, read once per run from the Holidays and OperatingDays tables.

Two questions, one object:
  - `closed_reason(day)`: is the center closed that day, and why?
  - `rules_for(day, plan_rules)`: the plan rules with that weekday's
    opening/closing time substituted for earliest_time_in /
    latest_time_out, so everything downstream keeps reading the same
    two keys.

`CenterCalendar.always_open()` is the no-information calendar (no
holidays, no weekday restriction, rules untouched) used by callers and
tests that don't load the tables.
"""

DAY_NAME = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday",
            5: "Friday", 6: "Saturday", 7: "Sunday"}


class CenterCalendar:
    def __init__(self, holidays=(), operating_days=None):
        """`holidays`: dicts from db.get_holidays ({id, name, date}).
        `operating_days`: dicts from db.get_operating_days ({id,
        day_of_week, opening_time, closing_time, ...}) or None for
        "no weekday information" (every weekday open, rules untouched).
        An empty list means every weekday is closed — that is what the
        table says when staff uncheck all seven days."""
        self._holidays = {}
        for row in holidays:
            day = row.get("date")
            if day is None or day in self._holidays:
                continue
            self._holidays[day] = str(row.get("name") or "").strip()

        if operating_days is None:
            self._days = None
        else:
            # Hand edits in Access could leave two rows for a weekday;
            # the newest (largest ID) wins.
            self._days = {}
            for row in operating_days:
                dow = row["day_of_week"]
                current = self._days.get(dow)
                if current is None or row["id"] > current["id"]:
                    self._days[dow] = row

    @classmethod
    def always_open(cls):
        return cls((), None)

    def closed_reason(self, day):
        """`day` is a datetime.date. ("holiday", name) when `day` is a
        company holiday, ("weekday", None) when its weekday has no
        OperatingDays row, else None. Holidays are checked first so
        the debug report names the holiday even on an otherwise-closed
        weekday."""
        if day in self._holidays:
            return ("holiday", self._holidays[day])
        if self._days is not None and day.isoweekday() not in self._days:
            return ("weekday", None)
        return None

    def is_closed(self, day) -> bool:
        return self.closed_reason(day) is not None

    def rules_for(self, day, plan_rules):
        """`day` is a datetime.date. `plan_rules` with earliest_time_in
        / latest_time_out replaced by the weekday's opening / closing
        time. Returns `plan_rules` itself (not a copy) when there is
        nothing to substitute."""
        if self._days is None:
            return plan_rules
        row = self._days.get(day.isoweekday())
        if row is None:
            return plan_rules
        merged = dict(plan_rules)
        merged["earliest_time_in"] = row["opening_time"]
        merged["latest_time_out"] = row["closing_time"]
        return merged
