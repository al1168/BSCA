import json
import sys

import pytest


@pytest.fixture
def settings_file(monkeypatch, tmp_path):
    path = tmp_path / "bsca_settings.json"
    monkeypatch.setattr("gui.app_settings._SETTINGS_FILE", str(path))
    return path


def test_load_fresh_install_returns_defaults(settings_file):
    from gui import app_settings
    s = app_settings.load()
    assert s["google_api_key"] == ""
    assert "google_config" not in s


def test_load_passes_through_existing_api_key(settings_file):
    settings_file.write_text(json.dumps({"google_api_key": "abc"}))
    from gui import app_settings
    s = app_settings.load()
    assert s["google_api_key"] == "abc"
    assert "google_config" not in s


def test_load_migrates_legacy_google_config(settings_file, tmp_path):
    cfg_path = tmp_path / "google_maps.config"
    cfg_path.write_text("  legacy-key-from-file  \n", encoding="utf-8")
    settings_file.write_text(json.dumps({"google_config": str(cfg_path)}))

    from gui import app_settings
    s = app_settings.load()

    assert s["google_api_key"] == "legacy-key-from-file"
    assert "google_config" not in s
    # Migration was persisted: reloading sees the same result without
    # needing the legacy file again.
    cfg_path.unlink()
    s2 = app_settings.load()
    assert s2["google_api_key"] == "legacy-key-from-file"
    assert "google_config" not in s2


def test_load_drops_google_config_when_file_missing(settings_file, tmp_path):
    settings_file.write_text(json.dumps({
        "google_config": str(tmp_path / "absent.config")
    }))

    from gui import app_settings
    s = app_settings.load()

    assert s["google_api_key"] == ""
    assert "google_config" not in s
    on_disk = json.loads(settings_file.read_text())
    assert "google_config" not in on_disk
    assert on_disk["google_api_key"] == ""


def test_load_drops_google_config_when_file_empty(settings_file, tmp_path):
    cfg_path = tmp_path / "google_maps.config"
    cfg_path.write_text("   \n", encoding="utf-8")
    settings_file.write_text(json.dumps({"google_config": str(cfg_path)}))

    from gui import app_settings
    s = app_settings.load()

    assert s["google_api_key"] == ""
    assert "google_config" not in s
    on_disk = json.loads(settings_file.read_text())
    assert "google_config" not in on_disk
    assert on_disk["google_api_key"] == ""


def test_fresh_install_has_default_schedule_rules(settings_file):
    from gui import app_settings
    s = app_settings.load()
    rules = s["schedule_rules"]
    assert rules["earliest_time_in"] == "08:00"
    assert rules["latest_time_out"] == "16:00"
    assert rules["session_length_min"] == [210, 240]
    assert rules["travel_buffer_min"] == [1, 5]
    assert rules["time_in_drift_min"] == [2, 2]
    assert rules["time_out_drift_min"] == [2, 2]


def test_partial_schedule_rules_fills_in_defaults(settings_file):
    """A settings file with only some rule keys still gets the rest
    from defaults, so adding a new knob in code is forward-compatible."""
    settings_file.write_text(json.dumps({
        "schedule_rules": {"earliest_time_in": "07:00"},
    }))
    from gui import app_settings
    s = app_settings.load()
    rules = s["schedule_rules"]
    assert rules["earliest_time_in"] == "07:00"
    assert rules["session_length_min"] == [210, 240]  # default
    assert rules["travel_buffer_min"] == [1, 5]       # default


def test_legacy_rule_keys_are_dropped(settings_file):
    """Old arrival_window/session_span_min keys from prior versions are
    retired on load rather than lingering as dead config."""
    settings_file.write_text(json.dumps({
        "schedule_rules": {
            "arrival_window": ["08:00", "11:00"],
            "session_span_min": [210, 245],
            "earliest_time_in": "09:00",
        },
    }))
    from gui import app_settings
    s = app_settings.load()
    rules = s["schedule_rules"]
    assert "arrival_window" not in rules
    assert "session_span_min" not in rules
    assert rules["earliest_time_in"] == "09:00"


def test_defaults_not_mutated_after_load(settings_file):
    """Caller mutating their schedule_rules dict must not leak back
    into the global DEFAULTS table."""
    from gui import app_settings
    s = app_settings.load()
    s["schedule_rules"]["earliest_time_in"] = "99:99"
    fresh = app_settings.load()
    assert fresh["schedule_rules"]["earliest_time_in"] == "08:00"


def test_load_existing_key_wins_over_legacy_path(settings_file, tmp_path):
    cfg_path = tmp_path / "google_maps.config"
    cfg_path.write_text("file-key", encoding="utf-8")
    settings_file.write_text(json.dumps({
        "google_api_key": "explicit-key",
        "google_config": str(cfg_path),
    }))

    from gui import app_settings
    s = app_settings.load()

    assert s["google_api_key"] == "explicit-key"
    assert "google_config" not in s


def test_dropoff_by_avail_end_default_on_fresh_install(settings_file):
    from gui import app_settings
    s = app_settings.load()
    assert s["schedule_rules"]["dropoff_by_avail_end"] is True


def test_dropoff_by_avail_end_missing_key_filled_on(settings_file):
    # A settings file saved before this feature has no key — the loader
    # must fill it from DEFAULTS (i.e., turn it on).
    settings_file.write_text(json.dumps({
        "schedule_rules": {"earliest_time_in": "09:00"}
    }))
    from gui import app_settings
    s = app_settings.load()
    assert s["schedule_rules"]["dropoff_by_avail_end"] is True
    assert s["schedule_rules"]["earliest_time_in"] == "09:00"


def test_dropoff_by_avail_end_saved_false_respected(settings_file):
    settings_file.write_text(json.dumps({
        "schedule_rules": {"dropoff_by_avail_end": False}
    }))
    from gui import app_settings
    s = app_settings.load()
    assert s["schedule_rules"]["dropoff_by_avail_end"] is False


def test_pickup_by_avail_start_default_on_fresh_install(settings_file):
    from gui import app_settings
    s = app_settings.load()
    assert s["schedule_rules"]["pickup_by_avail_start"] is True


def test_pickup_by_avail_start_missing_key_filled_on(settings_file):
    # A settings file saved before this feature has no key — the loader
    # must fill it from DEFAULTS (i.e., turn it on).
    settings_file.write_text(json.dumps({
        "schedule_rules": {"earliest_time_in": "09:00"}
    }))
    from gui import app_settings
    s = app_settings.load()
    assert s["schedule_rules"]["pickup_by_avail_start"] is True
    assert s["schedule_rules"]["earliest_time_in"] == "09:00"


def test_pickup_by_avail_start_saved_false_respected(settings_file):
    settings_file.write_text(json.dumps({
        "schedule_rules": {"pickup_by_avail_start": False}
    }))
    from gui import app_settings
    s = app_settings.load()
    assert s["schedule_rules"]["pickup_by_avail_start"] is False


def test_band_defaults_on_fresh_install(settings_file):
    from gui import app_settings
    rules = app_settings.load()["schedule_rules"]
    assert rules["band_enabled"] is False
    assert rules["morning_percent"] == 80
    assert rules["morning_window_min"] == 180
    assert rules["morning_members"] == []
    assert rules["afternoon_members"] == []


def test_band_keys_missing_filled_off(settings_file):
    # A settings file saved before this feature has no band keys -- the
    # loader fills them from DEFAULTS with the feature OFF.
    settings_file.write_text(json.dumps({
        "schedule_rules": {"earliest_time_in": "09:00"}
    }))
    from gui import app_settings
    rules = app_settings.load()["schedule_rules"]
    assert rules["band_enabled"] is False
    assert rules["earliest_time_in"] == "09:00"


def test_band_settings_round_trip(settings_file):
    from gui import app_settings
    s = app_settings.load()
    s["schedule_rules"]["band_enabled"] = True
    s["schedule_rules"]["morning_percent"] = 65
    s["schedule_rules"]["morning_window_min"] = 120
    s["schedule_rules"]["morning_members"] = [24010, 24011]
    s["schedule_rules"]["afternoon_members"] = [24012]
    app_settings.save(s)
    rules = app_settings.load()["schedule_rules"]
    assert rules["band_enabled"] is True
    assert rules["morning_percent"] == 65
    assert rules["morning_window_min"] == 120
    assert rules["morning_members"] == [24010, 24011]
    assert rules["afternoon_members"] == [24012]


# ── Frozen (PyInstaller exe) settings location ──────────────────────
# The onefile exe unpacks to a random temp dir each launch, so a
# settings path anchored to __file__ evaporates on exit (the
# "settings don't save" bug, 2026-07-23). Frozen builds must use the
# stable per-user app-data dir instead, migrating any legacy file.

@pytest.fixture
def frozen_env(monkeypatch, tmp_path):
    """Simulate running as dist\MonthlyScheduleGenerator.exe with a
    private APPDATA. Returns (expected_appdata_file, exe_dir)."""
    monkeypatch.setattr("gui.app_settings._SETTINGS_FILE", None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe_dir = tmp_path / "dist"
    exe_dir.mkdir()
    monkeypatch.setattr(
        sys, "executable", str(exe_dir / "MonthlyScheduleGenerator.exe")
    )
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    expected = (tmp_path / "appdata" / "BowerySeniorCare"
                / "bsca_settings.json")
    return expected, exe_dir


def test_frozen_settings_persist_in_appdata(frozen_env):
    expected, _exe_dir = frozen_env
    from gui import app_settings
    s = app_settings.load()
    s["google_api_key"] = "persisted"
    app_settings.save(s)
    assert expected.is_file()
    assert app_settings.exists()
    assert app_settings.load()["google_api_key"] == "persisted"


def test_frozen_migrates_settings_next_to_exe(frozen_env):
    expected, exe_dir = frozen_env
    (exe_dir / "bsca_settings.json").write_text(
        json.dumps({"google_api_key": "from-exe-dir"})
    )
    from gui import app_settings
    assert app_settings.exists()
    assert app_settings.load()["google_api_key"] == "from-exe-dir"
    assert expected.is_file()   # copied, not just read in place


def test_frozen_migrates_settings_from_exe_parent(frozen_env):
    # dist\ lives inside the repo, whose root holds the settings from
    # source-mode runs — the most common migration source.
    expected, exe_dir = frozen_env
    (exe_dir.parent / "bsca_settings.json").write_text(
        json.dumps({"google_api_key": "from-repo-root"})
    )
    from gui import app_settings
    assert app_settings.load()["google_api_key"] == "from-repo-root"
    assert expected.is_file()


def test_frozen_appdata_file_wins_over_legacy(frozen_env):
    expected, exe_dir = frozen_env
    expected.parent.mkdir(parents=True)
    expected.write_text(json.dumps({"google_api_key": "appdata"}))
    (exe_dir / "bsca_settings.json").write_text(
        json.dumps({"google_api_key": "legacy"})
    )
    from gui import app_settings
    assert app_settings.load()["google_api_key"] == "appdata"


def test_unfrozen_default_path_is_repo_root(monkeypatch):
    import os
    monkeypatch.setattr("gui.app_settings._SETTINGS_FILE", None)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    from gui import app_settings
    path = app_settings._settings_path()
    repo_root = os.path.dirname(os.path.dirname(app_settings.__file__))
    assert path == os.path.join(repo_root, "bsca_settings.json")
