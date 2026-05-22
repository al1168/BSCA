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

_GOOGLE_CONFIG_PLACEHOLDER = "PASTE_YOUR_GOOGLE_MAPS_API_KEY_HERE\n"

# Default location for a newly created config file: same folder as the
# running exe (PyInstaller) or the project root (script mode).
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
        browse = QPushButton("Browse…")
        browse.setFixedWidth(80)
        browse.clicked.connect(self._browse)
        self.addWidget(self.edit, 1)
        self.addWidget(browse)

    def _browse(self):
        if self._pick_dir:
            path = QFileDialog.getExistingDirectory(None, "Select Folder", self.edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(
                None, "Select File", self.edit.text(), self._filter
            )
        if path:
            self.edit.setText(path)

    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, v: str):
        self.edit.setText(v)


class _GoogleConfigRow(QHBoxLayout):
    """Path row for the Google Maps config file with a Create & Open button."""

    def __init__(self, default_path: str):
        super().__init__()
        self.edit = QLineEdit(default_path)
        self.edit.setMinimumWidth(260)
        browse = QPushButton("Browse…")
        browse.setFixedWidth(80)
        browse.clicked.connect(self._browse)
        create_btn = QPushButton("Create & Open")
        create_btn.setFixedWidth(105)
        create_btn.setToolTip("Create a new config file and open it in Notepad to paste your API key")
        create_btn.clicked.connect(self._create_and_open)
        self.addWidget(self.edit, 1)
        self.addWidget(browse)
        self.addWidget(create_btn)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Select Google Maps Config File", self.edit.text(), "Config files (*)"
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
                "File Already Exists",
                f"A config file already exists at:\n{target}\n\nOpen it for editing?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        else:
            try:
                with open(target, "w", encoding="utf-8") as f:
                    f.write(_GOOGLE_CONFIG_PLACEHOLDER)
            except OSError as exc:
                QMessageBox.warning(None, "Could Not Create File", str(exc))
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
        self.setWindowTitle("Welcome — Initial Setup" if first_run else "Settings")
        self.setMinimumWidth(560)
        self._result: dict | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        if first_run:
            welcome = QLabel(
                "Before you get started, please locate the three files below.\n"
                "You can change these at any time using the ⚙ Settings button."
            )
            welcome.setWordWrap(True)
            layout.addWidget(welcome)

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
        self._cache_row = _PathRow(settings.get("geo_cache", ""), "JSON files (*.json)")

        form.addRow(QLabel("Database File"), self._db_row)
        form.addRow(QLabel("Output Folder"), self._out_row)
        form.addRow(QLabel("Google Maps Config File"), self._gc_row)
        form.addRow(QLabel("Travel Cache File"), self._cache_row)
        layout.addLayout(form)

        if not first_run:
            test_btn = QPushButton("Test Connection")
            test_btn.clicked.connect(self._test_connection)
            layout.addWidget(test_btn)

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

    def _test_connection(self):
        db_path = self._db_row.value()
        gc_path = self._gc_row.value()
        lines = []

        if not os.path.isfile(db_path):
            lines.append(f"Database: File not found — {db_path}")
        else:
            try:
                get_member(0, db_path)
                lines.append("Database: Connected successfully.")
            except RuntimeError as exc:
                lines.append(f"Database: {friendly_db_error(str(exc))}")
            except Exception as exc:
                lines.append(f"Database: Connection failed — {exc}")

        if not os.path.isfile(gc_path):
            lines.append(f"Google Config: File not found — {gc_path}")
        else:
            try:
                load_api_key(gc_path)
                lines.append("Google Config: API key loaded successfully.")
            except RuntimeError as exc:
                lines.append(f"Google Config: {exc}")

        QMessageBox.information(self, "Connection Test", "\n".join(lines))

    def _save(self):
        self._result = {
            "db_path": self._db_row.value(),
            "output_path": self._out_row.value(),
            "google_config": self._gc_row.value(),
            "geo_cache": self._cache_row.value(),
        }
        self.accept()

    def get_settings(self) -> dict | None:
        """Returns the saved settings dict, or None if cancelled."""
        return self._result
