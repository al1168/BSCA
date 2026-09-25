"""Offscreen tests for the landscape main window (spec 2026-09-23)."""

import json
import os

import pytest

pytest.importorskip("PyQt6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The offscreen platform ships no fonts; its fallback glyphs are smaller
# than Segoe UI, which made the height check pass at 656px when the
# real window measured 710px. Point Qt at the Windows fonts so the
# geometry test sees the same metrics as the running app.
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PyQt6.QtGui import QFont  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from gui import app_settings  # noqa: E402

# Held in a module global: an unreferenced QApplication is garbage
# collected and the next widget built on it crashes the process.
_APP = None


@pytest.fixture(scope="module")
def app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    _APP.setStyle("Fusion")                 # as gui.py does
    if "Segoe UI" in QFont("Segoe UI").family():
        _APP.setFont(QFont("Segoe UI", 9))  # the Windows default
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


def test_long_output_path_stays_on_one_line(window):
    w = window
    long_path = "C:\\" + "\\".join(["a-very-long-folder-name"] * 8)
    w._set_out_path(long_path)
    assert "…" in w._out_label.text()
    assert w._out_label.toolTip() == long_path
    assert w._out_label.sizeHint().height() <= w._change_btn.sizeHint().height()


# ── Scaling on large windows (spec 2026-09-25) ──────────────────────
# The layout is tuned for 1280x720. A bigger window (maximized on a
# 1080p monitor) scales text and fixed-size controls up in 0.1 steps:
# as far as the width allows, then down until the left column fits
# the height. The left column keeps the share of the window it has by
# default instead of the right-hand panes taking all the extra room.

def _show_at(w, width, height):
    w.show()
    w.resize(width, height)
    QApplication.processEvents()


def _left_content_bottom(w):
    box = w._actions_box
    return box.mapTo(w, box.rect().bottomLeft()).y()


def test_max_ui_scale_follows_window_width():
    from gui.main_window import max_ui_scale
    assert max_ui_scale(1280) == 1.0
    assert max_ui_scale(1100) == 1.0      # never below the design size
    assert max_ui_scale(1366) == 1.0      # maximized 1366x768 laptop
    assert max_ui_scale(1920) == 1.5      # maximized 1080p
    assert max_ui_scale(1700) == 1.3
    assert max_ui_scale(5000) == 2.0      # capped


def test_maximized_1080p_window_scales_up_and_stays_balanced(window):
    w = window
    _show_at(w, 1920, 1009)
    s = w._ui_scale
    assert s == 1.5
    # Text and fixed-size controls grow together.
    assert w._title_label.font().pointSizeF() == pytest.approx(13 * s)
    assert w._generate_btn.font().pointSizeF() == pytest.approx(11 * s)
    assert w._log.font().pointSizeF() == pytest.approx(9 * s)
    assert w.font().pointSizeF() == pytest.approx(9 * s)
    assert w._generate_btn.height() == round(34 * s)
    assert w._lang_combo.width() == round(90 * s)
    assert w._change_btn.width() == round(80 * s)
    assert f"font-size: {round(11 * s)}px" in w._scope_label.styleSheet()
    # Every plan row, All Members included, is still fully visible.
    t = w._plan_table
    assert t.verticalHeader().defaultSectionSize() == round(22 * s)
    last = t.visualRect(t.model().index(t.rowCount() - 1, 0))
    assert last.bottom() < t.viewport().height()
    # The left column keeps its default share of the width (about 40%;
    # unscaled it was 27%) and its controls fill the height the way
    # they do at the default size, without running off the bottom.
    assert w._left_panel.width() >= 0.39 * w.width()
    assert 0.9 * w.height() <= _left_content_bottom(w) <= w.height()


def test_wide_short_window_scales_only_as_far_as_the_height_allows(window):
    w = window
    _show_at(w, 2560, 720)
    assert w._ui_scale == 1.0
    assert _left_content_bottom(w) <= w.height()
    _show_at(w, 2560, 900)
    assert 1.0 < w._ui_scale < 2.0
    assert _left_content_bottom(w) <= w.height()


def test_scale_returns_to_normal_when_window_shrinks(window):
    w = window
    _show_at(w, 1920, 1009)
    _show_at(w, 1280, 720)
    assert w._ui_scale == 1.0
    assert w._title_label.font().pointSizeF() == pytest.approx(13)
    assert w._generate_btn.height() == 34
    assert w._left_panel.maximumWidth() == 560
    assert _left_content_bottom(w) <= w.height()


def test_chinese_text_still_fits_when_scaled(window):
    from gui.i18n import LanguageManager
    w = window
    _show_at(w, 1920, 1009)
    LanguageManager.instance().set_language("zh")
    try:
        QApplication.processEvents()
        assert w._ui_scale > 1.0
        assert _left_content_bottom(w) <= w.height()
    finally:
        LanguageManager.instance().set_language("en")


def test_output_path_elides_to_the_scaled_width(window):
    from gui.main_window import OUT_PATH_WIDTH
    w = window
    long_path = "C:\\" + "\\".join(["a-very-long-folder-name"] * 8)
    w._set_out_path(long_path)
    _show_at(w, 1920, 1009)
    text = w._out_label.text()
    assert "…" in text
    advance = w._out_label.fontMetrics().horizontalAdvance(text)
    assert OUT_PATH_WIDTH < advance <= round(OUT_PATH_WIDTH * w._ui_scale)
