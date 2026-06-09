import json
import os

_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bsca_settings.json")

DEFAULTS = {
    "db_path": r".",
    "google_api_key": "",
    "geo_cache": "geo_cache.json",
    "output_path": ".",
    "language": "en",
}


def exists() -> bool:
    return os.path.isfile(_SETTINGS_FILE)


def load() -> dict:
    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULTS)

    merged = {**DEFAULTS, **data}
    if _migrate_legacy_google_config(merged):
        try:
            save(merged)
        except OSError:
            pass  # non-fatal: migration re-runs on next launch
    return merged


def save(settings: dict) -> None:
    with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
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
