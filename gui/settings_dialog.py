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
from monthly_schedule.travel import load_api_key


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
        self._gc_row = _PathRow(settings.get("google_config", ""), "Config files (*)")
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
