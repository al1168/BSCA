import json
import os
import shutil
import sys

from gui.app_paths import app_data_dir

# Test seam: when set (tests monkeypatch a str path), used verbatim.
_SETTINGS_FILE = None

_SOURCE_DIR = os.path.dirname(os.path.dirname(__file__))


def _settings_path() -> str:
    """Resolve where bsca_settings.json lives.

    Running from source: the repo root, as always. Frozen (PyInstaller
    exe): the per-user app-data dir — the onefile exe unpacks into a
    random temp dir each launch, so a path anchored to __file__
    evaporates on exit and every launch looked like a first run (bug,
    2026-07-23). On the first frozen run, a settings file found next to
    the exe or in its parent folder (the repo root for dist\\ builds)
    is copied over so the user keeps their existing setup."""
    if _SETTINGS_FILE:
        return _SETTINGS_FILE
    if not getattr(sys, "frozen", False):
        return os.path.join(_SOURCE_DIR, "bsca_settings.json")
    path = os.path.join(app_data_dir(), "bsca_settings.json")
    if not os.path.exists(path):
        exe_dir = os.path.dirname(sys.executable)
        for legacy_dir in (exe_dir, os.path.dirname(exe_dir)):
            legacy = os.path.join(legacy_dir, "bsca_settings.json")
            if os.path.isfile(legacy):
                try:
                    shutil.copyfile(legacy, path)
                except OSError:
                    pass  # non-fatal: first-run setup asks again
                break
    return path

DEFAULTS = {
    "db_path": r".",
    "google_api_key": "",
    "geo_cache": "geo_cache.json",
    "output_path": ".",
    "language": "en",
    # Default-for-everyone scheduling rules. Tuples are stored as lists
    # so they round-trip cleanly through JSON; rules.get_rules_for_plan
    # converts the ranges back to tuples at use site.
    "schedule_rules": {
        "earliest_time_in": "08:00",
        "latest_time_out": "16:00",
        "session_length_min": [210, 240],
        "travel_buffer_min": [1, 5],
        "time_in_drift_min": [2, 2],
        "time_out_drift_min": [2, 2],
        "dropoff_by_avail_end": True,
        "pickup_by_avail_start": True,
        "band_enabled": False,
        "morning_percent": 80,
        "morning_window_min": 180,
        "morning_members": [],
        "afternoon_members": [],
    },
}


def exists() -> bool:
    return os.path.isfile(_settings_path())


def load() -> dict:
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # dict() copies top-level keys; schedule_rules needs its own
        # copy so a caller mutating it doesn't poison DEFAULTS.
        result = dict(DEFAULTS)
        result["schedule_rules"] = dict(DEFAULTS["schedule_rules"])
        return result

    merged = {**DEFAULTS, **data}
    # schedule_rules: deep-merge so a file with only some of the keys
    # still gets defaults for the rest (forward-compatible). Saved keys
    # not in DEFAULTS are dropped, which retires legacy rule keys
    # (arrival_window/session_span_min) left over from older versions.
    saved_rules = data.get("schedule_rules") or {}
    known = set(DEFAULTS["schedule_rules"])
    merged["schedule_rules"] = {
        **DEFAULTS["schedule_rules"],
        **{k: v for k, v in saved_rules.items() if k in known},
    }
    if _migrate_legacy_google_config(merged):
        try:
            save(merged)
        except OSError:
            pass  # non-fatal: migration re-runs on next launch
    return merged


def save(settings: dict) -> None:
    with open(_settings_path(), "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def _migrate_legacy_google_config(settings: dict) -> bool:
    """One-time migration: replace the legacy `google_config` file-path
    setting with `google_api_key`, reading the file if needed.

    Returns True if the dict was mutated (caller should persist)."""
    legacy_path = settings.pop("google_config", None)
    if legacy_path is None:
        return False

    if settings.get("google_api_key"):
        return True  # mutation = removing the stale key

    try:
        with open(legacy_path, "r", encoding="utf-8") as fh:
            key = fh.read().strip()
    except OSError:
        return True  # file missing/unreadable — still dropped the key

    if key:
        settings["google_api_key"] = key
    return True
