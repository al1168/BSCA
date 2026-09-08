from datetime import date

from monthly_schedule.center_calendar import CenterCalendar, DAY_NAME


PLAN_RULES = {
    "earliest_time_in": "08:00",
    "latest_time_out": "16:00",
    "session_length_min": (210, 240),
}


def _open(*days, opening="08:00", closing="16:00", first_id=1):
    return [
        {"id": first_id + i, "day_name": DAY_NAME[d], "day_of_week": d,
         "opening_time": opening, "closing_time": closing}
        for i, d in enumerate(days)
    ]


ALL_WEEK = _open(1, 2, 3, 4, 5, 6, 7)
MON = date(2026, 5, 4)      # Monday
SUN = date(2026, 5, 3)      # Sunday


def test_holiday_is_closed_with_name():
    cal = CenterCalendar(
        [{"id": 1, "name": "Labor Day", "date": MON}], ALL_WEEK)
    assert cal.closed_reason(MON) == ("holiday", "Labor Day")
    assert cal.is_closed(MON) is True


def test_weekday_without_row_is_closed():
    cal = CenterCalendar([], _open(1, 2, 3, 4, 5))
    assert cal.closed_reason(SUN) == ("weekday", None)
    assert cal.closed_reason(MON) is None


def test_holiday_wins_over_closed_weekday():
    cal = CenterCalendar(
        [{"id": 1, "name": "Easter", "date": SUN}], _open(1, 2, 3, 4, 5))
    assert cal.closed_reason(SUN) == ("holiday", "Easter")


def test_holiday_with_null_date_is_ignored():
    cal = CenterCalendar([{"id": 1, "name": "x", "date": None}], ALL_WEEK)
    assert cal.closed_reason(MON) is None


def test_rules_for_substitutes_weekday_hours():
    cal = CenterCalendar([], _open(1, opening="09:30", closing="15:00"))
    rules = cal.rules_for(MON, PLAN_RULES)
    assert rules["earliest_time_in"] == "09:30"
    assert rules["latest_time_out"] == "15:00"
    assert rules["session_length_min"] == (210, 240)
    assert PLAN_RULES["earliest_time_in"] == "08:00"   # input untouched


def test_rules_for_closed_weekday_returns_plan_rules():
    cal = CenterCalendar([], _open(1))
    assert cal.rules_for(SUN, PLAN_RULES) is PLAN_RULES


def test_always_open_never_closes_and_keeps_rules():
    cal = CenterCalendar.always_open()
    assert cal.closed_reason(SUN) is None
    assert cal.rules_for(SUN, PLAN_RULES) is PLAN_RULES


def test_empty_operating_days_closes_every_weekday():
    cal = CenterCalendar([], [])
    assert cal.closed_reason(MON) == ("weekday", None)


def test_duplicate_weekday_rows_largest_id_wins():
    rows = _open(1, opening="08:00") + _open(1, opening="10:00", first_id=9)
    cal = CenterCalendar([], rows)
    assert cal.rules_for(MON, PLAN_RULES)["earliest_time_in"] == "10:00"
