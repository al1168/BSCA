import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
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


# Known-good address used to verify Google accepts the API key. Google's
# own HQ — should always resolve when the key + project are wired up.
_TEST_ADDRESS = "1600 Amphitheatre Pkwy, Mountain View, CA"


def _check_google_api_key(key: str) -> tuple[str, str]:
    """Ping Google's Geocoding API with a known-good address.

    Returns (result, detail) where result is one of:
      "OK"            — Google accepted the key and resolved the address.
      "INVALID"       — Google rejected the request; `detail` is Google's
                        own error_message text.
      "NETWORK_ERROR" — could not reach Google; `detail` is the exception
                        message.
    """
    import requests  # local import — keeps Settings dialog cheap to import.
    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": _TEST_ADDRESS, "key": key},
            timeout=10,
        )
        body = r.json()
    except (requests.RequestException, ValueError) as exc:
        return ("NETWORK_ERROR", str(exc))
    status = body.get("status", "")
    if status == "OK":
        return ("OK", "")
    return ("INVALID", body.get("error_message") or status or "unknown error")


class _PathRow(QHBoxLayout):
    def __init__(self, default_path: str, file_filter: str = "", pick_dir: bool = False):
        super().__init__()
        self._filter = file_filter
        self._pick_dir = pick_dir
        self.edit = QLineEdit(default_path)
        self.edit.setMinimumWidth(320)
        self.browse_btn = QPushButton()
        self.browse_btn.setFixedWidth(80)
        self.browse_btn.clicked.connect(self._browse)
        self.addWidget(self.edit, 1)
        self.addWidget(self.browse_btn)

    def retranslate(self):
        self.browse_btn.setText(tr("settings.browse"))

    def _browse(self):
        if self._pick_dir:
            path = QFileDialog.getExistingDirectory(
                None, tr("settings.file_dialog.folder"), self.edit.text()
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                None,
                tr("settings.file_dialog.file"),
                self.edit.text(),
                self._filter,
            )
        if path:
            self.edit.setText(path)

    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, v: str):
        self.edit.setText(v)


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


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None, first_run: bool = False):
        super().__init__(parent)
        self.setMinimumWidth(560)
        self._first_run = first_run
        self._result: dict | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._welcome = None
        if first_run:
            self._welcome = QLabel()
            self._welcome.setWordWrap(True)
            layout.addWidget(self._welcome)

        form = QFormLayout()
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        form.setVerticalSpacing(10)

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
        layout.addLayout(form)

        self._test_btn = None
        if not first_run:
            self._test_btn = QPushButton()
            self._test_btn.clicked.connect(self._test_connection)
            layout.addWidget(self._test_btn)

        button_mask = (
            QDialogButtonBox.StandardButton.Ok
            if first_run
            else QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons = QDialogButtonBox(button_mask)
        buttons.accepted.connect(self._save)
        if not first_run:
            buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        LanguageManager.instance().languageChanged.connect(self._retranslate)
        self._retranslate()

    def _retranslate(self):
        self.setWindowTitle(
            tr("app.first_run_title") if self._first_run else tr("app.settings_title")
        )
        if self._welcome is not None:
            self._welcome.setText(tr("settings.welcome"))
        self._db_label.setText(tr("settings.db_label"))
        self._out_label.setText(tr("settings.output_label"))
        self._api_key_label.setText(tr("settings.api_key_label"))
        self._cache_label.setText(tr("settings.cache_label"))
        self._db_row.retranslate()
        self._out_row.retranslate()
        self._key_row.retranslate()
        self._cache_row.retranslate()
        if self._test_btn is not None:
            self._test_btn.setText(tr("settings.test_connection"))

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

        if not api_key:
            lines.append(tr("settings.test.api_key_missing"))
        else:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                result, detail = _check_google_api_key(api_key)
            finally:
                QApplication.restoreOverrideCursor()
            if result == "OK":
                lines.append(tr("settings.test.api_key_valid"))
            elif result == "INVALID":
                lines.append(
                    tr("settings.test.api_key_invalid", error=detail)
                )
            else:  # NETWORK_ERROR
                lines.append(
                    tr("settings.test.api_key_network_error", error=detail)
                )

        QMessageBox.information(
            self, tr("settings.test_result_title"), "\n".join(lines)
        )

    def _save(self):
        self._result = {
            "db_path": self._db_row.value(),
            "output_path": self._out_row.value(),
            "google_api_key": self._key_row.value(),
            "geo_cache": self._cache_row.value(),
        }
        self.accept()

    def get_settings(self) -> dict | None:
        return self._result
