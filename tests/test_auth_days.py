import pytest

from monthly_schedule.auth_days import format_auth_days, get_authorized_weekdays


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Plain digit lists, various separators.
        ("1.3.4.5", {1, 3, 4, 5}),
        ("1,3,4,5", {1, 3, 4, 5}),
        ("1 3 4 5", {1, 3, 4, 5}),
        ("1.2.3.4.5.6.7", {1, 2, 3, 4, 5, 6, 7}),
        ("3", {3}),
        ("2", {2}),
        # None / empty / out-of-range / garbage.
        ("", set()),
        (None, set()),
        ("0.8.9", set()),
        ("garbage", set()),
        # Parenthetical annotations stripped (no digit leakage from
        # dates, times, or CJK notes).
        ("3.4.5.6.7(9am-1pm)", {3, 4, 5, 6, 7}),
        ("1.4.5.6(7/23/25)", {1, 4, 5, 6}),
        ("1.2.3.4 (12/16/25)", {1, 2, 3, 4}),
        ("1.2.3.4 (9am-1am)", {1, 2, 3, 4}),
        ("3.5.6 (5/1/26)", {3, 5, 6}),
        ("1.4.6 (9am-1pm)", {1, 4, 6}),
        ("1.2.3(6/10/26)", {1, 2, 3}),
        ("1.2.3.5.7(4/9/26)", {1, 2, 3, 5, 7}),
        ("1.2.3.4.5.6.7(8/15/25)", {1, 2, 3, 4, 5, 6, 7}),
        ("1.2.3 (早上)", {1, 2, 3}),
        ("1.2.3(会员可自己选择时间)", {1, 2, 3}),
        ("1.2.3.4.5.6.7 (SUN 星期日12pm以前)", {1, 2, 3, 4, 5, 6, 7}),
        # Supersession via "->": right side wins when valid.
        ("1.2.3.4.5.6.7->1.2.3", {1, 2, 3}),
        ("1.2.3.4.5.6.7->1.3.5", {1, 3, 5}),
        ("1.2.3.4.5.6.7->1.2", {1, 2}),
        ("1.2.3.4.5.6.7->2.3.4", {2, 3, 4}),
        ("1.2.3.4.5.6.7->2.4.6(6/1/26)", {2, 4, 6}),
        ("1.2.3.4.5.6.7->1.3.5(4/6/26)", {1, 3, 5}),
        ("1.2.3.4.5.6.7->1.2.3 (4/1/26)", {1, 2, 3}),
        ("1.2.3.4.5.6.7->1.2.3.4.5", {1, 2, 3, 4, 5}),
        ("1.2->6.7(7/14/25)", {6, 7}),
        ("3.4.5.6.7->1.2.3", {1, 2, 3}),
        ("1.2.4.5->2.4.5.6(5/4/26)", {2, 4, 5, 6}),
        # "-->" / "--->" arrow variants.
        ("1.2.3.4.5-->4.5(4/1/26)", {4, 5}),
        ("1.2.3.4.5.6.7-->4.5(4/21/26)", {4, 5}),
        # Whitespace around arrows is tolerated.
        ("1.2.3.4.5-> 4.5.6 (4/1/26)", {4, 5, 6}),
        ("1.2.3.4.5.6.7-> 1.3(4/19/26)", {1, 3}),
        ("2.3.4.5.6 ->1.2.3.4.5.6.7", {1, 2, 3, 4, 5, 6, 7}),
        # Right side has ASCII letters -> free-text, fall back to
        # the left segment.
        ("1.2.3.4.5.6.7->3DAYS", {1, 2, 3, 4, 5, 6, 7}),
        ("1.2.3.4.5.6.7->3days", {1, 2, 3, 4, 5, 6, 7}),
        ("1.2.3.4.5.6.7->2days", {1, 2, 3, 4, 5, 6, 7}),
        ("1.2.3.4.5.6.7->2 days per week", {1, 2, 3, 4, 5, 6, 7}),
        ("1.2.3.4.5.6.7->3days (5/5/26)", {1, 2, 3, 4, 5, 6, 7}),
        ("1.2.3.4.5.6.7->3Days per week", {1, 2, 3, 4, 5, 6, 7}),
        ("2.3.4.6.7->3days (6/1/26)", {2, 3, 4, 6, 7}),
        # Multi-arrow chain: rightmost valid segment wins.
        ("2.3.4 (4/1/26)->3.4.5(5/1/26)", {3, 4, 5}),
        # CSV-quoted comma-separated values.
        ("1,2,3,4,5,6,7", {1, 2, 3, 4, 5, 6, 7}),
        ("4,5", {4, 5}),
    ],
)
def test_get_authorized_weekdays(raw, expected):
    assert get_authorized_weekdays(raw) == expected


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
