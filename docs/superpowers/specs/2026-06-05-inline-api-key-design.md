# Inline Google Maps API Key

Status: Draft
Date: 2026-06-05

## Goal

Replace the Google Maps API key config-file workflow with a direct input field. Both the GUI Settings dialog and the CLI take the key inline instead of pointing at a file on disk.

## Motivation

The current flow forces the user through a file-management detour for what is conceptually a single string: create a `.config` file, paste the key in, point the app at the path, keep the path valid. An inline field is shorter to explain, fewer things to break (file missing, file empty, wrong path), and matches how every other tool accepts an API key.

## Scope

In scope:

- `gui/app_settings.py` — replace `google_config` (path) with `google_api_key` (string); one-time auto-migration from the old file.
- `gui/settings_dialog.py` — replace `_GoogleConfigRow` (browse + "Create & Open" file dialog) with a masked text field + Show/Hide toggle.
- `gui/main_window.py` — validate the key is non-empty; pass the key into the worker.
- `gui/worker.py` — accept `google_api_key` directly; drop the file-read step.
- `gui/i18n.py` — rename/add/remove translation strings (English + 中文).
- `new_monthly_schedule.py` — replace `--google-config` with `--api-key` (required).
- `monthly_schedule/travel.py` — delete `load_api_key()`; no longer referenced.

Out of scope:

- Encryption at rest. The key sits in plain text in `bsca_settings.json`, same exposure level as the previous `google_maps.config` file.
- Environment variable fallback for the CLI. `--api-key` only.
- Removing the legacy `google_maps.config` file from disk after migration. We leave the file alone; the user can delete it.

## Design

### Settings storage (`gui/app_settings.py`)

`DEFAULTS` changes:

```python
DEFAULTS = {
    "db_path": r".",
    "google_api_key": "",     # was: "google_config": "google_maps.config"
    "geo_cache": "geo_cache.json",
    "output_path": ".",
    "language": "en",
}
```

`load()` gains a migration step. After merging defaults with the on-disk JSON, before returning:

1. If `google_api_key` is non-empty, just drop any leftover `google_config` key and return.
2. Otherwise, if `google_config` is present and points at a readable, non-empty file, read its stripped contents into `google_api_key`, drop `google_config`, and call `save()` once so the migration sticks.
3. If the file is missing or unreadable, drop `google_config` silently. `google_api_key` stays empty — the user re-pastes in Settings.

The migration only fires when there's something to migrate from. Fresh installs (no `bsca_settings.json` yet) skip it entirely.

### Settings dialog (`gui/settings_dialog.py`)

Delete `_GoogleConfigRow` and its supporting helpers — `_GOOGLE_CONFIG_PLACEHOLDER`, `_default_config_dir`, the "Create & Open" flow, the file-exists confirmation dialog, the `_create_and_open` method.

New `_ApiKeyRow` (sibling of `_PathRow`):

- `QLineEdit` with `EchoMode.Password`, minimum width matching the path rows.
- Toggle button (`QPushButton`, fixed width ~70px) that flips between `EchoMode.Password` and `EchoMode.Normal` and updates its label between "Show" and "Hide".
- `value()` / `set_value()` mirror `_PathRow`.
- `retranslate()` updates the toggle button text via `tr()`.

`SettingsDialog.__init__` swaps the `_gc_row = _GoogleConfigRow(...)` line for `_key_row = _ApiKeyRow(settings.get("google_api_key", ""))`, and renames `_gc_label` → `_api_key_label`. Form label key changes from `settings.google_label` to `settings.api_key_label`. `_retranslate()` updates the new label and calls `self._key_row.retranslate()` (which initially sets the toggle button to `tr("settings.api_key.show")`, since the field starts in Password mode).

`_save()` writes `"google_api_key": self._key_row.value()` instead of `"google_config": self._gc_row.value()`.

`_test_connection()`: the second block (file existence + `load_api_key`) collapses to:

```python
key = self._key_row.value()
if key:
    lines.append(tr("settings.test.api_key_present"))
else:
    lines.append(tr("settings.test.api_key_missing"))
```

Drop the `load_api_key` import.

### Main window (`gui/main_window.py`)

`_validate()`: replace the `gc_path = self._settings.get("google_config", "") ... os.path.isfile(gc_path)` check with:

```python
api_key = self._settings.get("google_api_key", "").strip()
if not api_key:
    QMessageBox.warning(
        self,
        tr("msg.api_key_missing.title"),
        tr("msg.api_key_missing.body"),
    )
    return False
```

`_run()`: replace `google_config=self._settings["google_config"]` with `google_api_key=self._settings["google_api_key"]` in the `ScheduleWorker` constructor call.

### Worker (`gui/worker.py`)

Constructor parameter renames `google_config` → `google_api_key`; the attribute stored on `self` follows.

In `_run_inner`, delete the `try: api_key = load_api_key(...)` block. Use `api_key = self.google_api_key` directly. The downstream `process_member(..., api_key, cache)` call is unchanged.

Drop `load_api_key` from the import line.

### `monthly_schedule/travel.py`

Delete `load_api_key()`. No other changes — `geocode_address`, `compute_route_minutes`, and `resolve_travel_minutes` already accept `api_key` as a parameter.

### CLI (`new_monthly_schedule.py`)

- Drop `DEFAULT_GOOGLE_CONFIG` constant.
- Drop `load_api_key` from the `monthly_schedule.travel` import.
- Replace `parser.add_argument("--google-config", default=DEFAULT_GOOGLE_CONFIG)` with `parser.add_argument("--api-key", required=True)`.
- Replace the `try: api_key = load_api_key(args.google_config) except RuntimeError ...` block in `main()` with `api_key = args.api_key` (no try/except; argparse already rejects missing required args).

### i18n (`gui/i18n.py`)

Add (English + 中文):

- `settings.api_key_label` — "Google Maps API Key" / "Google 地图 API 密钥"
- `settings.api_key.show` — "Show" / "显示"
- `settings.api_key.hide` — "Hide" / "隐藏"
- `settings.test.api_key_present` — "API Key: provided." / "API 密钥：已填写。"
- `settings.test.api_key_missing` — "API Key: missing — enter one above." / "API 密钥：未填写 — 请在上方输入。"
- `msg.api_key_missing.title` — "API Key Missing" / "缺少 API 密钥"
- `msg.api_key_missing.body` — "Enter your Google Maps API key in Settings before generating." / "生成前请在设置中输入您的 Google 地图 API 密钥。"

Remove (no longer referenced):

- `settings.google_label`
- `settings.create_open`, `settings.create_open_tooltip`
- `settings.file_dialog.google`
- `settings.test.gc_not_found`, `settings.test.gc_ok`, `settings.test.gc_fail`
- `settings.file_exists_title`, `settings.file_exists_body`
- `settings.create_fail_title`
- `msg.gc_not_found.title`, `msg.gc_not_found.body`

## Migration behavior — concrete examples

**Existing install on this machine.** `bsca_settings.json` currently has `"google_config": "google_maps.config"` and that file holds the real key. On next launch, `load()` reads the file, writes `"google_api_key": "<the key>"` back to `bsca_settings.json`, and the user never notices.

**Existing install where the file was deleted.** `google_config` points at a missing path. `load()` drops the key, leaves `google_api_key` empty, and `_validate()` will prompt the user to paste the key in Settings before generating.

**Fresh install.** No `bsca_settings.json` yet; the first-run `SettingsDialog` opens with an empty API key field. User pastes once, Save.

## Testing

The existing test suite doesn't cover the GUI path directly. For this change:

- Manual: run `python gui.py`, confirm the new field renders, Show/Hide toggle works, Save persists to `bsca_settings.json` as `google_api_key`, Test Connection reflects the field's current value.
- Manual: with the current `bsca_settings.json` (which references `google_maps.config`), launch the app once and verify the migration writes `google_api_key` and drops `google_config`.
- Manual: run the CLI: `python new_monthly_schedule.py --center-id <id> --year 2026 --month 7 --api-key <key>`. Confirm it generates as before.
- Manual: run the CLI without `--api-key` and confirm argparse errors out with a clear message.
- Existing automated tests: check none of them import `load_api_key` or set `google_config`. If any do, update them.
