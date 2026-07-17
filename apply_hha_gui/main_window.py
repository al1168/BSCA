"""Apply HHA Answers GUI main window: answers-CSV picker, DB picker,
Preview (dry-run) and Apply buttons, scrolling log. English-only.

Apply is enabled only after a successful Preview on the exact same
pair of paths; editing either path disables it again (spec §6)."""
import os

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from apply_hha_gui.worker import ApplyHhaWorker


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Apply HHA Answers")
        self.setMinimumWidth(560)
        self._worker: ApplyHhaWorker | None = None
        # (csv, db) paths of the last successful preview, or None.
        self._previewed: tuple[str, str] | None = None

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ── Title ─────────────────────────────────────────────
        title = QLabel("Apply HHA Answers")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)

        # ── Answers CSV picker ────────────────────────────────
        root.addWidget(QLabel("Answers CSV:"))
        self._csv_edit, self._csv_browse = self._picker_row(
            root, "Select Answers CSV", "CSV Files (*.csv)",
        )

        # ── DB picker ─────────────────────────────────────────
        root.addWidget(QLabel("Database File:"))
        self._db_edit, self._db_browse = self._picker_row(
            root, "Select Database File",
            "Access Database (*.accdb *.mdb)",
        )

        # ── Buttons ───────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_font = QFont()
        btn_font.setPointSize(11)
        btn_font.setBold(True)
        self._preview_btn = QPushButton("Preview (no changes)")
        self._preview_btn.setFixedHeight(40)
        self._preview_btn.setFont(btn_font)
        self._preview_btn.clicked.connect(self._on_preview_clicked)
        btn_row.addWidget(self._preview_btn)
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setFixedHeight(40)
        self._apply_btn.setFont(btn_font)
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        btn_row.addWidget(self._apply_btn)
        root.addLayout(btn_row)

        # ── Log ───────────────────────────────────────────────
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setMinimumHeight(260)
        root.addWidget(self._log)

    def _picker_row(self, root, caption, name_filter):
        """One QLineEdit + Browse button row. Returns (edit, button)."""
        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setMinimumWidth(360)
        edit.textChanged.connect(self._on_paths_changed)
        row.addWidget(edit, 1)
        btn = QPushButton("Browse…")
        btn.setFixedWidth(90)

        def on_browse():
            start = edit.text() or os.path.expanduser("~")
            path, _ = QFileDialog.getOpenFileName(
                self, caption, start, name_filter,
            )
            if path:
                edit.setText(path)

        btn.clicked.connect(on_browse)
        row.addWidget(btn)
        root.addLayout(row)
        return edit, btn

    # ── State helpers ─────────────────────────────────────────

    def _current_paths(self):
        return (
            self._csv_edit.text().strip(),
            self._db_edit.text().strip(),
        )

    def _on_paths_changed(self, _text=""):
        """Apply stays enabled only while the paths match the last
        successful preview."""
        self._apply_btn.setEnabled(
            self._worker is None
            and self._previewed is not None
            and self._current_paths() == self._previewed
        )

    def _validated_paths(self):
        """Return (csv, db) if both files exist, else None (+dialog)."""
        csv_path, db_path = self._current_paths()
        if not csv_path or not os.path.isfile(csv_path):
            QMessageBox.warning(
                self, "CSV Not Found",
                "Pick a valid answers CSV file first.",
            )
            return None
        if not db_path or not os.path.isfile(db_path):
            QMessageBox.warning(
                self, "Database Not Found",
                "Pick a valid .accdb file first.",
            )
            return None
        return csv_path, db_path

    def _start(self, mode):
        paths = self._validated_paths()
        if paths is None:
            return
        self._log.clear()
        for w in (self._preview_btn, self._apply_btn, self._csv_edit,
                  self._db_edit, self._csv_browse, self._db_browse):
            w.setEnabled(False)
        self._worker = ApplyHhaWorker(paths[0], paths[1], mode,
                                      parent=self)
        self._worker.log_line.connect(self._log.appendPlainText)
        self._worker.finished_run.connect(self._on_finished)
        self._worker.start()

    # ── Slots ─────────────────────────────────────────────────

    def _on_preview_clicked(self):
        self._previewed = None
        self._start("preview")

    def _on_apply_clicked(self):
        self._start("apply")

    def _on_finished(self, success: bool, payload: dict):
        self._worker = None
        for w in (self._preview_btn, self._csv_edit, self._db_edit,
                  self._csv_browse, self._db_browse):
            w.setEnabled(True)

        mode = payload.get("mode", "?")
        if success and mode == "preview":
            self._previewed = self._current_paths()
            self._log.appendPlainText("")
            self._log.appendPlainText(
                "Preview finished — no changes were made. Review the "
                "log above, then click Apply to make these changes."
            )
        elif success and mode == "apply":
            self._previewed = None
            backup = payload.get("backup", "")
            self._log.appendPlainText("")
            self._log.appendPlainText(f"Applied. Backup: {backup}")
            QMessageBox.information(
                self, "Apply Complete",
                "Availability was updated successfully.\n\n"
                f"A backup of the database is at:\n{backup}",
            )
        else:
            self._previewed = None
            step = payload.get("step", "?")
            error = payload.get("error", "unknown error")
            backup = payload.get("backup")
            self._log.appendPlainText("")
            self._log.appendPlainText(f"Failed at {step}: {error}")
            body = f"Failed at step '{step}'.\n\nError: {error}"
            if step == "backup":
                body += (
                    "\n\nNothing was changed. If the database is open "
                    "in Access or Excel, close it and try again."
                )
            elif backup:
                body += (
                    "\n\nThe database may be partially modified. To "
                    "restore, copy this file over the original:\n"
                    f"{backup}"
                )
            QMessageBox.warning(self, "Apply HHA Answers Failed", body)
        self._on_paths_changed()

    def closeEvent(self, event):
        """Wait up to 3 s for an in-flight worker before closing
        (same rationale as setup_gui)."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        event.accept()
