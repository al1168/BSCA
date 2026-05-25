# GUI Internationalization (English / Simplified Chinese)

**Date:** 2026-05-25
**Status:** Approved (pending spec review)
**Scope:** PyQt6 GUI in [gui/](../../../gui/) and the launcher [gui.py](../../../gui.py)

## Goal

Let users switch the entire GUI between English and Simplified Chinese
(简体中文) at runtime. Translations cover all visible UI text including
worker progress log lines and message-box dialogs. The user's choice
persists across sessions.

## Design Decisions (Recap From Brainstorming)

| Decision | Choice |
| --- | --- |
| Chinese variant | Simplified only (no Traditional, no per-user picker) |
| Translation scope | Everything visible — labels, buttons, group titles, tooltips, all `QMessageBox` dialogs, worker log lines, and the post-run summary |
| Toggle placement | `QComboBox` in the top bar, immediately left of the ⚙ Settings button |
| Switch behavior | Live retranslation — no restart needed |
| Implementation approach | Simple dict-based `tr()` lookup in a single `gui/i18n.py` module (not Qt's `QTranslator` / `.ts` / `.qm` toolchain) |

## Architecture

### New module: `gui/i18n.py`

Single source of truth for translations and language state. Contents:

1. **`STRINGS: dict[str, dict[str, str]]`**

   Two top-level keys, `"en"` and `"zh"`. Each maps key → translated
   string. Format placeholders use Python `str.format` syntax (e.g.
   `"Wrote {filename}"`).

2. **Module-level `_current_lang: str`** — starts as `"en"`.

3. **`tr(key: str, **fmt) -> str`**

   - Looks up `STRINGS[_current_lang][key]`.
   - If the key is missing, returns the key string itself (no exception,
     no fallback to English) so missing translations are visible in
     development.
   - Applies `.format(**fmt)` if `fmt` is provided.

4. **`LanguageManager(QObject)` singleton**

   - Exposes a Qt signal `languageChanged = pyqtSignal(str)`.
   - `instance()` classmethod for the singleton accessor.
   - `set_language(lang: str)`:
     1. Updates `_current_lang`.
     2. Persists the choice to `bsca_settings.json` via
        [gui/app_settings.py](../../../gui/app_settings.py) `save()`.
     3. Emits `languageChanged.emit(lang)`.

### Retranslate contract for widgets

Every widget that holds translatable text MUST:

1. In `__init__`, create child widgets without hardcoding any English
   text (use empty strings or set text via the retranslate step).
2. Define `_retranslate(self)` — calls `setText`, `setTitle`,
   `setToolTip`, `setPlaceholderText`, `setWindowTitle`, etc. for every
   string it owns, sourcing each from `tr(...)`.
3. Call `LanguageManager.instance().languageChanged.connect(self._retranslate)`
   once.
4. Call `self._retranslate()` once at the end of `__init__` so the
   first paint is in the current language.

### Widget changes

| File | Change |
| --- | --- |
| [gui/main_window.py](../../../gui/main_window.py) | Add `_lang_combo`; route all strings through `tr()`; add `_retranslate()`. Module-level `MONTHS` list moves into `i18n.py`. |
| [gui/settings_dialog.py](../../../gui/settings_dialog.py) | Route all strings through `tr()`; add `_retranslate()`. Includes the `_PathRow`/`_GoogleConfigRow` "Browse…" / "Create & Open" labels. |
| [gui/worker.py](../../../gui/worker.py) | Change `log_line` signal shape: `pyqtSignal(str, dict)` carrying `(key, fmt_args)`. Change `finished` signal shape: `pyqtSignal(bool, dict)` carrying `(success, summary_data)` instead of a pre-formatted string. Update emitters. Replace `scope = f"plan {CODE} {YYYY-MM}"` string concatenation with a structured `scope_data` dict. |
| [gui/errors.py](../../../gui/errors.py) | `friendly_db_error()` calls `tr()` directly and returns a translated string. (Both call sites are inside Python — `gui/worker.py` and `gui/settings_dialog.py` — so a translated return value works without changing signal shapes.) |
| [new_monthly_schedule.py](../../../new_monthly_schedule.py) | **No change.** `format_summary()` stays English-only and remains the CLI's renderer. Keeping the CLI free of any `gui/` import avoids pulling PyQt6 into command-line use. The GUI builds its translated summary from the structured data emitted by the worker. |
| [gui/app_settings.py](../../../gui/app_settings.py) | Add `"language": "en"` to `DEFAULTS`. |
| [gui.py](../../../gui.py) | Before constructing `MainWindow`, call `LanguageManager.instance().set_language(settings.get("language", "en"))`. |

### Top-bar dropdown layout

```
┌────────────────────────────────────────────────────────────┐
│  Monthly Schedule Generator              [English ▾] [⚙]   │
├────────────────────────────────────────────────────────────┤
│  Who                                                       │
│  ● Single Member   ○ Multiple Members   ○ Entire Plan      │
│  ...                                                       │
```

The combo has two items, each carrying `userData`:

| Display | userData |
| --- | --- |
| `English` | `"en"` |
| `中文` | `"zh"` |

Fixed width ~90 px. `currentIndexChanged` handler calls
`LanguageManager.instance().set_language(combo.currentData())`. The
combo's own item labels are self-identifying in their own scripts and
do not need retranslation.

## String Key Catalog

Naming convention: `<area>.<element>[.<variant>]`. Approximate target is
**~70 keys**. Final list is settled when implementing — this is the
inventory the implementer must cover:

| Namespace | Description | Approx. keys |
| --- | --- | --- |
| `app.*` | Window titles (main, settings, first-run) | 3 |
| `top.*` | Top-bar title, settings tooltip | 2 |
| `who.*` | Group title, 3 radio labels, 3 panel labels, multi-id placeholder | 8 |
| `when.*` | "Month:", "Year:", 12 month names | 14 |
| `save.*` | Group title, "Change…" button | 2 |
| `opts.*` | Preview checkbox, Generate button, Open Output Folder button | 3 |
| `settings.*` | Welcome blurb, 4 row labels, Browse…, Create & Open, Test Connection, file/folder dialog titles | ~9 |
| `msg.*` | All `QMessageBox` titles + bodies, each with `{path}` / `{ids}` interpolation as needed | ~12 |
| `worker.*` | "Preview: {id} ({last}, {first})", "Wrote {filename}", "No members found for plan {plan}", "Cannot create output folder: {error}" | ~5 |
| `summary.*` | Headline template ("Wrote N of M member(s) for {scope}"), "into {dir}" suffix, "; N failed." tail, "Failures:" header, failure-row formats (with-name / without-name), per-stage labels (`geocode`, `route`, `generate`, `write`, `lookup`), "not found in database" reason | ~11 |
| `scope.*` | "plan {code} {YYYY-MM}" (plan mode), "{YYYY-MM}" (single/multiple mode) — used by the GUI's summary renderer | 2 |
| `errors.*` | `errors.driver_missing` (the multi-line ODBC-missing hint), `errors.db_generic` ("Could not connect to the database:\\n\\n{message}") | 2 |

The two `STRINGS["en"]` / `STRINGS["zh"]` sub-dicts must have identical
key sets, enforced by a unit test (see Testing).

### Translation responsibility

The implementer produces both columns. Chinese translations target a
**business / clerical register** appropriate for a scheduling tool used
by office staff. Examples for calibration:

| Key | en | zh |
| --- | --- | --- |
| `app.main_title` | Monthly Schedule Generator | 月度日程生成器 |
| `who.title` | Who | 人员 |
| `who.single` | Single Member | 单个成员 |
| `who.multiple` | Multiple Members | 多个成员 |
| `who.plan` | Entire Plan | 整个计划 |
| `when.title` | When | 时间 |
| `opts.preview` | Preview only (don't save files) | 仅预览（不保存文件） |
| `opts.generate` | Generate Schedule | 生成日程 |
| `worker.wrote` | Wrote {filename} | 已写入 {filename} |

(These are starting points — the implementer should refine for
consistency and review with the user before merging.)

## Worker Signal Changes

Two worker signals change shape; their only consumer is
[gui/main_window.py](../../../gui/main_window.py), so the blast radius
is limited to that file.

### `log_line`

**Current:** `pyqtSignal(str)` — emits pre-formatted English strings
like `"Wrote Schedule_24010_2026-05.xlsx"`.

**New:** `pyqtSignal(str, dict)` — emits `(key, fmt_args)`, e.g.
`self.log_line.emit("worker.wrote", {"filename": fname})`.

**Consumer:**

```python
def _on_log_line(self, key: str, args: dict):
    self._log.appendPlainText(tr(key, **args))
```

### `finished`

**Current:** `pyqtSignal(bool, str)` — emits `(success, summary)`
where `summary` is the string returned by `format_summary()`.

**New:** `pyqtSignal(bool, dict)` — emits `(success, summary_data)`
where `summary_data` is:

```python
{
    "verb_key": "summary.verb.wrote",   # or "summary.verb.previewed"
    "success": int,                     # successful members
    "total":   int,                     # total attempted
    "scope": {                          # structured, not pre-formatted
        "plan_code": "HOF" | None,      # None => single/multi mode
        "year":  2026,
        "month": 5,
    },
    "out_dir": str | None,              # None when previewing
    "failures": [
        {"center_id": int, "name": str, "stage": str, "reason_key": str | None, "reason": str},
        ...
    ],
}
```

The GUI constructs the translated summary from this dict using a new
`_build_summary(data)` helper in `main_window.py` that calls `tr()`
for each piece — headline, scope, "into {dir}", "; N failed.",
"Failures:", each failure row, each stage label, the "not found in
database" reason. Stages that are exception-derived (e.g.
`"geocode"` from `TravelError`) get translated stage names but pass
the raw `reason` string through untranslated (technical detail).

**Error-path emissions** in the worker — `f"No members found for
plan {CODE}."`, `f"Cannot create output folder: {exc}"`,
`friendly_db_error(...)` — also flow through `finished`. The dict
schema uses a sentinel `"error_text"` key to distinguish error paths:

```python
# Success path:
{"verb_key": "...", "success": ..., "total": ..., "scope": {...}, "out_dir": ..., "failures": [...]}
# Error path (early exit, no run summary):
{"error_text": "Could not connect to the database:\n\n[ODBC ...]"}
```

The worker calls `tr()` directly to build `error_text` at emit time
(safe — `tr()` is a thread-free dict lookup). `friendly_db_error()`
likewise calls `tr()` and returns a translated string, used directly
by both the worker (wrapped into `error_text`) and the settings
dialog's "Test Connection" button.

The GUI's `_on_finished` checks for `"error_text"` first, renders that,
otherwise renders the run summary.

This keeps the worker thread free of UI-language state and means a
mid-run language switch does NOT retroactively re-render lines
already appended to the log box. Acceptable — the log is a record of
what was emitted at the time. The final summary, however, IS rendered
at the moment `_on_finished` runs, so a language switch immediately
after the run completes will show the new language's summary.

## Persistence

[gui/app_settings.py](../../../gui/app_settings.py) `DEFAULTS` gains:

```python
"language": "en",
```

`LanguageManager.set_language()` loads the current settings dict,
updates `"language"`, and calls `app_settings.save()`. On app start,
[gui.py](../../../gui.py) `main()` reads `settings["language"]` before
building any widgets and seeds `LanguageManager` so the first paint is
in the chosen language.

## Error Handling and Edge Cases

| Case | Behavior |
| --- | --- |
| `tr()` called with an unknown key | Returns the key string verbatim — visible bug, no crash |
| `tr()` called with extra `**fmt` args | `str.format` ignores extras — fine |
| `tr()` called with missing `**fmt` args | `KeyError` — let it crash; caught by unit tests |
| Settings file has `"language": "fr"` (unknown) | `tr()` falls through to "missing key" behavior on every call. Mitigation: on app start, validate the loaded language against the known set and fall back to `"en"` if unknown |
| Language switched mid-generation run | New lines emitted after the switch render in the new language; lines already in the log box stay as they were rendered. Acceptable. |

## Testing

**New: `tests/test_i18n.py`**

- `test_key_parity` — `set(STRINGS["en"]) == set(STRINGS["zh"])`.
- `test_missing_key_returns_key` — `tr("nope.nada") == "nope.nada"`.
- `test_format_interpolation` —
  `tr("worker.wrote", filename="a.xlsx")` returns the string with
  `{filename}` replaced.
- `test_language_persistence` — calling
  `LanguageManager.instance().set_language("zh")` writes `"zh"` into
  the settings file. (Use a `tmp_path` to redirect the settings file.)

**Manual smoke test** (no automation in this repo for the GUI):

1. Launch the app. Confirm dropdown reads `English` and UI is English.
2. Select `中文` from the dropdown. Confirm all visible labels, group
   titles, buttons, and tooltips switch immediately.
3. Open Settings dialog. Confirm it renders in Chinese.
4. Run a small generation (preview mode). Confirm log lines and the
   final summary render in Chinese.
5. Trigger one validation error (e.g. blank member ID). Confirm the
   `QMessageBox` is in Chinese.
6. Close and relaunch the app. Confirm it opens in Chinese (persisted).
7. Switch back to English. Confirm same behavior in reverse.

## Out of Scope (YAGNI)

- Plural rules (no plurals in the current UI).
- Right-to-left layouts.
- Per-string contextual variants.
- Translating data values (member names, plan codes, file paths).
- Translating Windows OS dialogs — `QFileDialog`, default `QMessageBox`
  buttons. Qt translates those itself based on system locale; we do
  not install a `QTranslator`.
- Traditional Chinese (decided in brainstorming).
- Localizing date / number formats (months use Chinese names; numbers
  stay Arabic).

## File Inventory (What Will Change)

New:
- `gui/i18n.py`
- `tests/test_i18n.py`
- `docs/superpowers/specs/2026-05-25-gui-i18n-design.md` (this file)

Modified:
- `gui.py`
- `gui/app_settings.py`
- `gui/main_window.py`
- `gui/settings_dialog.py`
- `gui/worker.py`
- `gui/errors.py`

No change:
- `new_monthly_schedule.py` (CLI stays English-only; `format_summary` untouched)
- `monthly_schedule/*` (data layer)
- `MonthlyScheduleGenerator.spec` (no new bundled data)
- `requirements.txt`
