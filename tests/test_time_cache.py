from datetime import date

from monthly_schedule.time_cache import (
    load_time_cache,
    save_time_cache,
    lookup_times,
    store_times,
)


def _times():
    return {
        "pickup": "08:32",
        "arrival": "08:45",
        "time_in": "08:47",
        "time_out": "12:47",
        "departure": "12:49",
        "dropoff": "13:02",
    }


def test_load_missing_returns_empty(tmp_path):
    assert load_time_cache(str(tmp_path / "nope.json")) == {}


def test_load_corrupt_returns_empty_and_warns(tmp_path, capsys):
    p = tmp_path / "c.json"
    p.write_text("not json{", encoding="utf-8")
    assert load_time_cache(str(p)) == {}
    assert "time cache" in capsys.readouterr().err


def test_load_non_dict_returns_empty(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_time_cache(str(p)) == {}


def test_save_and_round_trip(tmp_path):
    p = str(tmp_path / "c.json")
    cache = {}
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    save_time_cache(p, cache)
    reloaded = load_time_cache(p)
    assert reloaded == cache


def test_lookup_miss_when_member_absent():
    cache = {"members": {}}
    out = lookup_times(
        cache, 24010, date(2026, 5, 5), "HOF", 9, (480, 660)
    )
    assert out is None


def test_lookup_miss_when_day_absent():
    cache = {}
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    out = lookup_times(
        cache, 24010, date(2026, 5, 6), "HOF", 9, (480, 660)
    )
    assert out is None


def test_lookup_hit_returns_stored_times():
    cache = {}
    times = _times()
    store_times(cache, 24010, date(2026, 5, 5), times, "HOF", 9)
    out = lookup_times(
        cache, 24010, date(2026, 5, 5), "HOF", 9, (480, 660)
    )
    assert out == times


def test_lookup_invalidates_on_plan_change():
    cache = {}
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    out = lookup_times(
        cache, 24010, date(2026, 5, 5), "BCBS", 9, (480, 660)
    )
    assert out is None
    # The stale entry is removed from the cache so it does not pollute
    # the saved file.
    assert "2026-05-05" not in cache["members"].get("24010", {})


def test_lookup_invalidates_on_travel_change():
    cache = {}
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    out = lookup_times(
        cache, 24010, date(2026, 5, 5), "HOF", 12, (480, 660)
    )
    assert out is None


def test_lookup_invalidates_when_arrival_outside_new_window():
    cache = {}
    # Cached arrival is 08:45 = 525 min.
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    # New availability narrows arrival to 09:30-10:30 (570-630) -
    # 08:45 is outside this window, so the cached entry is stale.
    out = lookup_times(
        cache, 24010, date(2026, 5, 5), "HOF", 9, (570, 630)
    )
    assert out is None


def test_lookup_hit_when_new_window_still_includes_arrival():
    cache = {}
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    # Wider window still includes 08:45.
    out = lookup_times(
        cache, 24010, date(2026, 5, 5), "HOF", 9, (420, 720)
    )
    assert out == _times()


def test_store_overwrites_existing_entry():
    cache = {}
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    new_times = {**_times(), "arrival": "09:00"}
    store_times(cache, 24010, date(2026, 5, 5), new_times, "HOF", 9)
    out = lookup_times(
        cache, 24010, date(2026, 5, 5), "HOF", 9, (480, 660)
    )
    assert out["arrival"] == "09:00"


def test_invalidation_cleans_empty_member_entry():
    """After invalidating the only entry for a member, the member key
    itself is removed so the cache file stays tidy."""
    cache = {}
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    lookup_times(
        cache, 24010, date(2026, 5, 5), "BCBS", 9, (480, 660)
    )
    assert "24010" not in cache.get("members", {})
