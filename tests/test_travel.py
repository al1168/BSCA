import time

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


def test_purge_expired_removes_stale_entries():
    now = 1_000_000
    cache = {
        "geocode": {"old addr": [1.0, 2.0], "new addr": [3.0, 4.0]},
        "route": {"1.0,2.0": 5},
        "ts": {
            "geocode:old addr": now - travel._CACHE_TTL_SECONDS - 1,
            "geocode:new addr": now - 60,
            "route:1.0,2.0": now - travel._CACHE_TTL_SECONDS - 1,
        },
    }
    travel._purge_expired(cache, now=now)
    assert "old addr" not in cache["geocode"]
    assert "new addr" in cache["geocode"]
    assert "1.0,2.0" not in cache["route"]


def test_purge_expired_keeps_fresh_entries():
    now = 1_000_000
    cache = {
        "geocode": {"addr": [1.0, 2.0]},
        "ts": {"geocode:addr": now - 60},
    }
    travel._purge_expired(cache, now=now)
    assert "addr" in cache["geocode"]


def test_purge_expired_no_ts_treats_all_as_expired():
    cache = {"geocode": {"addr": [1.0, 2.0]}, "route": {"1,2": 5}}
    travel._purge_expired(cache)
    assert cache["geocode"] == {}
    assert cache["route"] == {}


def test_load_cache_missing_returns_empty(tmp_path):
    assert travel.load_cache(str(tmp_path / "nope.json")) == {}


def test_load_cache_corrupt_returns_empty_and_warns(tmp_path, capsys):
    p = tmp_path / "c.json"
    p.write_text("not json{", encoding="utf-8")
    assert travel.load_cache(str(p)) == {}
    assert "geo cache" in capsys.readouterr().err


def test_cache_round_trip(tmp_path):
    p = str(tmp_path / "c.json")
    now = time.time()
    data = {
        "geocode": {"a": [1.0, 2.0]},
        "route": {"1.0,2.0": 7},
        "ts": {"geocode:a": now, "route:1.0,2.0": now},
    }
    travel.save_cache(p, data)
    assert travel.load_cache(p) == data


def test_load_cache_non_dict_returns_empty(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert travel.load_cache(str(p)) == {}


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


def test_geocode_retries_on_over_query_limit_then_succeeds(monkeypatch):
    monkeypatch.setattr(travel.time, "sleep", lambda s: None)
    responses = [
        {"status": "OVER_QUERY_LIMIT", "results": []},
        {"status": "OK", "results": [
            {"geometry": {"location": {"lat": 40.5, "lng": -73.5}}}
        ]},
    ]
    monkeypatch.setattr(travel, "_http_get_json", lambda url, p: responses.pop(0))
    assert travel.geocode_address("1 Main St", "K") == (40.5, -73.5)


def test_geocode_raises_after_all_retries_exhausted(monkeypatch):
    monkeypatch.setattr(travel.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        travel, "_http_get_json",
        lambda url, p: {"status": "OVER_QUERY_LIMIT", "results": []},
    )
    with pytest.raises(travel.TravelError) as ei:
        travel.geocode_address("1 Main St", "K")
    assert ei.value.stage == "geocode"
    assert "OVER_QUERY_LIMIT" in ei.value.reason


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


def _no_geocode(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("geocode_address should not be called")
    monkeypatch.setattr(travel, "geocode_address", fail)


def test_resolve_uses_db_long_lat_no_geocode(monkeypatch):
    _no_geocode(monkeypatch)
    monkeypatch.setattr(
        travel, "compute_route_minutes",
        lambda origin, dest, key: 9,
    )
    cache = {}
    member = {"long_lat": "40.5,-73.5", "address": "ignored"}
    assert travel.resolve_travel_minutes(member, "K", cache) == 9
    assert cache["route"]["40.5,-73.5"] == 9


def test_resolve_geocode_cache_hit_no_api(monkeypatch):
    _no_geocode(monkeypatch)
    monkeypatch.setattr(
        travel, "compute_route_minutes",
        lambda origin, dest, key: 4,
    )
    cache = {"geocode": {"1 main st": [40.5, -73.5]}}
    member = {"long_lat": None, "address": " 1  Main  St "}
    assert travel.resolve_travel_minutes(member, "K", cache) == 4


def test_resolve_geocode_miss_calls_api_and_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(
        travel, "geocode_address",
        lambda addr, key: calls.append(addr) or (40.5, -73.5),
    )
    monkeypatch.setattr(
        travel, "compute_route_minutes",
        lambda origin, dest, key: 6,
    )
    cache = {}
    member = {"long_lat": "", "address": "1 Main St"}
    assert travel.resolve_travel_minutes(member, "K", cache) == 6
    assert calls == ["1 Main St"]
    assert cache["geocode"]["1 main st"] == [40.5, -73.5]
    assert cache["route"]["40.5,-73.5"] == 6


def test_resolve_route_cache_hit_no_route_call(monkeypatch):
    _no_geocode(monkeypatch)

    def fail_route(*a, **k):
        raise AssertionError("compute_route_minutes should not run")
    monkeypatch.setattr(travel, "compute_route_minutes", fail_route)
    cache = {"route": {"40.5,-73.5": 11}}
    member = {"long_lat": "40.5,-73.5", "address": None}
    assert travel.resolve_travel_minutes(member, "K", cache) == 11


def test_resolve_writes_timestamp_on_geocode_cache_miss(monkeypatch):
    monkeypatch.setattr(travel, "geocode_address", lambda addr, key: (40.5, -73.5))
    monkeypatch.setattr(travel, "compute_route_minutes", lambda o, d, k: 6)
    cache = {}
    travel.resolve_travel_minutes({"long_lat": None, "address": "1 Main St"}, "K", cache)
    assert "geocode:1 main st" in cache.get("ts", {})
    assert "route:40.5,-73.5" in cache.get("ts", {})


def test_resolve_no_coords_no_address_raises(monkeypatch):
    _no_geocode(monkeypatch)
    member = {"long_lat": None, "address": "   "}
    with pytest.raises(travel.TravelError) as ei:
        travel.resolve_travel_minutes(member, "K", {})
    assert ei.value.stage == "geocode"
