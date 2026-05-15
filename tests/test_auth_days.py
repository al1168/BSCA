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
