import pytest

from monthly_schedule import travel


def test_default_destination_is_lat_long():
    assert travel.DEFAULT_DESTINATION == (40.7165774, -73.9954078)


def test_travel_error_carries_stage_and_reason():
    e = travel.TravelError("geocode", "boom")
    assert e.stage == "geocode"
    assert e.reason == "boom"
    assert isinstance(e, Exception)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("40.7165774,-73.9954078", (40.7165774, -73.9954078)),
        (" 40.7 , -73.9 ", (40.7, -73.9)),
        ("", None),
        (None, None),
        ("abc", None),
        ("1", None),
        ("1,2,3", None),
    ],
)
def test_parse_long_lat(text, expected):
    assert travel.parse_long_lat(text) == expected


def test_normalize_address():
    assert travel.normalize_address("  123  Main   St ") == "123 main st"
    assert travel.normalize_address("A,B") == "a,b"
