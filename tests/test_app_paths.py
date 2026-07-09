import json
import os


def test_app_data_dir_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from gui import app_paths
    d = app_paths.app_data_dir()
    assert d == str(tmp_path / "BowerySeniorCare")
    assert os.path.isdir(d)   # created on demand


def test_time_cache_path_under_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from gui import app_paths
    p = app_paths.time_cache_path()
    assert p == str(tmp_path / "BowerySeniorCare" / "time_cache.json")


def test_time_cache_path_migrates_legacy_file(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    legacy = tmp_path / "old" / "time_cache.json"
    legacy.parent.mkdir()
    legacy.write_text('{"members": {"1": {}}}', encoding="utf-8")

    from gui import app_paths
    p = app_paths.time_cache_path(legacy_path=str(legacy))
    # The legacy cache was copied into the app-data location so
    # already-printed times survive the move.
    assert os.path.exists(p)
    assert json.loads(open(p, encoding="utf-8").read()) == {"members": {"1": {}}}


def test_time_cache_path_keeps_existing_over_legacy(monkeypatch, tmp_path):
    appdata = tmp_path / "appdata"
    monkeypatch.setenv("APPDATA", str(appdata))
    new_dir = appdata / "BowerySeniorCare"
    new_dir.mkdir(parents=True)
    (new_dir / "time_cache.json").write_text('{"keep": true}', encoding="utf-8")
    legacy = tmp_path / "time_cache.json"
    legacy.write_text('{"old": true}', encoding="utf-8")

    from gui import app_paths
    p = app_paths.time_cache_path(legacy_path=str(legacy))
    # An existing app-data cache must NOT be clobbered by the legacy one.
    assert json.loads(open(p, encoding="utf-8").read()) == {"keep": True}
