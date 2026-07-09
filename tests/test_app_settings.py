import json

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
