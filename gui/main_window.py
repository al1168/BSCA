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
from gui.i18n import LanguageManager, tr
from gui.settings_dialog import SettingsDialog
from gui.worker import ScheduleWorker
from new_monthly_schedule import parse_center_ids, resolve_output_dir

PLAN_CODES = ["HOF"]


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumWidth(560)
        self._settings = app_settings.load()
        self._worker = None
        self._last_out_dir = None

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ── Top bar ────────────────────────────────────────────────
        top = QHBoxLayout()
        self._title_label = QLabel()
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        top.addWidget(self._title_label, 1)

        self._lang_combo = QComboBox()
        self._lang_combo.addItem("English", "en")
        self._lang_combo.addItem("中文", "zh")
        self._lang_combo.setFixedWidth(90)
        # Reflect the current language without firing a switch.
        current_lang = self._settings.get("language", "en")
        idx = self._lang_combo.findData(current_lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        top.addWidget(self._lang_combo)

        self._settings_btn = QPushButton("⚙")
        self._settings_btn.setFixedSize(32, 32)
        self._settings_btn.clicked.connect(self._open_settings)
        top.addWidget(self._settings_btn)
        root.addLayout(top)

        # ── WHO ────────────────────────────────────────────────────
        self._who_box = QGroupBox()
        who_layout = QVBoxLayout(self._who_box)

        radio_row = QHBoxLayout()
        self._radio_single = QRadioButton()
        self._radio_multiple = QRadioButton()
        self._radio_plan = QRadioButton()
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

        # Panel 0 — single
        p0 = QWidget()
        p0_layout = QHBoxLayout(p0)
        p0_layout.setContentsMargins(0, 0, 0, 0)
        self._single_label = QLabel()
        p0_layout.addWidget(self._single_label)
        self._single_id = QSpinBox()
        self._single_id.setRange(1, 999999)
        self._single_id.setFixedWidth(100)
        p0_layout.addWidget(self._single_id)
        p0_layout.addStretch()

        # Panel 1 — multiple
        p1 = QWidget()
        p1_layout = QHBoxLayout(p1)
        p1_layout.setContentsMargins(0, 0, 0, 0)
        self._multi_label = QLabel()
        p1_layout.addWidget(self._multi_label)
        self._multi_ids = QLineEdit()
        p1_layout.addWidget(self._multi_ids, 1)

        # Panel 2 — plan
        p2 = QWidget()
        p2_layout = QHBoxLayout(p2)
        p2_layout.setContentsMargins(0, 0, 0, 0)
        self._plan_label_widget = QLabel()
        p2_layout.addWidget(self._plan_label_widget)
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
        root.addWidget(self._who_box)

        # ── WHEN ───────────────────────────────────────────────────
        self._when_box = QGroupBox()
        when_layout = QHBoxLayout(self._when_box)
        self._month_label_widget = QLabel()
        when_layout.addWidget(self._month_label_widget)
        self._month_combo = QComboBox()
        # Items are added in _retranslate() so they reflect the current language.
        self._month_combo.addItems([""] * 12)
        self._month_combo.setCurrentIndex(datetime.date.today().month - 1)
        when_layout.addWidget(self._month_combo)
        when_layout.addSpacing(16)
        self._year_label_widget = QLabel()
        when_layout.addWidget(self._year_label_widget)
        self._year_spin = QSpinBox()
        self._year_spin.setRange(2020, 2040)
        self._year_spin.setValue(datetime.date.today().year)
        self._year_spin.setFixedWidth(80)
        when_layout.addWidget(self._year_spin)
        when_layout.addStretch()
        root.addWidget(self._when_box)

        # ── SAVE TO ────────────────────────────────────────────────
        self._save_box = QGroupBox()
        save_layout = QHBoxLayout(self._save_box)
        self._out_label = QLabel(self._settings.get("output_path", "."))
        self._out_label.setWordWrap(True)
        save_layout.addWidget(self._out_label, 1)
        self._change_btn = QPushButton()
        self._change_btn.setFixedWidth(80)
        self._change_btn.clicked.connect(self._open_settings)
        save_layout.addWidget(self._change_btn)
        root.addWidget(self._save_box)

        # ── Options ────────────────────────────────────────────────
        self._preview_check = QCheckBox()
        root.addWidget(self._preview_check)

        # ── Generate ───────────────────────────────────────────────
        self._generate_btn = QPushButton()
        self._generate_btn.setFixedHeight(40)
        gen_font = QFont()
        gen_font.setPointSize(11)
        gen_font.setBold(True)
        self._generate_btn.setFont(gen_font)
        self._generate_btn.clicked.connect(self._run)
        root.addWidget(self._generate_btn)

        # ── Progress + Log ─────────────────────────────────────────
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

        self._open_folder_btn = QPushButton()
        self._open_folder_btn.setVisible(False)
        self._open_folder_btn.clicked.connect(self._open_output_folder)
        root.addWidget(self._open_folder_btn)

        # Wire up live retranslation and apply once.
        LanguageManager.instance().languageChanged.connect(self._retranslate)
        self._retranslate()

    # ── Retranslate ───────────────────────────────────────────────

    def _retranslate(self):
        self.setWindowTitle(tr("app.main_title"))
        self._title_label.setText(tr("top.title"))
        self._settings_btn.setToolTip(tr("top.settings_tooltip"))

        self._who_box.setTitle(tr("who.title"))
        self._radio_single.setText(tr("who.single"))
        self._radio_multiple.setText(tr("who.multiple"))
        self._radio_plan.setText(tr("who.plan"))
        self._single_label.setText(tr("who.member_id_label"))
        self._multi_label.setText(tr("who.member_ids_label"))
        self._multi_ids.setPlaceholderText(tr("who.placeholder"))
        self._plan_label_widget.setText(tr("who.plan_label"))

        self._when_box.setTitle(tr("when.title"))
        self._month_label_widget.setText(tr("when.month_label"))
        self._year_label_widget.setText(tr("when.year_label"))
        for i in range(12):
            self._month_combo.setItemText(i, tr(f"when.month.{i + 1}"))

        self._save_box.setTitle(tr("save.title"))
        self._change_btn.setText(tr("save.change"))

        self._preview_check.setText(tr("opts.preview"))
        self._generate_btn.setText(tr("opts.generate"))
        self._open_folder_btn.setText(tr("opts.open_folder"))

    # ── Slots ─────────────────────────────────────────────────────

    def _on_who_changed(self, btn_id: int, checked: bool):
        if checked:
            self._who_stack.setCurrentIndex(btn_id)

    def _on_language_changed(self, index: int):
        lang = self._lang_combo.itemData(index)
        if lang:
            LanguageManager.instance().set_language(lang)

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
                QMessageBox.warning(
                    self,
                    tr("msg.missing_info.title"),
                    tr("msg.missing_info.member_id"),
                )
                return False

        elif mode == 1:
            raw = self._multi_ids.text().strip()
            if not raw:
                QMessageBox.warning(
                    self,
                    tr("msg.missing_info.title"),
                    tr("msg.missing_info.member_ids"),
                )
                return False
            try:
                ids = parse_center_ids(raw)
                if not ids:
                    raise ValueError
            except (ValueError, Exception):
                QMessageBox.warning(
                    self,
                    tr("msg.invalid_ids.title"),
                    tr("msg.invalid_ids.body", raw=repr(raw)),
                )
                return False

        elif mode == 2:
            pass

        db_path = self._settings.get("db_path", "")
        if not os.path.isfile(db_path):
            QMessageBox.warning(
                self,
                tr("msg.db_not_found.title"),
                tr("msg.db_not_found.body", path=db_path),
            )
            return False

        gc_path = self._settings.get("google_config", "")
        if not os.path.isfile(gc_path):
            QMessageBox.warning(
                self,
                tr("msg.gc_not_found.title"),
                tr("msg.gc_not_found.body", path=gc_path),
            )
            return False

        if not self._preview_check.isChecked():
            out = self._settings.get("output_path", "").strip()
            if not out:
                QMessageBox.warning(
                    self,
                    tr("msg.missing_info.title"),
                    tr("msg.missing_info.output_folder"),
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

    def _on_log_line(self, key: str, args: dict):
        self._log.appendPlainText(tr(key, **args))

    def _on_finished(self, success: bool, payload: dict):
        if "error_text" in payload:
            summary = payload["error_text"]
        else:
            summary = self._build_summary(payload)
        self._log.appendPlainText("")
        self._log.appendPlainText(summary)
        self._generate_btn.setEnabled(True)
        preview = self._preview_check.isChecked()
        if success and not preview:
            self._open_folder_btn.setVisible(True)
        if not success:
            QMessageBox.warning(
                self, tr("msg.completed_errors.title"), summary
            )

    def _build_summary(self, data: dict) -> str:
        scope = data["scope"]
        period = f"{scope['year']:04d}-{scope['month']:02d}"
        if scope["plan_code"] is not None:
            scope_text = tr("scope.plan", code=scope["plan_code"], period=period)
        else:
            scope_text = tr("scope.period", period=period)

        verb = tr(data["verb_key"])
        head = tr(
            "summary.headline",
            verb=verb,
            success=data["success"],
            total=data["total"],
            scope=scope_text,
        )
        if data["out_dir"] is not None:
            head += tr("summary.into", dir=data["out_dir"])
        if data["failures"]:
            head += tr("summary.failed_tail", n=len(data["failures"]))

        if not data["failures"]:
            return head

        lines = [head, tr("summary.failures_header")]
        for f in data["failures"]:
            stage = tr(f"summary.stage.{f['stage']}")
            reason = (
                tr("summary.reason.not_found")
                if f["reason"] == "not found in database"
                else f["reason"]
            )
            row_key = (
                "summary.failure_row_named" if f["name"] else "summary.failure_row_unnamed"
            )
            lines.append(
                tr(
                    row_key,
                    center_id=f["center_id"],
                    name=f["name"],
                    stage=stage,
                    reason=reason,
                )
            )
        return "\n".join(lines)
