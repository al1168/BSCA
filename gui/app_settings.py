import json
import os

_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bsca_settings.json")

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
    },
}


def exists() -> bool:
    return os.path.isfile(_SETTINGS_FILE)


def load() -> dict:
    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as f:
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
