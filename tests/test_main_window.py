"""Offscreen tests for the landscape main window (spec 2026-09-23)."""

import json
import os

import pytest

pytest.importorskip("PyQt6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from gui import app_settings  # noqa: E402

# Held in a module global: an unreferenced QApplication is garbage
# collected and the next widget built on it crashes the process.
_APP = None


@pytest.fixture(scope="module")
def app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    """A MainWindow backed by a throwaway settings file whose DB path
    does not exist, so the counts fetch fails fast and quietly."""
    settings_file = tmp_path / "bsca_settings.json"
    settings = dict(app_settings.DEFAULTS)
    settings["db_path"] = str(tmp_path / "missing.accdb")
    settings["output_path"] = str(tmp_path)
    settings_file.write_text(json.dumps(settings))
    monkeypatch.setattr(app_settings, "_SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr("gui.i18n._current_lang", "en")
    from gui.main_window import MainWindow
    w = MainWindow()
    yield w
    # Never let a running QThread reach interpreter teardown.
    for worker in list(w._counts_workers):
        worker.wait()
    w.deleteLater()
    app.processEvents()


def test_window_is_landscape_and_fully_visible(window):
    w = window
    assert w.minimumWidth() >= 1100 and w.minimumHeight() >= 680
    assert w.width() >= 1280 and w.height() >= 720
    assert w.width() > w.height()
    assert w._left_panel.maximumWidth() <= 600
    # Every left-column control fits inside the default window height.
    assert w._left_panel.sizeHint().height() <= 680


def _quiet_warning(monkeypatch):
    monkeypatch.setattr("gui.main_window.QMessageBox.warning",
                        lambda *a, **k: None)


def _ok_payload(paths):
    return {
        "scope": {"year": 2026, "month": 9, "mode": "single"},
        "verb_key": "summary.verb.wrote",
        "success": len(paths),
        "total": len(paths),
        "out_dir": None,
        "failures": [],
        "generated_paths": paths,
    }


def test_summary_pane_shows_result(window, monkeypatch):
    _quiet_warning(monkeypatch)
    w = window
    w._on_finished(True, _ok_payload(["a.xlsx"]))
    assert w._summary.toPlainText().strip() != ""
    assert w._log.toPlainText() == ""
    assert w._generate_btn.isEnabled()
    w._on_finished(False, {"error_text": "bad"})
    assert w._summary.toPlainText() == "bad"


def test_print_button_enabled_only_after_generation(window, monkeypatch):
    _quiet_warning(monkeypatch)
    w = window
    assert not w._print_btn.isEnabled()
    w._on_finished(True, _ok_payload(["a.xlsx"]))
    assert w._print_btn.isEnabled()
    w._on_finished(True, _ok_payload([]))
    assert not w._print_btn.isEnabled()


def test_open_folder_falls_back_to_settings_path(window, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr("gui.main_window.sys.platform", "win32")
    monkeypatch.setattr("gui.main_window.os.startfile",
                        lambda p: opened.append(p), raising=False)
    w = window
    w._last_out_dir = None
    w._open_output_folder()
    assert opened == [str(tmp_path)]
