import json
import os

_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bsca_settings.json")

DEFAULTS = {
    "db_path": r"C:\Users\luald\OneDrive\Desktop\Access Member 5.5.26_copy.accdb",
    "google_config": "google_maps.config",
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
        return {**DEFAULTS, **data}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULTS)


def save(settings: dict) -> None:
    with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
