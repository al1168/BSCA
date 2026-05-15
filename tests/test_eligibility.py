from datetime import date

from monthly_schedule.eligibility import Exclusions, is_day_eligible

AUTH = {1, 3, 4, 5}  # Mon, Wed, Thu, Fri


def test_authorized_weekday_no_exclusions():
    # 2026-05-01 is a Friday (isoweekday 5)
    assert is_day_eligible(date(2026, 5, 1), AUTH) is True


def test_unauthorized_weekday():
    # 2026-05-02 is a Saturday (isoweekday 6) -> not in AUTH
    assert is_day_eligible(date(2026, 5, 2), AUTH) is False


def test_none_exclusions_equivalent_to_empty():
    assert is_day_eligible(date(2026, 5, 1), AUTH, None) is True


def test_vacation_range_blocks_authorized_day():
    exc = Exclusions(ranges=((date(2026, 5, 10), date(2026, 5, 16)),))
    # 2026-05-11 is a Monday (authorized) but inside the vacation range
    assert is_day_eligible(date(2026, 5, 11), AUTH, exc) is False
    # boundary days are inclusive
    assert is_day_eligible(date(2026, 5, 16), {6}, Exclusions(
        ranges=((date(2026, 5, 10), date(2026, 5, 16)),))) is False


def test_termination_blocks_date_and_after():
    exc = Exclusions(termination_date=date(2026, 5, 10))
    # 2026-05-08 is a Friday (authorized), before termination -> eligible
    assert is_day_eligible(date(2026, 5, 8), AUTH, exc) is True
    # 2026-05-11 Monday (authorized) on/after termination -> ineligible
    assert is_day_eligible(date(2026, 5, 11), AUTH, exc) is False
    # the termination day itself is ineligible (2026-05-11 is Mon; pick
    # an authorized termination day): 2026-05-13 is a Wednesday
    exc2 = Exclusions(termination_date=date(2026, 5, 13))
    assert is_day_eligible(date(2026, 5, 13), AUTH, exc2) is False
