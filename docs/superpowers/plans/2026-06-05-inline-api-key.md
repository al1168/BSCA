# Inline Google Maps API Key Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Google Maps API key config-file workflow with a direct input field — masked text field in the GUI Settings dialog, and a `--api-key` flag on the CLI.

**Architecture:** Settings storage swaps `google_config` (file path) for `google_api_key` (string), with a one-time migration that reads the legacy file on load. The GUI worker and CLI both receive the key directly instead of opening a file at runtime. `monthly_schedule.travel.load_api_key()` is deleted entirely.

**Tech Stack:** Python 3.11, PyQt6, pytest. Existing patterns: `gui/i18n.py` provides `tr()` with parallel `en`/`zh` dicts (parity enforced by `tests/test_i18n.py::test_key_parity`). `gui/app_settings.py` is monkeypatch-friendly via the module-level `_SETTINGS_FILE` constant.

**Spec:** [docs/superpowers/specs/2026-06-05-inline-api-key-design.md](../specs/2026-06-05-inline-api-key-design.md)

---

## File Map

- `new_monthly_schedule.py` — CLI: drop `--google-config`/`load_api_key` import/`DEFAULT_GOOGLE_CONFIG`; add required `--api-key`.
- `tests/test_cli.py` — Inject `--api-key K` via the autouse fixture's `parse_args` wrapper; delete `test_missing_api_key_config_aborts`.
- `gui/worker.py` — Rename `google_config` constructor param → `google_api_key`; use it directly; drop `load_api_key` import.
- `gui/app_settings.py` — DEFAULTS gets `google_api_key: ""`; `load()` migrates legacy `google_config` once.
- `gui/i18n.py` — Add 7 keys, remove 11 keys, in both `en` and `zh`.
- `gui/settings_dialog.py` — Delete `_GoogleConfigRow` + helpers; add `_ApiKeyRow` (masked LineEdit + Show/Hide toggle); rewire `_test_connection` and `_save`.
- `gui/main_window.py` — `_validate()` checks `google_api_key` non-empty; `_run()` passes `google_api_key=...` to worker.
- `monthly_schedule/travel.py` — Delete `load_api_key()`.
- `tests/test_travel.py` — Delete the three `test_load_api_key_*` tests.

Task ordering removes consumers first, then the function itself, so the repo stays runnable at every commit.

---

## Task 1: Switch CLI to `--api-key`

**Files:**
- Modify: `new_monthly_schedule.py:21-30, 120-129, 181-189`
- Modify: `tests/test_cli.py:42-63, 381-394`

- [ ] **Step 1: Read the current CLI imports + arg parser + main()**

You need to see lines 21-30 (imports), 120-129 (argparse), and 181-189 (main's key-loading block) to confirm the diff context matches.

Run: `git diff HEAD -- new_monthly_schedule.py` (should be empty — clean tree)

- [ ] **Step 2: Update the import block**

In [new_monthly_schedule.py](../../../new_monthly_schedule.py), replace:

```python
from monthly_schedule.travel import (
    load_api_key,
    load_cache,
    save_cache,
    resolve_travel_minutes,
    TravelError,
)

DEFAULT_DB = r"\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb"
DEFAULT_GOOGLE_CONFIG = "google_maps.config"
DEFAULT_GEO_CACHE = "geo_cache.json"
```

with:

```python
from monthly_schedule.travel import (
    load_cache,
    save_cache,
    resolve_travel_minutes,
    TravelError,
)

DEFAULT_DB = r"\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb"
DEFAULT_GEO_CACHE = "geo_cache.json"
```

- [ ] **Step 3: Update the argparse block**

In `parse_args()`, replace:

```python
    parser.add_argument("--google-config", default=DEFAULT_GOOGLE_CONFIG)
```

with:

```python
    parser.add_argument("--api-key", required=True)
```

- [ ] **Step 4: Update `main()`**

Replace:

```python
    try:
        api_key = load_api_key(args.google_config)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    cache = load_cache(args.geo_cache)
```

with:

```python
    api_key = args.api_key
    cache = load_cache(args.geo_cache)
```

- [ ] **Step 5: Update the `_stub_travel` fixture in tests**

In [tests/test_cli.py](../../../tests/test_cli.py), replace:

```python
@pytest.fixture(autouse=True)
def _stub_travel(monkeypatch):
    """Neutralize travel + new DB lookups for legacy tests."""
    monkeypatch.setattr(cli, "load_api_key", lambda path: "K")
    monkeypatch.setattr(cli, "load_cache", lambda path: {})
```

with:

```python
@pytest.fixture(autouse=True)
def _stub_travel(monkeypatch):
    """Neutralize travel + new DB lookups for legacy tests.

    Injects --api-key K into every parse_args call so individual tests
    don't have to thread the flag through every cli.main() invocation.
    """
    _real_parse_args = cli.parse_args

    def _parse_args_with_key(argv):
        if "--api-key" not in argv:
            argv = list(argv) + ["--api-key", "K"]
        return _real_parse_args(argv)

    monkeypatch.setattr(cli, "parse_args", _parse_args_with_key)
    monkeypatch.setattr(cli, "load_cache", lambda path: {})
```

- [ ] **Step 6: Delete the file-missing test**

In `tests/test_cli.py`, delete the entire `test_missing_api_key_config_aborts` function (lines 381-394). The "missing required arg" behavior is now argparse's responsibility — it's tested by stdlib, no project-level test needed.

- [ ] **Step 7: Run the CLI test suite**

Run: `pytest tests/test_cli.py -v`
Expected: all tests pass (one fewer than before — the deleted one).

If any test errors with `error: the following arguments are required: --api-key`, the fixture's `parse_args` wrapper isn't being installed correctly. Check that the autouse fixture is still autouse and that the wrapper signature matches `parse_args(argv)`.

- [ ] **Step 8: Smoke-run the CLI directly**

Run (substitute a real key + valid IDs):
```
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 7 --api-key TEST_KEY --preview-data
```

Expected: either succeeds (DB reachable + key valid would actually call Google — `--preview-data` skips workbook write but still does travel resolution) or fails with a *runtime* error like "Database not found" / "geocode" — not an argparse error.

Run without `--api-key`:
```
python new_monthly_schedule.py --center-id 24010 --year 2026 --month 7 --preview-data
```

Expected: argparse exits with `error: the following arguments are required: --api-key`.

- [ ] **Step 9: Commit**

```bash
git add new_monthly_schedule.py tests/test_cli.py
git commit -m "feat(cli): take --api-key inline instead of --google-config file"
```

---

## Task 2: Worker accepts API key directly

**Files:**
- Modify: `gui/worker.py:15, 34-60, 76-82`

- [ ] **Step 1: Update worker imports**

In [gui/worker.py](../../../gui/worker.py), replace:

```python
from monthly_schedule.travel import load_api_key, load_cache, save_cache
```

with:

```python
from monthly_schedule.travel import load_cache, save_cache
```

- [ ] **Step 2: Rename the constructor parameter and attribute**

In `ScheduleWorker.__init__`, replace `google_config` with `google_api_key` in the parameter list and the `self.` assignment.

Replace:

```python
    def __init__(
        self,
        mode,
        center_id,
        center_ids,
        plan_code,
        year,
        month,
        out_dir,
        preview,
        db_path,
        google_config,
        geo_cache,
        parent=None,
    ):
        super().__init__(parent)
        self.mode = mode
        self.center_id = center_id
        self.center_ids = center_ids
        self.plan_code = plan_code
        self.year = year
        self.month = month
        self.out_dir = out_dir
        self.preview = preview
        self.db_path = db_path
        self.google_config = google_config
        self.geo_cache = geo_cache
```

with:

```python
    def __init__(
        self,
        mode,
        center_id,
        center_ids,
        plan_code,
        year,
        month,
        out_dir,
        preview,
        db_path,
        google_api_key,
        geo_cache,
        parent=None,
    ):
        super().__init__(parent)
        self.mode = mode
        self.center_id = center_id
        self.center_ids = center_ids
        self.plan_code = plan_code
        self.year = year
        self.month = month
        self.out_dir = out_dir
        self.preview = preview
        self.db_path = db_path
        self.google_api_key = google_api_key
        self.geo_cache = geo_cache
```

- [ ] **Step 3: Replace the file-read block in `_run_inner`**

Replace:

```python
    def _run_inner(self):
        try:
            api_key = load_api_key(self.google_config)
        except RuntimeError as exc:
            self._emit_error(str(exc))
            return

        cache = load_cache(self.geo_cache)
```

with:

```python
    def _run_inner(self):
        api_key = self.google_api_key
        cache = load_cache(self.geo_cache)
```

- [ ] **Step 4: Sanity check — no other references**

Run: `grep -n "google_config\|load_api_key" gui/worker.py`
Expected: no output (zero matches).

- [ ] **Step 5: Commit**

The repo is temporarily broken at the GUI level — `main_window.py` still passes `google_config=...` to this constructor. That's fixed in Task 6. Commit anyway because each task is a logical unit; the GUI is unrunnable until Task 6 lands.

```bash
git add gui/worker.py
git commit -m "refactor(gui/worker): accept google_api_key directly"
```

---

## Task 3: Settings storage + one-time migration

**Files:**
- Modify: `gui/app_settings.py` (whole file rewrite — it's small)
- Create: `tests/test_app_settings.py`

- [ ] **Step 1: Write the failing tests first**

Create [tests/test_app_settings.py](../../../tests/test_app_settings.py) with:

```python
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


def test_load_drops_google_config_when_file_empty(settings_file, tmp_path):
    cfg_path = tmp_path / "google_maps.config"
    cfg_path.write_text("   \n", encoding="utf-8")
    settings_file.write_text(json.dumps({"google_config": str(cfg_path)}))

    from gui import app_settings
    s = app_settings.load()

    assert s["google_api_key"] == ""
    assert "google_config" not in s


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
```

- [ ] **Step 2: Run the tests — confirm they fail**

Run: `pytest tests/test_app_settings.py -v`
Expected: 5 of 6 tests fail (the only currently-passing one is `test_load_passes_through_existing_api_key` if `google_api_key` happens to merge through as-is — it actually will fail too because `google_config` is in `DEFAULTS` and gets merged in). Expect all 6 to fail with `KeyError`, `AssertionError`, or "`google_config` in s" failures.

- [ ] **Step 3: Rewrite `gui/app_settings.py`**

Replace the entire contents of [gui/app_settings.py](../../../gui/app_settings.py) with:

```python
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
        save(merged)
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
```

- [ ] **Step 4: Run the tests — confirm they pass**

Run: `pytest tests/test_app_settings.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add gui/app_settings.py tests/test_app_settings.py
git commit -m "feat(gui/settings): store google_api_key inline; migrate legacy config path"
```

---

## Task 4: i18n string updates

**Files:**
- Modify: `gui/i18n.py:58-82, 100-104, 201-224, 242-246`

- [ ] **Step 1: Update the English dict**

In [gui/i18n.py](../../../gui/i18n.py), in the `"en"` block:

**Replace** the line:
```python
        "settings.google_label": "Google Maps Config File",
```
with:
```python
        "settings.api_key_label": "Google Maps API Key",
```

**Delete** these lines (the entire create-config + file-dialog cluster):
```python
        "settings.create_open": "Create & Open",
        "settings.create_open_tooltip": (
            "Create a new config file and open it in Notepad to paste "
            "your API key"
        ),
```

**Delete**:
```python
        "settings.file_dialog.google": "Select Google Maps Config File",
```

**Replace** the three `settings.test.gc_*` lines:
```python
        "settings.test.gc_not_found": "Google Config: File not found — {path}",
        "settings.test.gc_ok": "Google Config: API key loaded successfully.",
        "settings.test.gc_fail": "Google Config: {error}",
```
with:
```python
        "settings.test.api_key_present": "API Key: provided.",
        "settings.test.api_key_missing": "API Key: missing — enter one above.",
```

**Delete**:
```python
        "settings.file_exists_title": "File Already Exists",
        "settings.file_exists_body": (
            "A config file already exists at:\n{path}\n\n"
            "Open it for editing?"
        ),
        "settings.create_fail_title": "Could Not Create File",
```

**Add** (next to the other settings keys, e.g. right after `settings.test_connection`):
```python
        "settings.api_key.show": "Show",
        "settings.api_key.hide": "Hide",
```

**Replace** the `msg.gc_not_found.*` cluster:
```python
        "msg.gc_not_found.title": "Google Config Not Found",
        "msg.gc_not_found.body": (
            "The Google Maps config file could not be found:\n{path}\n\n"
            "Open Settings to fix the path."
        ),
```
with:
```python
        "msg.api_key_missing.title": "API Key Missing",
        "msg.api_key_missing.body": (
            "Enter your Google Maps API key in Settings before generating."
        ),
```

- [ ] **Step 2: Mirror the changes in the Chinese dict**

In the `"zh"` block, perform the same operations with these translations:

`settings.google_label` → `settings.api_key_label`: `"Google 地图 API 密钥"`

Delete `settings.create_open` ("创建并打开"), `settings.create_open_tooltip`, `settings.file_dialog.google` ("选择 Google 地图配置文件"), `settings.file_exists_title` ("文件已存在"), `settings.file_exists_body`, `settings.create_fail_title` ("无法创建文件").

Replace the three `settings.test.gc_*` with:
```python
        "settings.test.api_key_present": "API 密钥：已填写。",
        "settings.test.api_key_missing": "API 密钥：未填写 — 请在上方输入。",
```

Add (next to `settings.test_connection`):
```python
        "settings.api_key.show": "显示",
        "settings.api_key.hide": "隐藏",
```

Replace `msg.gc_not_found.*` with:
```python
        "msg.api_key_missing.title": "缺少 API 密钥",
        "msg.api_key_missing.body": (
            "生成前请在设置中输入您的 Google 地图 API 密钥。"
        ),
```

- [ ] **Step 3: Run the i18n parity test**

Run: `pytest tests/test_i18n.py -v`
Expected: all pass. If `test_key_parity` fails, the failure message will list keys that exist in one language but not the other — fix the diff.

- [ ] **Step 4: Sanity check — no stale references**

Run: `grep -rn "settings\.google_label\|settings\.create_open\|settings\.file_dialog\.google\|settings\.test\.gc_\|settings\.file_exists\|settings\.create_fail_title\|msg\.gc_not_found" gui/ tests/`
Expected: no output. (If anything matches inside `gui/settings_dialog.py` or `gui/main_window.py`, those references die naturally in Tasks 5 and 6 — that's fine here; we'll re-run after Task 6.)

Actually for now, only check the i18n file itself:

Run: `grep -n "settings\.google_label\|settings\.create_open\|settings\.file_dialog\.google\|settings\.test\.gc_\|settings\.file_exists\|settings\.create_fail_title\|msg\.gc_not_found" gui/i18n.py`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add gui/i18n.py
git commit -m "i18n: API key field strings (en+zh); drop google-config file strings"
```

---

## Task 5: Settings dialog — masked API key field

**Files:**
- Modify: `gui/settings_dialog.py` (substantial — replace `_GoogleConfigRow` and its helpers; rewire dialog)

- [ ] **Step 1: Replace the file-header imports**

In [gui/settings_dialog.py](../../../gui/settings_dialog.py), replace lines 1-23:

```python
import os
import subprocess
import sys

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from monthly_schedule.db import get_member
from monthly_schedule.travel import load_api_key
from gui.errors import friendly_db_error
from gui.i18n import LanguageManager, tr

_GOOGLE_CONFIG_PLACEHOLDER = "PASTE_YOUR_GOOGLE_MAPS_API_KEY_HERE\n"
```

with:

```python
import os

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from monthly_schedule.db import get_member
from gui.errors import friendly_db_error
from gui.i18n import LanguageManager, tr
```

- [ ] **Step 2: Delete `_default_config_dir` and `_GoogleConfigRow`**

Delete lines 26-30 (the `_default_config_dir` function) and lines 70-136 (the entire `_GoogleConfigRow` class). After this, `_PathRow` should be followed directly by `class SettingsDialog`.

- [ ] **Step 3: Add `_ApiKeyRow`**

Insert this class immediately after `_PathRow` (before `class SettingsDialog`):

```python
class _ApiKeyRow(QHBoxLayout):
    def __init__(self, initial_value: str):
        super().__init__()
        self.edit = QLineEdit(initial_value)
        self.edit.setMinimumWidth(320)
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.toggle_btn = QPushButton()
        self.toggle_btn.setFixedWidth(70)
        self.toggle_btn.clicked.connect(self._toggle)
        self.addWidget(self.edit, 1)
        self.addWidget(self.toggle_btn)

    def retranslate(self):
        if self.edit.echoMode() == QLineEdit.EchoMode.Password:
            self.toggle_btn.setText(tr("settings.api_key.show"))
        else:
            self.toggle_btn.setText(tr("settings.api_key.hide"))

    def _toggle(self):
        if self.edit.echoMode() == QLineEdit.EchoMode.Password:
            self.edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_btn.setText(tr("settings.api_key.hide"))
        else:
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_btn.setText(tr("settings.api_key.show"))

    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, v: str):
        self.edit.setText(v)
```

- [ ] **Step 4: Rewire `SettingsDialog.__init__`**

In `SettingsDialog.__init__`, replace the row + label construction:

```python
        self._db_row = _PathRow(
            settings.get("db_path", ""),
            "Access Database (*.accdb *.mdb)",
        )
        self._out_row = _PathRow(settings.get("output_path", ""), pick_dir=True)
        self._gc_row = _GoogleConfigRow(settings.get("google_config", ""))
        self._cache_row = _PathRow(
            settings.get("geo_cache", ""), "JSON files (*.json)"
        )

        self._db_label = QLabel()
        self._out_label = QLabel()
        self._gc_label = QLabel()
        self._cache_label = QLabel()

        form.addRow(self._db_label, self._db_row)
        form.addRow(self._out_label, self._out_row)
        form.addRow(self._gc_label, self._gc_row)
        form.addRow(self._cache_label, self._cache_row)
```

with:

```python
        self._db_row = _PathRow(
            settings.get("db_path", ""),
            "Access Database (*.accdb *.mdb)",
        )
        self._out_row = _PathRow(settings.get("output_path", ""), pick_dir=True)
        self._key_row = _ApiKeyRow(settings.get("google_api_key", ""))
        self._cache_row = _PathRow(
            settings.get("geo_cache", ""), "JSON files (*.json)"
        )

        self._db_label = QLabel()
        self._out_label = QLabel()
        self._api_key_label = QLabel()
        self._cache_label = QLabel()

        form.addRow(self._db_label, self._db_row)
        form.addRow(self._out_label, self._out_row)
        form.addRow(self._api_key_label, self._key_row)
        form.addRow(self._cache_label, self._cache_row)
```

- [ ] **Step 5: Rewire `_retranslate`**

Replace:

```python
        self._db_label.setText(tr("settings.db_label"))
        self._out_label.setText(tr("settings.output_label"))
        self._gc_label.setText(tr("settings.google_label"))
        self._cache_label.setText(tr("settings.cache_label"))
        self._db_row.retranslate()
        self._out_row.retranslate()
        self._gc_row.retranslate()
        self._cache_row.retranslate()
```

with:

```python
        self._db_label.setText(tr("settings.db_label"))
        self._out_label.setText(tr("settings.output_label"))
        self._api_key_label.setText(tr("settings.api_key_label"))
        self._cache_label.setText(tr("settings.cache_label"))
        self._db_row.retranslate()
        self._out_row.retranslate()
        self._key_row.retranslate()
        self._cache_row.retranslate()
```

- [ ] **Step 6: Rewire `_test_connection`**

Replace:

```python
    def _test_connection(self):
        db_path = self._db_row.value()
        gc_path = self._gc_row.value()
        lines = []

        if not os.path.isfile(db_path):
            lines.append(tr("settings.test.db_not_found", path=db_path))
        else:
            try:
                get_member(0, db_path)
                lines.append(tr("settings.test.db_ok"))
            except RuntimeError as exc:
                lines.append(
                    tr("settings.test.db_fail", error=friendly_db_error(str(exc)))
                )
            except Exception as exc:
                lines.append(tr("settings.test.db_fail", error=str(exc)))

        if not os.path.isfile(gc_path):
            lines.append(tr("settings.test.gc_not_found", path=gc_path))
        else:
            try:
                load_api_key(gc_path)
                lines.append(tr("settings.test.gc_ok"))
            except RuntimeError as exc:
                lines.append(tr("settings.test.gc_fail", error=str(exc)))

        QMessageBox.information(
            self, tr("settings.test_result_title"), "\n".join(lines)
        )
```

with:

```python
    def _test_connection(self):
        db_path = self._db_row.value()
        api_key = self._key_row.value()
        lines = []

        if not os.path.isfile(db_path):
            lines.append(tr("settings.test.db_not_found", path=db_path))
        else:
            try:
                get_member(0, db_path)
                lines.append(tr("settings.test.db_ok"))
            except RuntimeError as exc:
                lines.append(
                    tr("settings.test.db_fail", error=friendly_db_error(str(exc)))
                )
            except Exception as exc:
                lines.append(tr("settings.test.db_fail", error=str(exc)))

        if api_key:
            lines.append(tr("settings.test.api_key_present"))
        else:
            lines.append(tr("settings.test.api_key_missing"))

        QMessageBox.information(
            self, tr("settings.test_result_title"), "\n".join(lines)
        )
```

- [ ] **Step 7: Rewire `_save`**

Replace:

```python
    def _save(self):
        self._result = {
            "db_path": self._db_row.value(),
            "output_path": self._out_row.value(),
            "google_config": self._gc_row.value(),
            "geo_cache": self._cache_row.value(),
        }
        self.accept()
```

with:

```python
    def _save(self):
        self._result = {
            "db_path": self._db_row.value(),
            "output_path": self._out_row.value(),
            "google_api_key": self._key_row.value(),
            "geo_cache": self._cache_row.value(),
        }
        self.accept()
```

- [ ] **Step 8: Sanity check the dialog file**

Run: `grep -n "google_config\|load_api_key\|_GoogleConfigRow\|_gc_row\|_gc_label\|_default_config_dir\|_GOOGLE_CONFIG_PLACEHOLDER\|subprocess\|^import sys" gui/settings_dialog.py`
Expected: no output.

Run: `python -c "from gui.settings_dialog import SettingsDialog, _ApiKeyRow"`
Expected: no error (import smoke test).

- [ ] **Step 9: Commit**

```bash
git add gui/settings_dialog.py
git commit -m "feat(gui/settings): masked API key field with Show/Hide toggle"
```

---

## Task 6: Main window — validation + worker call

**Files:**
- Modify: `gui/main_window.py:339-346, 387-399`

- [ ] **Step 1: Update `_validate()`**

In [gui/main_window.py](../../../gui/main_window.py), replace:

```python
        gc_path = self._settings.get("google_config", "")
        if not os.path.isfile(gc_path):
            QMessageBox.warning(
                self,
                tr("msg.gc_not_found.title"),
                tr("msg.gc_not_found.body", path=gc_path),
            )
            return False
```

with:

```python
        if not self._settings.get("google_api_key", "").strip():
            QMessageBox.warning(
                self,
                tr("msg.api_key_missing.title"),
                tr("msg.api_key_missing.body"),
            )
            return False
```

- [ ] **Step 2: Update `_run()` — worker construction**

Replace the kwarg:

```python
            google_config=self._settings["google_config"],
```

with:

```python
            google_api_key=self._settings["google_api_key"],
```

- [ ] **Step 3: Sanity check the GUI module**

Run: `grep -rn "google_config\|load_api_key" gui/`
Expected: no output anywhere in `gui/`.

Run: `python -c "from gui.main_window import MainWindow"`
Expected: no error.

- [ ] **Step 4: Run the full test suite to confirm nothing regressed**

Run: `pytest`
Expected: all tests pass. (test_travel.py still has the three `test_load_api_key_*` — they should still pass because we haven't removed the function yet. They'll be deleted in Task 7.)

- [ ] **Step 5: Commit**

```bash
git add gui/main_window.py
git commit -m "feat(gui/main): require non-empty google_api_key; pass to worker"
```

---

## Task 7: Delete `monthly_schedule.travel.load_api_key`

**Files:**
- Modify: `monthly_schedule/travel.py:97-110`
- Modify: `tests/test_travel.py:103-118`

- [ ] **Step 1: Verify nothing in the repo still imports `load_api_key`**

Run: `grep -rn "load_api_key" .` (excluding `.git`)

Expected: only matches in `monthly_schedule/travel.py` (definition), `tests/test_travel.py` (the 3 tests we're about to delete), and `docs/`. If any source file outside docs still imports it, fix that file first.

- [ ] **Step 2: Delete the function**

In [monthly_schedule/travel.py](../../../monthly_schedule/travel.py), delete lines 97-110 (the entire `load_api_key` function plus the blank line before it). The next thing after `save_cache` should be the `GEOCODE_URL` constant.

- [ ] **Step 3: Delete the three tests**

In [tests/test_travel.py](../../../tests/test_travel.py), delete the three functions:
- `test_load_api_key_reads_trimmed`
- `test_load_api_key_missing_raises`
- `test_load_api_key_empty_raises`

(Lines 103-118 plus any leading/trailing blank lines as needed for clean formatting.)

- [ ] **Step 4: Run the test suite**

Run: `pytest`
Expected: all tests pass. (Three fewer than before.)

- [ ] **Step 5: Final repo-wide sanity check**

Run: `grep -rn "load_api_key\|google_config" . --include="*.py"`
Expected: zero matches anywhere in `.py` files. (Docs may still reference them — that's fine, they're historical.)

- [ ] **Step 6: Commit**

```bash
git add monthly_schedule/travel.py tests/test_travel.py
git commit -m "refactor(travel): remove load_api_key; key is passed in directly"
```

---

## Task 8: Manual GUI verification + migration smoke test

This task has no code changes — it's a manual check of the things automated tests can't cover.

- [ ] **Step 1: Confirm `bsca_settings.json` still has the legacy shape**

Run: `cat bsca_settings.json`
Expected: a JSON object that includes `"google_config": "google_maps.config"` and does NOT include `"google_api_key"`.

If `google_api_key` is already in there, the migration has already run from a prior local test — that's fine, but you won't be able to verify migration behavior. Either skip Step 2 or temporarily restore the legacy state by editing the file.

- [ ] **Step 2: Launch the app and verify migration**

Run: `python gui.py`

In a second terminal: `cat bsca_settings.json`

Expected: `google_api_key` is now present with the value that was inside `google_maps.config`, and `google_config` is gone. The app's main window should be open and look normal.

- [ ] **Step 3: Open Settings dialog — verify the field**

In the app, click ⚙ to open Settings.

Expected:
- The form has a row labeled "Google Maps API Key" (or "Google 地图 API 密钥" if your language setting is `zh`) with a masked field showing dots, and a "Show"/"显示" button.
- No "Google Maps Config File" row, no "Browse…" or "Create & Open" buttons next to the key.
- Clicking "Show" reveals the key as plaintext and the button changes to "Hide"/"隐藏". Clicking again re-masks.

- [ ] **Step 4: Test Connection**

Click "Test Connection".

Expected: the result dialog shows two lines — one about the database, one saying "API Key: provided." (or "API 密钥：已填写。"). Close the dialog.

- [ ] **Step 5: Clear the key and try to generate**

In Settings, clear the API key field. Click Save.

On the main window, click "Generate Schedule" (with any valid member ID + month selected).

Expected: a warning dialog titled "API Key Missing" (or "缺少 API 密钥") with the body asking you to enter your key in Settings. Generation does not start.

- [ ] **Step 6: Re-enter the key and generate**

Re-open Settings, paste the key back in, Save. Run a single-member preview (Preview-only checkbox checked, any valid Member ID). Confirm it produces preview log lines without an "API key" error.

- [ ] **Step 7: Confirm `google_maps.config` was NOT deleted**

Run: `ls google_maps.config`
Expected: file still exists on disk. (The migration reads it; it doesn't delete it. You may now delete it manually if you want — it's no longer referenced.)

- [ ] **Step 8: No commit needed**

This task only confirms behavior; no files changed. End of plan.

---

## Spec Coverage Verification

Quick sweep through the spec to confirm every requirement maps to a task:

| Spec section | Task |
|---|---|
| `app_settings.py` DEFAULTS change + migration | Task 3 |
| `settings_dialog.py` delete `_GoogleConfigRow` + helpers | Task 5 (Step 2) |
| `settings_dialog.py` new `_ApiKeyRow` w/ Show/Hide toggle | Task 5 (Step 3) |
| `settings_dialog.py` rewire `_save` and `_test_connection` | Task 5 (Steps 6–7) |
| `main_window.py` `_validate()` non-empty key check | Task 6 (Step 1) |
| `main_window.py` `_run()` passes `google_api_key` | Task 6 (Step 2) |
| `worker.py` constructor + drop file-read | Task 2 |
| `travel.py` delete `load_api_key()` | Task 7 (Step 2) |
| CLI `--api-key` replaces `--google-config` | Task 1 (Steps 3–4) |
| i18n add/remove keys, en+zh | Task 4 |
| Manual: migration end-to-end | Task 8 (Step 2) |
| Manual: Show/Hide toggle | Task 8 (Step 3) |
| Manual: empty-key warning | Task 8 (Step 5) |
