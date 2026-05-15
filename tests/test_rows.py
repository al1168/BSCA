import random
from datetime import date

from monthly_schedule.rules import SCHEDULE_RULES
from monthly_schedule.eligibility import Exclusions
from monthly_schedule.rows import build_rows, TIME_KEYS

AUTH = {1, 3, 4, 5}  # Mon, Wed, Thu, Fri


def test_row_count_and_shape():
    rng = random.Random(0)
    rows = build_rows(2026, 5, AUTH, SCHEDULE_RULES["Default"], rng)
    assert len(rows) == 31
    assert rows[0]["date"] == date(2026, 5, 1)
    assert rows[0]["day"] == "Fri"
    assert rows[1]["day"] == "Sat"


def test_eligible_day_has_times_unauthorized_day_blank():
    rng = random.Random(0)
    rows = build_rows(2026, 5, AUTH, SCHEDULE_RULES["Default"], rng)
    fri = rows[0]   # 2026-05-01 Friday -> authorized
    sat = rows[1]   # 2026-05-02 Saturday -> not authorized
    assert all(fri[k] != "" for k in TIME_KEYS)
    assert all(sat[k] == "" for k in TIME_KEYS)


def test_exclusions_blank_out_authorized_day():
    rng = random.Random(0)
    exc = Exclusions(ranges=((date(2026, 5, 11), date(2026, 5, 16)),))
    rows = build_rows(2026, 5, AUTH, SCHEDULE_RULES["Default"], rng, exc)
    # 2026-05-11 is Monday (authorized) but excluded
    may11 = next(r for r in rows if r["date"] == date(2026, 5, 11))
    assert all(may11[k] == "" for k in TIME_KEYS)
