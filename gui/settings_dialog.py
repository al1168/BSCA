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


def _default_config_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


class _GoogleConfigRow(QHBoxLayout):
    def __init__(self, default_path: str):
        super().__init__()
        self.edit = QLineEdit(default_path)
        self.edit.setMinimumWidth(260)
        self.browse_btn = QPushButton()
        self.browse_btn.setFixedWidth(80)
        self.browse_btn.clicked.connect(self._browse)
        self.create_btn = QPushButton()
        self.create_btn.setFixedWidth(105)
        self.create_btn.clicked.connect(self._create_and_open)
        self.addWidget(self.edit, 1)
        self.addWidget(self.browse_btn)
        self.addWidget(self.create_btn)

    def retranslate(self):
        self.browse_btn.setText(tr("settings.browse"))
        self.create_btn.setText(tr("settings.create_open"))
        self.create_btn.setToolTip(tr("settings.create_open_tooltip"))

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            None,
            tr("settings.file_dialog.google"),
            self.edit.text(),
            "Config files (*)",
        )
        if path:
            self.edit.setText(path)

    def _create_and_open(self):
        current = self.edit.text().strip()
        if current:
            target = current
        else:
            target = os.path.join(_default_config_dir(), "google_maps.config")

        if os.path.isfile(target):
            reply = QMessageBox.question(
                None,
                tr("settings.file_exists_title"),
                tr("settings.file_exists_body", path=target),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        else:
            try:
                with open(target, "w", encoding="utf-8") as f:
                    f.write(_GOOGLE_CONFIG_PLACEHOLDER)
            except OSError as exc:
                QMessageBox.warning(
                    None, tr("settings.create_fail_title"), str(exc)
                )
                return

        self.edit.setText(target)
        if sys.platform == "win32":
            os.startfile(target)
        else:
            subprocess.Popen(["xdg-open", target])

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
        self._gc_label.setText(tr("settings.google_label"))
        self._cache_label.setText(tr("settings.cache_label"))
        self._db_row.retranslate()
        self._out_row.retranslate()
        self._gc_row.retranslate()
        self._cache_row.retranslate()
        if self._test_btn is not None:
            self._test_btn.setText(tr("settings.test_connection"))

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

    def _save(self):
        self._result = {
            "db_path": self._db_row.value(),
            "output_path": self._out_row.value(),
            "google_config": self._gc_row.value(),
            "geo_cache": self._cache_row.value(),
        }
        self.accept()

    def get_settings(self) -> dict | None:
        return self._result
