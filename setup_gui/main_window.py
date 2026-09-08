"""Setup GUI main window. A single QWidget: DB file picker, Run
Setup button, progress bar, scrolling log. English-only."""
import os

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from setup_gui.setup_worker import SETUP_STEPS, SetupWorker


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BSCA Setup")
        self.setMinimumWidth(560)
        self._worker: SetupWorker | None = None

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ── Title ─────────────────────────────────────────────
        title = QLabel("BSCA Setup")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)

        # ── DB file picker ────────────────────────────────────
        root.addWidget(QLabel("Database File:"))
        picker_row = QHBoxLayout()
        self._db_edit = QLineEdit()
        self._db_edit.setMinimumWidth(360)
        picker_row.addWidget(self._db_edit, 1)
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setFixedWidth(90)
        self._browse_btn.clicked.connect(self._on_browse_clicked)
        picker_row.addWidget(self._browse_btn)
        root.addLayout(picker_row)

        # ── Group label (optional) ────────────────────────────
        root.addWidget(QLabel("Group (optional):"))
        self._group_edit = QLineEdit()
        self._group_edit.setPlaceholderText("e.g. A")
        self._group_edit.setMaxLength(255)
        root.addWidget(self._group_edit)
        group_hint = QLabel(
            "Written to the new Contacts [Group] column for every "
            "member that does not already have one."
        )
        group_hint.setWordWrap(True)
        group_hint.setStyleSheet("color: gray;")
        root.addWidget(group_hint)

        # ── Run button ────────────────────────────────────────
        self._run_btn = QPushButton("Run Setup")
        self._run_btn.setFixedHeight(40)
        run_font = QFont()
        run_font.setPointSize(11)
        run_font.setBold(True)
        self._run_btn.setFont(run_font)
        self._run_btn.clicked.connect(self._on_run_clicked)
        root.addWidget(self._run_btn)

        # ── Optional: terminate long-ID enrollments ───────────
        self._terminate_check = QCheckBox(
            "Also terminate long-ID enrollments "
            "(sets end_date to 2000-01-01 for any member whose "
            "Center ID is more than 5 digits)"
        )
        self._terminate_check.setChecked(True)
        root.addWidget(self._terminate_check)

        # ── Progress ──────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, len(SETUP_STEPS))
        self._progress.setValue(0)
        self._progress.setFormat("%v of %m")
        root.addWidget(self._progress)

        # ── Log ───────────────────────────────────────────────
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        log_font = QFont("Consolas", 9)
        self._log.setFont(log_font)
        self._log.setMinimumHeight(220)
        root.addWidget(self._log)

    # ── Slots ─────────────────────────────────────────────────

    def _on_browse_clicked(self):
        start = self._db_edit.text() or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Database File",
            start,
            "Access Database (*.accdb *.mdb)",
        )
        if path:
            self._db_edit.setText(path)

    def _on_run_clicked(self):
        db_path = self._db_edit.text().strip()
        if not db_path or not os.path.isfile(db_path):
            QMessageBox.warning(
                self,
                "Database Not Found",
                "Pick a valid .accdb file before running setup.",
            )
            return

        self._log.clear()
        self._progress.setValue(0)
        self._run_btn.setEnabled(False)
        self._browse_btn.setEnabled(False)
        self._db_edit.setEnabled(False)
        self._group_edit.setEnabled(False)
        self._terminate_check.setEnabled(False)

        also_terminate = self._terminate_check.isChecked()
        group_text = self._group_edit.text().strip()
        self._worker = SetupWorker(
            db_path, also_terminate=also_terminate, parent=self,
            group_text=group_text,
        )
        self._worker.log_line.connect(self._on_log_line)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_log_line(self, line: str):
        self._log.appendPlainText(line)

    def _on_progress(self, done: int, total: int):
        self._progress.setRange(0, total)
        self._progress.setValue(done)

    def _on_finished(self, success: bool, payload: dict):
        self._run_btn.setEnabled(True)
        self._browse_btn.setEnabled(True)
        self._db_edit.setEnabled(True)
        self._group_edit.setEnabled(True)
        self._terminate_check.setEnabled(True)
        self._worker = None

        if success:
            backup = payload.get("backup", "")
            total_steps = payload.get("total_steps", len(SETUP_STEPS))
            self._log.appendPlainText("")
            self._log.appendPlainText(
                f"Setup completed successfully. Backup: {backup}"
            )
            QMessageBox.information(
                self,
                "Setup Complete",
                f"All {total_steps} setup steps finished "
                f"successfully.\n\n"
                f"A backup of your original database is at:\n{backup}",
            )
        else:
            step = payload.get("step", "?")
            error = payload.get("error", "unknown error")
            backup = payload.get("backup")
            self._log.appendPlainText("")
            self._log.appendPlainText(
                f"Setup failed at step '{step}': {error}"
            )
            body = (
                f"Setup failed at step '{step}'.\n\n"
                f"Error: {error}"
            )
            if backup:
                body += (
                    f"\n\nThe original database may be partially "
                    f"modified. To restore, copy this file over the "
                    f"original:\n{backup}"
                )
            QMessageBox.warning(self, "Setup Failed", body)

    def closeEvent(self, event):
        """Wait up to 3 s for an in-flight worker before accepting close.

        If the worker is still running after the timeout (e.g. a script
        hangs on a DB connection), Qt will emit `QThread destroyed while
        still running` as the parented thread is torn down. Acceptable
        for a one-shot setup tool with no cancel mechanism."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        event.accept()
