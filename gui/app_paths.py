"""Per-user app-data locations for BSCA.

Files that must survive across runs and should NOT sit next to the
generated output (where a user might delete them by accident) live
here — currently just the time cache that keeps printed visit times
stable across reruns.
"""

import os
import shutil

APP_DIR_NAME = "BowerySeniorCare"


def app_data_dir():
    """Return the per-user app-data directory for BSCA, creating it if
    needed. Uses %APPDATA% on Windows; falls back to ~/.bsca elsewhere
    (or if APPDATA is unset)."""
    base = os.environ.get("APPDATA")
    if base:
        path = os.path.join(base, APP_DIR_NAME)
    else:
        path = os.path.join(os.path.expanduser("~"), ".bsca")
    os.makedirs(path, exist_ok=True)
    return path


def time_cache_path(legacy_path=None):
    """Path to the persistent time cache under app-data.

    If the app-data cache doesn't exist yet but a `legacy_path` cache
    does (the old location next to geo_cache.json), the legacy file is
    copied over first — a one-time migration so already-printed times
    survive the move. An existing app-data cache is never overwritten."""
    new_path = os.path.join(app_data_dir(), "time_cache.json")
    if (legacy_path and not os.path.exists(new_path)
            and os.path.exists(legacy_path)):
        try:
            shutil.copyfile(legacy_path, new_path)
        except OSError:
            pass  # non-fatal: a fresh cache is rebuilt on the next run
    return new_path
