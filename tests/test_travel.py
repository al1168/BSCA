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


def test_load_cache_missing_returns_empty(tmp_path):
    assert travel.load_cache(str(tmp_path / "nope.json")) == {}


def test_load_cache_corrupt_returns_empty_and_warns(tmp_path, capsys):
    p = tmp_path / "c.json"
    p.write_text("not json{", encoding="utf-8")
    assert travel.load_cache(str(p)) == {}
    assert "geo cache" in capsys.readouterr().err


def test_cache_round_trip(tmp_path):
    p = str(tmp_path / "c.json")
    data = {"geocode": {"a": [1.0, 2.0]}, "route": {"1.0,2.0": 7}}
    travel.save_cache(p, data)
    assert travel.load_cache(p) == data


def test_load_cache_non_dict_returns_empty(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert travel.load_cache(str(p)) == {}
