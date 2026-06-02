import pytest

from monthly_schedule.auth_days import get_authorized_weekdays


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.3.4.5", {1, 3, 4, 5}),
        ("1,3,4,5", {1, 3, 4, 5}),
        ("1 3 4 5", {1, 3, 4, 5}),
        ("", set()),
        (None, set()),
        ("0.8.9", set()),          # all out of range -> discarded
        ("1.2.3.4.5.6.7", {1, 2, 3, 4, 5, 6, 7}),
        ("garbage", set()),
        ("3", {3}),
    ],
)
def test_get_authorized_weekdays(raw, expected):
    assert get_authorized_weekdays(raw) == expected


from monthly_schedule.auth_days import format_auth_days


@pytest.mark.parametrize(
    "days,expected",
    [
        ({1, 3, 5}, "1,3,5"),
        ({5, 1, 3}, "1,3,5"),       # sorted
        (set(), ""),                # empty -> empty string
        ({1}, "1"),
        ({1, 2, 3, 4, 5, 6, 7}, "1,2,3,4,5,6,7"),
    ],
)
def test_format_auth_days(days, expected):
    assert format_auth_days(days) == expected
