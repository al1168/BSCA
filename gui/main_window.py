import datetime
import os
import subprocess
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui import app_settings
from gui.settings_dialog import SettingsDialog
from gui.worker import ScheduleWorker
from new_monthly_schedule import parse_center_ids, resolve_output_dir

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

PLAN_CODES = ["HOF"]


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Monthly Schedule Generator")
        self.setMinimumWidth(560)
        self._settings = app_settings.load()
        self._worker = None

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ── Top bar ───────────────────────────────────────────────────────
        top = QHBoxLayout()
        title = QLabel("Monthly Schedule Generator")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title.setFont(title_font)
        top.addWidget(title, 1)
        settings_btn = QPushButton("⚙")
        settings_btn.setFixedSize(32, 32)
        settings_btn.setToolTip("Settings")
        settings_btn.clicked.connect(self._open_settings)
        top.addWidget(settings_btn)
        root.addLayout(top)

        # ── WHO ───────────────────────────────────────────────────────────
        who_box = QGroupBox("Who")
        who_layout = QVBoxLayout(who_box)

        radio_row = QHBoxLayout()
        self._radio_single = QRadioButton("Single Member")
        self._radio_multiple = QRadioButton("Multiple Members")
        self._radio_plan = QRadioButton("Entire Plan")
        self._radio_single.setChecked(True)
        radio_row.addWidget(self._radio_single)
        radio_row.addWidget(self._radio_multiple)
        radio_row.addWidget(self._radio_plan)
        radio_row.addStretch()

        self._who_group = QButtonGroup(self)
        self._who_group.addButton(self._radio_single, 0)
        self._who_group.addButton(self._radio_multiple, 1)
        self._who_group.addButton(self._radio_plan, 2)
        self._who_group.idToggled.connect(self._on_who_changed)

        self._who_stack = QStackedWidget()

        # Panel 0 — single member
        p0 = QWidget()
        p0_layout = QHBoxLayout(p0)
        p0_layout.setContentsMargins(0, 0, 0, 0)
        p0_layout.addWidget(QLabel("Member ID:"))
        self._single_id = QSpinBox()
        self._single_id.setRange(1, 999999)
        self._single_id.setFixedWidth(100)
        p0_layout.addWidget(self._single_id)
        p0_layout.addStretch()

        # Panel 1 — multiple members
        p1 = QWidget()
        p1_layout = QHBoxLayout(p1)
        p1_layout.setContentsMargins(0, 0, 0, 0)
        p1_layout.addWidget(QLabel("Member IDs:"))
        self._multi_ids = QLineEdit()
        self._multi_ids.setPlaceholderText("e.g. 24010, 24011, 24015")
        p1_layout.addWidget(self._multi_ids, 1)

        # Panel 2 — plan
        p2 = QWidget()
        p2_layout = QHBoxLayout(p2)
        p2_layout.setContentsMargins(0, 0, 0, 0)
        p2_layout.addWidget(QLabel("Plan:"))
        self._plan_combo = QComboBox()
        self._plan_combo.addItems(PLAN_CODES)
        self._plan_combo.setFixedWidth(120)
        p2_layout.addWidget(self._plan_combo)
        p2_layout.addStretch()

        self._who_stack.addWidget(p0)
        self._who_stack.addWidget(p1)
        self._who_stack.addWidget(p2)

        who_layout.addLayout(radio_row)
        who_layout.addWidget(self._who_stack)
        root.addWidget(who_box)

        # ── WHEN ──────────────────────────────────────────────────────────
        when_box = QGroupBox("When")
        when_layout = QHBoxLayout(when_box)
        when_layout.addWidget(QLabel("Month:"))
        self._month_combo = QComboBox()
        self._month_combo.addItems(MONTHS)
        self._month_combo.setCurrentIndex(datetime.date.today().month - 1)
        when_layout.addWidget(self._month_combo)
        when_layout.addSpacing(16)
        when_layout.addWidget(QLabel("Year:"))
        self._year_spin = QSpinBox()
        self._year_spin.setRange(2020, 2040)
        self._year_spin.setValue(datetime.date.today().year)
        self._year_spin.setFixedWidth(80)
        when_layout.addWidget(self._year_spin)
        when_layout.addStretch()
        root.addWidget(when_box)

        # ── SAVE TO ───────────────────────────────────────────────────────
        save_box = QGroupBox("Save To")
        save_layout = QHBoxLayout(save_box)
        self._out_label = QLabel(self._settings.get("output_path", "."))
        self._out_label.setWordWrap(True)
        save_layout.addWidget(self._out_label, 1)
        change_btn = QPushButton("Change…")
        change_btn.setFixedWidth(80)
        change_btn.clicked.connect(self._open_settings)
        save_layout.addWidget(change_btn)
        root.addWidget(save_box)

        # ── Options ───────────────────────────────────────────────────────
        self._preview_check = QCheckBox("Preview only (don't save files)")
        root.addWidget(self._preview_check)

        # ── Generate button ───────────────────────────────────────────────
        self._generate_btn = QPushButton("Generate Schedule")
        self._generate_btn.setFixedHeight(40)
        gen_font = QFont()
        gen_font.setPointSize(11)
        gen_font.setBold(True)
        self._generate_btn.setFont(gen_font)
        self._generate_btn.clicked.connect(self._run)
        root.addWidget(self._generate_btn)

        # ── Progress + Log ────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setVisible(False)
        log_font = QFont("Consolas", 9)
        self._log.setFont(log_font)
        self._log.setMinimumHeight(120)
        root.addWidget(self._log)

        self._open_folder_btn = QPushButton("Open Output Folder")
        self._open_folder_btn.setVisible(False)
        self._open_folder_btn.clicked.connect(self._open_output_folder)
        root.addWidget(self._open_folder_btn)

        self._last_out_dir = None

    # ── Slots ─────────────────────────────────────────────────────────────

    def _on_who_changed(self, btn_id: int, checked: bool):
        if checked:
            self._who_stack.setCurrentIndex(btn_id)

    def _open_settings(self):
        dlg = SettingsDialog(self._settings, self)
        if dlg.exec():
            result = dlg.get_settings()
            if result:
                self._settings.update(result)
                app_settings.save(self._settings)
                self._out_label.setText(self._settings.get("output_path", "."))

    def _open_output_folder(self):
        if self._last_out_dir and os.path.isdir(self._last_out_dir):
            if sys.platform == "win32":
                os.startfile(self._last_out_dir)
            else:
                subprocess.Popen(["xdg-open", self._last_out_dir])

    def _validate(self) -> bool:
        mode = self._who_group.checkedId()

        if mode == 0:
            if self._single_id.value() < 1:
                QMessageBox.warning(self, "Missing Info", "Please enter a Member ID.")
                return False

        elif mode == 1:
            raw = self._multi_ids.text().strip()
            if not raw:
                QMessageBox.warning(self, "Missing Info", "Please enter at least one Member ID.")
                return False
            try:
                ids = parse_center_ids(raw)
                if not ids:
                    raise ValueError
            except (ValueError, Exception):
                QMessageBox.warning(
                    self, "Invalid IDs",
                    "Member IDs must be numbers separated by commas.\n"
                    f"Could not read: {raw!r}"
                )
                return False

        elif mode == 2:
            pass  # combo always has a value

        db_path = self._settings.get("db_path", "")
        if not os.path.isfile(db_path):
            QMessageBox.warning(
                self, "Database Not Found",
                f"The database file could not be found:\n{db_path}\n\n"
                "Open Settings to fix the path."
            )
            return False

        gc_path = self._settings.get("google_config", "")
        if not os.path.isfile(gc_path):
            QMessageBox.warning(
                self, "Google Config Not Found",
                f"The Google Maps config file could not be found:\n{gc_path}\n\n"
                "Open Settings to fix the path."
            )
            return False

        if not self._preview_check.isChecked():
            out = self._settings.get("output_path", "").strip()
            if not out:
                QMessageBox.warning(
                    self, "Missing Info",
                    "Please set an output folder in Settings (⚙)."
                )
                return False

        return True

    def _run(self):
        if not self._validate():
            return

        mode_id = self._who_group.checkedId()
        mode = ["single", "multiple", "plan"][mode_id]
        year = self._year_spin.value()
        month = self._month_combo.currentIndex() + 1
        preview = self._preview_check.isChecked()

        center_id = self._single_id.value() if mode == "single" else None
        center_ids = (
            parse_center_ids(self._multi_ids.text()) if mode == "multiple" else None
        )
        plan_code = self._plan_combo.currentText() if mode == "plan" else None

        out_base = self._settings.get("output_path", "").strip() or "."
        out_dir = resolve_output_dir(out_base, plan_code, year, month)

        self._log.clear()
        self._log.setVisible(True)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._open_folder_btn.setVisible(False)
        self._generate_btn.setEnabled(False)
        self._last_out_dir = out_dir

        self._worker = ScheduleWorker(
            mode=mode,
            center_id=center_id,
            center_ids=center_ids,
            plan_code=plan_code,
            year=year,
            month=month,
            out_dir=out_dir,
            preview=preview,
            db_path=self._settings["db_path"],
            google_config=self._settings["google_config"],
            geo_cache=self._settings["geo_cache"],
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.log_line.connect(self._on_log_line)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, done: int, total: int):
        self._progress.setRange(0, total)
        self._progress.setValue(done)

    def _on_log_line(self, line: str):
        self._log.appendPlainText(line)

    def _on_finished(self, success: bool, summary: str):
        self._log.appendPlainText("")
        self._log.appendPlainText(summary)
        self._generate_btn.setEnabled(True)
        preview = self._preview_check.isChecked()
        if success and not preview:
            self._open_folder_btn.setVisible(True)
        if not success:
            QMessageBox.warning(self, "Completed with errors", summary)
