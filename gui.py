import sys

from PyQt6.QtWidgets import QApplication

from gui import app_settings
from gui.i18n import LanguageManager
from gui.main_window import MainWindow
from gui.settings_dialog import SettingsDialog


_SUPPORTED_LANGS = {"en", "zh"}


def _run_first_time_setup(app: QApplication) -> bool:
    settings = app_settings.load()
    dlg = SettingsDialog(settings, first_run=True)
    if not dlg.exec():
        return False
    result = dlg.get_settings()
    if result:
        settings.update(result)
        app_settings.save(settings)
    return True


def _seed_language():
    settings = app_settings.load()
    lang = settings.get("language", "en")
    if lang not in _SUPPORTED_LANGS:
        lang = "en"
    LanguageManager.instance().set_language(lang)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _seed_language()

    if not app_settings.exists():
        if not _run_first_time_setup(app):
            sys.exit(0)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
