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
        "time_in": "08:47",   # 527 min
        "time_out": "12:47",  # 767 min
        "departure": "12:49",
        "dropoff": "13:02",
    }


# A window the stored block (08:47–12:47) comfortably fits inside.
FITS = (480, 960)   # 08:00–16:00


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
    out = lookup_times(cache, 24010, date(2026, 5, 5), "HOF", 9, FITS)
    assert out is None


def test_lookup_miss_when_day_absent():
    cache = {}
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    out = lookup_times(cache, 24010, date(2026, 5, 6), "HOF", 9, FITS)
    assert out is None


def test_lookup_hit_returns_stored_times():
    cache = {}
    times = _times()
    store_times(cache, 24010, date(2026, 5, 5), times, "HOF", 9)
    out = lookup_times(cache, 24010, date(2026, 5, 5), "HOF", 9, FITS)
    assert out == times


def test_lookup_invalidates_on_plan_change():
    cache = {}
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    out = lookup_times(cache, 24010, date(2026, 5, 5), "BCBS", 9, FITS)
    assert out is None
    # The stale entry is removed from the cache so it does not pollute
    # the saved file.
    assert "2026-05-05" not in cache["members"].get("24010", {})


def test_lookup_invalidates_on_travel_change():
    cache = {}
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    out = lookup_times(cache, 24010, date(2026, 5, 5), "HOF", 12, FITS)
    assert out is None


def test_lookup_invalidates_when_block_no_longer_fits_window():
    cache = {}
    # Cached block is 08:47–12:47.
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    # New availability narrows the window to 09:30–12:30 (570–750); the
    # cached Time-In 08:47 now starts before it, so the entry is stale.
    out = lookup_times(cache, 24010, date(2026, 5, 5), "HOF", 9, (570, 750))
    assert out is None


def test_lookup_hit_when_new_window_still_fits_block():
    cache = {}
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    # Tighter window that still contains the whole 08:47–12:47 block.
    out = lookup_times(cache, 24010, date(2026, 5, 5), "HOF", 9, (500, 800))
    assert out == _times()


def test_store_overwrites_existing_entry():
    cache = {}
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    new_times = {**_times(), "arrival": "09:00"}
    store_times(cache, 24010, date(2026, 5, 5), new_times, "HOF", 9)
    out = lookup_times(cache, 24010, date(2026, 5, 5), "HOF", 9, FITS)
    assert out["arrival"] == "09:00"


def test_invalidation_cleans_empty_member_entry():
    """After invalidating the only entry for a member, the member key
    itself is removed so the cache file stays tidy."""
    cache = {}
    store_times(cache, 24010, date(2026, 5, 5), _times(), "HOF", 9)
    lookup_times(cache, 24010, date(2026, 5, 5), "BCBS", 9, FITS)
    assert "24010" not in cache.get("members", {})
