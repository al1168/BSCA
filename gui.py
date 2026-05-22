import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from gui import app_settings
from gui.main_window import MainWindow
from gui.settings_dialog import SettingsDialog


def _run_first_time_setup(app: QApplication) -> bool:
    """Show the initial setup dialog. Returns False if the user cancels."""
    settings = app_settings.load()
    dlg = SettingsDialog(settings, first_run=True)
    if not dlg.exec():
        return False
    result = dlg.get_settings()
    if result:
        settings.update(result)
        app_settings.save(settings)
    return True


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    if not app_settings.exists():
        if not _run_first_time_setup(app):
            sys.exit(0)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
