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
