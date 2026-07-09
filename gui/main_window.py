import calendar
import datetime
import os
import subprocess
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIntValidator
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
from gui.printing import printable_schedules, default_printer_name
from gui.print_worker import PrintWorker
from gui.settings_dialog import SettingsDialog
from gui.worker import ScheduleWorker
from new_monthly_schedule import REASON_NOT_FOUND, parse_center_ids, resolve_output_dir
from monthly_schedule.per_day import REASON_NOT_ENROLLED, REASON_NO_AUTH, REASON_ABSENT_MONTH

PLAN_CODES = ["HF", "HOF", "VCM", "BCBS", "ES", "AE", "HC", "BCSB"]


def _translate_reason(reason: str) -> str:
    if reason == REASON_NOT_FOUND:
        return tr("summary.reason.not_found")
    if reason == REASON_NOT_ENROLLED:
        return tr("summary.reason.not_enrolled")
    if reason == REASON_NO_AUTH:
        return tr("summary.reason.no_auth")
    if reason == REASON_ABSENT_MONTH:
        return tr("summary.reason.absent_month")
    return reason


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumWidth(560)
        self._settings = app_settings.load()
        self._worker = None
        self._print_worker = None
        self._last_out_dir = None
        self._last_generated = []   # .xlsx paths from the last run

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
        self._radio_all = QRadioButton()
        self._radio_single.setChecked(True)
        radio_row.addWidget(self._radio_single)
        radio_row.addWidget(self._radio_multiple)
        radio_row.addWidget(self._radio_plan)
        radio_row.addWidget(self._radio_all)
        radio_row.addStretch()

        self._who_group = QButtonGroup(self)
        self._who_group.addButton(self._radio_single, 0)
        self._who_group.addButton(self._radio_multiple, 1)
        self._who_group.addButton(self._radio_plan, 2)
        self._who_group.addButton(self._radio_all, 3)
        self._who_group.idToggled.connect(self._on_who_changed)

        self._who_stack = QStackedWidget()

        # Panel 0 — single
        p0 = QWidget()
        p0_layout = QHBoxLayout(p0)
        p0_layout.setContentsMargins(0, 0, 0, 0)
        self._single_label = QLabel()
        p0_layout.addWidget(self._single_label)
        self._single_id = QLineEdit()
        self._single_id.setMaxLength(10)
        self._single_id.setValidator(QIntValidator(1, 2147483647))
        self._single_id.setFixedWidth(120)
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

        # Panel 3 — all members (informational only, no input)
        p3 = QWidget()
        p3_layout = QHBoxLayout(p3)
        p3_layout.setContentsMargins(0, 0, 0, 0)
        self._all_hint_label = QLabel()
        self._all_hint_label.setWordWrap(True)
        p3_layout.addWidget(self._all_hint_label, 1)

        self._who_stack.addWidget(p0)
        self._who_stack.addWidget(p1)
        self._who_stack.addWidget(p2)
        self._who_stack.addWidget(p3)

        who_layout.addLayout(radio_row)
        who_layout.addWidget(self._who_stack)
        root.addWidget(self._who_box)

        # ── WHEN ───────────────────────────────────────────────────
        self._when_box = QGroupBox()
        when_outer = QVBoxLayout(self._when_box)
        when_layout = QHBoxLayout()
        when_outer.addLayout(when_layout)
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

        # Custom day-range row (hidden until the checkbox is ticked).
        range_row = QHBoxLayout()
        self._range_check = QCheckBox()
        self._range_check.toggled.connect(self._on_range_toggled)
        range_row.addWidget(self._range_check)
        self._range_from_label = QLabel()
        range_row.addWidget(self._range_from_label)
        self._range_from_spin = QSpinBox()
        self._range_from_spin.setRange(1, 31)
        self._range_from_spin.setValue(1)
        self._range_from_spin.setFixedWidth(56)
        self._range_from_spin.setEnabled(False)
        range_row.addWidget(self._range_from_spin)
        self._range_to_label = QLabel()
        range_row.addWidget(self._range_to_label)
        self._range_to_spin = QSpinBox()
        self._range_to_spin.setRange(1, 31)
        self._range_to_spin.setValue(31)
        self._range_to_spin.setFixedWidth(56)
        self._range_to_spin.setEnabled(False)
        range_row.addWidget(self._range_to_spin)
        range_row.addStretch()
        when_outer.addLayout(range_row)

        # Keep the spin-box maxima in sync with the selected month/year
        # so a user can't pick April 31 or Feb 29 in a non-leap year.
        self._month_combo.currentIndexChanged.connect(self._update_range_max)
        self._year_spin.valueChanged.connect(self._update_range_max)
        self._update_range_max()
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
        self._debug_check = QCheckBox()
        root.addWidget(self._debug_check)
        # All-Members only: split output into per-MLTC folders. Default
        # off -> everyone in one <Month>_<Year>_Timesheets folder.
        self._mltc_folders_check = QCheckBox()
        root.addWidget(self._mltc_folders_check)

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

        # Appears after a successful (non-preview) run; prints every
        # generated schedule to the default printer (never debug CSVs).
        self._print_btn = QPushButton()
        self._print_btn.setVisible(False)
        self._print_btn.clicked.connect(self._print_schedules)
        root.addWidget(self._print_btn)

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
        self._radio_all.setText(tr("who.all"))
        self._single_label.setText(tr("who.member_id_label"))
        self._multi_label.setText(tr("who.member_ids_label"))
        self._multi_ids.setPlaceholderText(tr("who.placeholder"))
        self._plan_label_widget.setText(tr("who.plan_label"))
        self._all_hint_label.setText(tr("who.all_hint"))

        self._when_box.setTitle(tr("when.title"))
        self._month_label_widget.setText(tr("when.month_label"))
        self._year_label_widget.setText(tr("when.year_label"))
        for i in range(12):
            self._month_combo.setItemText(i, tr(f"when.month.{i + 1}"))
        self._range_check.setText(tr("when.range_check"))
        self._range_from_label.setText(tr("when.range_from"))
        self._range_to_label.setText(tr("when.range_to"))

        self._save_box.setTitle(tr("save.title"))
        self._change_btn.setText(tr("save.change"))

        self._preview_check.setText(tr("opts.preview"))
        self._debug_check.setText(tr("opts.debug"))
        self._mltc_folders_check.setText(tr("opts.mltc_folders"))
        self._generate_btn.setText(tr("opts.generate"))
        self._open_folder_btn.setText(tr("opts.open_folder"))
        self._print_btn.setText(tr("opts.print"))

    # ── Slots ─────────────────────────────────────────────────────

    def _on_who_changed(self, btn_id: int, checked: bool):
        if checked:
            self._who_stack.setCurrentIndex(btn_id)

    def _on_range_toggled(self, checked: bool):
        self._range_from_spin.setEnabled(checked)
        self._range_to_spin.setEnabled(checked)

    def _update_range_max(self, *_):
        """Cap the From/To spin boxes at the actual last day of the
        selected month so April 31 / Feb 29 in non-leap years can't be
        entered. Triggered when month or year changes."""
        year = self._year_spin.value()
        month = self._month_combo.currentIndex() + 1
        last_day = calendar.monthrange(year, month)[1]
        self._range_from_spin.setMaximum(last_day)
        self._range_to_spin.setMaximum(last_day)
        if self._range_to_spin.value() > last_day:
            self._range_to_spin.setValue(last_day)
        if self._range_from_spin.value() > last_day:
            self._range_from_spin.setValue(last_day)

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

    def _print_schedules(self):
        files = printable_schedules(self._last_generated)
        if not files:
            QMessageBox.information(
                self, tr("print.title"), tr("print.none")
            )
            return
        printer = default_printer_name() or tr("print.default_printer")
        confirm = QMessageBox.question(
            self,
            tr("print.confirm.title"),
            tr("print.confirm.body", count=len(files), printer=printer),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        # Disable the buttons and stream progress while printing.
        self._print_btn.setEnabled(False)
        self._generate_btn.setEnabled(False)
        self._progress.setRange(0, len(files))
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._log.setVisible(True)
        self._log.appendPlainText("")
        self._log.appendPlainText(tr("print.started", count=len(files)))
        self._print_worker = PrintWorker(files)
        self._print_worker.progress.connect(self._on_print_progress)
        self._print_worker.finished.connect(self._on_print_finished)
        self._print_worker.start()

    def _on_print_progress(self, done: int, total: int):
        self._progress.setRange(0, total)
        self._progress.setValue(done)

    def _on_print_finished(self, success: bool, payload: dict):
        self._print_btn.setEnabled(True)
        self._generate_btn.setEnabled(True)
        if success:
            self._log.appendPlainText(
                tr("print.done", count=payload.get("printed", 0))
            )
        else:
            msg = tr("print.failed", error=payload.get("error", ""))
            self._log.appendPlainText(msg)
            QMessageBox.warning(self, tr("print.title"), msg)

    def _validate(self) -> bool:
        mode = self._who_group.checkedId()

        if mode == 0:
            raw = self._single_id.text().strip()
            if not raw or int(raw) < 1:
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
            pass  # Plan — combo always has a value

        elif mode == 3:
            pass  # All Members — no input to validate

        db_path = self._settings.get("db_path", "")
        if not os.path.isfile(db_path):
            QMessageBox.warning(
                self,
                tr("msg.db_not_found.title"),
                tr("msg.db_not_found.body", path=db_path),
            )
            return False

        if not self._settings.get("google_api_key", "").strip():
            QMessageBox.warning(
                self,
                tr("msg.api_key_missing.title"),
                tr("msg.api_key_missing.body"),
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

        if self._range_check.isChecked():
            if self._range_from_spin.value() > self._range_to_spin.value():
                QMessageBox.warning(
                    self,
                    tr("msg.invalid_range.title"),
                    tr("msg.invalid_range.body"),
                )
                return False

        return True

    def _run(self):
        if not self._validate():
            return

        mode_id = self._who_group.checkedId()
        mode = ["single", "multiple", "plan", "all"][mode_id]
        year = self._year_spin.value()
        month = self._month_combo.currentIndex() + 1
        preview = self._preview_check.isChecked()
        debug = self._debug_check.isChecked()
        separate_by_plan = self._mltc_folders_check.isChecked()
        if self._range_check.isChecked():
            start_day = self._range_from_spin.value()
            end_day = self._range_to_spin.value()
        else:
            start_day = None
            end_day = None

        center_id = int(self._single_id.text()) if mode == "single" else None
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
        self._print_btn.setVisible(False)
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
            google_api_key=self._settings["google_api_key"],
            geo_cache=self._settings["geo_cache"],
            debug=debug,
            start_day=start_day,
            end_day=end_day,
            schedule_rules=self._settings.get("schedule_rules"),
            separate_by_plan=separate_by_plan,
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
        self._last_generated = payload.get("generated_paths", []) or []
        # Show the folder/print buttons whenever at least one schedule was
        # written — even on a partial run where some members were skipped.
        if not preview and self._last_generated:
            self._open_folder_btn.setVisible(True)
            self._print_btn.setVisible(True)
        if not success:
            QMessageBox.warning(
                self, tr("msg.completed_errors.title"), summary
            )

    def _build_summary(self, data: dict) -> str:
        scope = data["scope"]
        period = f"{scope['year']:04d}-{scope['month']:02d}"
        mode = scope.get("mode")
        if mode == "plan":
            scope_text = tr("scope.plan", code=scope["plan_code"], period=period)
        elif mode == "all":
            scope_text = tr("scope.all", period=period)
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
            reason = _translate_reason(f["reason"])
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
