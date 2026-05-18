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


def test_load_api_key_reads_trimmed(tmp_path):
    p = tmp_path / "k.config"
    p.write_text("  my-secret-key\n", encoding="utf-8")
    assert travel.load_api_key(str(p)) == "my-secret-key"


def test_load_api_key_missing_raises(tmp_path):
    with pytest.raises(RuntimeError):
        travel.load_api_key(str(tmp_path / "absent.config"))


def test_load_api_key_empty_raises(tmp_path):
    p = tmp_path / "k.config"
    p.write_text("   \n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        travel.load_api_key(str(p))


def test_geocode_address_ok(monkeypatch):
    def fake_get(url, params):
        assert params["address"] == "1 Main St"
        assert params["key"] == "K"
        return {
            "status": "OK",
            "results": [
                {"geometry": {"location": {"lat": 40.5, "lng": -73.5}}}
            ],
        }
    monkeypatch.setattr(travel, "_http_get_json", fake_get)
    assert travel.geocode_address("1 Main St", "K") == (40.5, -73.5)


def test_geocode_address_zero_results(monkeypatch):
    monkeypatch.setattr(
        travel, "_http_get_json",
        lambda url, params: {"status": "ZERO_RESULTS", "results": []},
    )
    with pytest.raises(travel.TravelError) as ei:
        travel.geocode_address("nowhere", "K")
    assert ei.value.stage == "geocode"


def test_geocode_address_http_error(monkeypatch):
    def boom(url, params):
        raise RuntimeError("network down")
    monkeypatch.setattr(travel, "_http_get_json", boom)
    with pytest.raises(travel.TravelError) as ei:
        travel.geocode_address("1 Main St", "K")
    assert ei.value.stage == "geocode"


def test_compute_route_minutes_rounds(monkeypatch):
    captured = {}

    def fake_post(url, body, headers):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        return {"routes": [{"duration": "754s"}]}
    monkeypatch.setattr(travel, "_http_post_json", fake_post)
    assert travel.compute_route_minutes((40.5, -73.5),
                                        (40.7, -73.9), "K") == 13
    assert captured["headers"]["X-Goog-Api-Key"] == "K"
    assert captured["headers"]["X-Goog-FieldMask"] == "routes.duration"
    assert captured["body"]["travelMode"] == "DRIVE"


def test_compute_route_minutes_min_one(monkeypatch):
    monkeypatch.setattr(
        travel, "_http_post_json",
        lambda url, body, headers: {"routes": [{"duration": "20s"}]},
    )
    assert travel.compute_route_minutes((1, 2), (3, 4), "K") == 1


def test_compute_route_minutes_no_routes(monkeypatch):
    monkeypatch.setattr(
        travel, "_http_post_json",
        lambda url, body, headers: {"routes": []},
    )
    with pytest.raises(travel.TravelError) as ei:
        travel.compute_route_minutes((1, 2), (3, 4), "K")
    assert ei.value.stage == "route"


def test_compute_route_minutes_http_error(monkeypatch):
    def boom(url, body, headers):
        raise RuntimeError("429")
    monkeypatch.setattr(travel, "_http_post_json", boom)
    with pytest.raises(travel.TravelError) as ei:
        travel.compute_route_minutes((1, 2), (3, 4), "K")
    assert ei.value.stage == "route"
