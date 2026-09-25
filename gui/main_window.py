import calendar
import datetime
import math
import os
import subprocess
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QIntValidator
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui import app_settings
from gui.counts_worker import CountsWorker
from gui.i18n import LanguageManager, tr
from gui.plan_counts import PLAN_CODES, plan_table_rows, scope_caption
from gui.printing import (
    printable_schedules, default_printer_name, partition_printed,
)
from gui.print_worker import PrintWorker
from gui.settings_dialog import SettingsDialog
from gui.worker import ScheduleWorker
from new_monthly_schedule import REASON_NOT_FOUND, parse_center_ids, resolve_output_dir
from monthly_schedule.per_day import (
    REASON_NOT_ENROLLED,
    REASON_NO_AUTH,
    REASON_ABSENT_MONTH,
    REASON_NO_ELIGIBLE_DAYS,
    REASON_CENTER_CLOSED_MONTH,
)

# Landscape layout (spec 2026-09-23): controls in a fixed-width left
# column, progress/log/summary on the right, everything on screen at
# once on a 1366x768 display.
WINDOW_SIZE = (1280, 720)
MIN_SIZE = (1100, 680)
LEFT_WIDTH = 560
PLAN_ROW_HEIGHT = 22
# Pixels left for the Save To path once the title and Change button
# have taken theirs (560 - margins - ~70 title - 80 button).
OUT_PATH_WIDTH = 360
# Every pixel size and font size in this window is a design value for
# WINDOW_SIZE. A bigger window (maximized on a 1080p monitor) scales
# them all up in UI_SCALE_STEP steps, so the left column keeps the
# share of the window it has at the default size instead of the log
# and summary panes taking all the extra room (spec 2026-09-25).
UI_SCALE_STEP = 0.1
UI_SCALE_MAX = 2.0
BASE_FONT_PT = 9     # Segoe UI 9pt, the Windows default UI font
CAPTION_PX = 11


def max_ui_scale(width: int) -> float:
    """The largest UI scale a window this wide can take: how many times
    wider it is than WINDOW_SIZE, rounded down to a step, never below
    1.0 or above UI_SCALE_MAX. The height limit is measured instead
    (see MainWindow._fit_ui_scale): padding, spacing and check boxes
    do not grow with the text, so a height ratio would undershoot."""
    raw = width / WINDOW_SIZE[0]
    steps = math.floor(raw / UI_SCALE_STEP + 1e-9)
    return max(1.0, min(UI_SCALE_MAX, round(steps * UI_SCALE_STEP, 1)))


def _translate_one_off_reason(detail: dict) -> str:
    """Build the one-off conflict sentence in the current language from
    the structured detail carried on the failure. Mirrors
    monthly_schedule.per_day.format_one_off_conflict(), which produces
    the English text written to the CSV reports."""
    if detail["kind"] == "duplicate":
        parts = [
            tr("summary.reason.one_off_row",
               window=f"{r['avail_start']}-{r['avail_end']}",
               row_id=r["id"])
            for r in detail["one_offs"]
        ]
        if len(parts) == 1:
            rows = parts[0]
        else:
            rows = (
                tr("summary.reason.one_off_join").join(parts[:-1])
                + tr("summary.reason.one_off_join_last")
                + parts[-1]
            )
        return tr(
            "summary.reason.one_off_duplicate",
            count=len(parts), day=detail["day"], rows=rows,
        )

    one_off = detail["one_offs"][0]
    absence = detail["absence"]
    leave_type = str(absence["leave_type"] or "").strip()
    key = (
        "summary.reason.one_off_absence" if leave_type
        else "summary.reason.one_off_absence_untyped"
    )
    return tr(
        key,
        window=f"{one_off['avail_start']}-{one_off['avail_end']}",
        day=detail["day"],
        one_off_id=one_off["id"],
        leave_type=leave_type,
        start=absence["start_date"],
        end=absence["end_date"],
        absence_id=absence["id"],
    )


def _translate_reason(reason: str, detail: dict = None) -> str:
    if detail:
        return _translate_one_off_reason(detail)
    if reason == REASON_NOT_FOUND:
        return tr("summary.reason.not_found")
    if reason == REASON_NOT_ENROLLED:
        return tr("summary.reason.not_enrolled")
    if reason == REASON_NO_AUTH:
        return tr("summary.reason.no_auth")
    if reason == REASON_ABSENT_MONTH:
        return tr("summary.reason.absent_month")
    if reason == REASON_NO_ELIGIBLE_DAYS:
        return tr("summary.reason.no_eligible_days")
    if reason == REASON_CENTER_CLOSED_MONTH:
        return tr("summary.reason.center_closed_month")
    return reason


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self._settings = app_settings.load()
        self._worker = None
        self._print_worker = None
        self._counts_workers = set()  # retain refs until threads finish
        self._counts_seq = 0          # stale-result guard
        self._counts_timer = QTimer(self)
        self._counts_timer.setSingleShot(True)
        self._counts_timer.setInterval(300)   # debounce month spinning
        self._counts_timer.timeout.connect(self._start_counts_refresh)
        self._last_out_dir = None
        self._last_generated = []   # .xlsx paths from the last run
        # Abspaths successfully printed this session; lets a re-click
        # after a printer failure send only the unprinted remainder.
        # Cleared when a new generation run finishes (files rewritten).
        self._printed_ok = set()
        # Scaling state (see max_ui_scale). The registries hold design
        # values; _apply_ui_scale re-applies them at the current scale.
        self._ui_scale = 1.0
        self._left_heights = {}  # scale -> left column height, measured
        self._fixed_sizes = []   # (widget, width or None, height or None)
        self._fixed_fonts = []   # (widget, family or None, points, bold)
        self._captions = []      # small gray labels sized in pixels
        self._out_path = ""

        root = QHBoxLayout(self)
        root.setSpacing(12)
        self._left_panel = QWidget()
        left = QVBoxLayout(self._left_panel)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)
        right = QVBoxLayout()
        right.setSpacing(6)
        root.addWidget(self._left_panel, 0)
        root.addLayout(right, 1)

        # ── Top bar ────────────────────────────────────────────────
        top = QHBoxLayout()
        self._title_label = QLabel()
        self._fix_font(self._title_label, 13, bold=True)
        top.addWidget(self._title_label, 1)

        self._lang_combo = QComboBox()
        self._lang_combo.addItem("English", "en")
        self._lang_combo.addItem("中文", "zh")
        self._fix_size(self._lang_combo, width=90)
        # Reflect the current language without firing a switch.
        current_lang = self._settings.get("language", "en")
        idx = self._lang_combo.findData(current_lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        top.addWidget(self._lang_combo)

        self._settings_btn = QPushButton("⚙")
        self._fix_size(self._settings_btn, 32, 32)
        self._settings_btn.clicked.connect(self._open_settings)
        top.addWidget(self._settings_btn)
        left.addLayout(top)

        # ── WHO ────────────────────────────────────────────────────
        self._who_box = QGroupBox()
        who_layout = QVBoxLayout(self._who_box)
        who_layout.setSpacing(4)
        who_layout.setContentsMargins(8, 4, 8, 6)

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
        self._fix_size(self._single_id, width=120)
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

        # Panel 2 — plan (selection happens in the table below)
        p2 = QWidget()
        p2_layout = QHBoxLayout(p2)
        p2_layout.setContentsMargins(0, 0, 0, 0)
        self._plan_hint_label = QLabel()
        self._plan_hint_label.setWordWrap(True)
        p2_layout.addWidget(self._plan_hint_label, 1)

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

        # Plan-counts table (spec 2026-07-28): always visible; rows are
        # the 8 known plans plus a bold All Members total row.
        self._plan_row = 0            # selected plan index into PLAN_CODES
        self._plan_counts = None      # last counts result (None=loading)
        self._counts_failed = False
        self._syncing_selection = False

        self._plan_table = QTableWidget(len(PLAN_CODES) + 1, 3)
        self._plan_table.verticalHeader().setVisible(False)
        self._plan_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._plan_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._plan_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._plan_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._plan_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._plan_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        header = self._plan_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        for row in range(len(PLAN_CODES) + 1):
            for col in range(3):
                item = QTableWidgetItem("")
                if col > 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter
                    )
                if row == len(PLAN_CODES):
                    font = QFont()
                    font.setBold(True)
                    item.setFont(font)
                self._plan_table.setItem(row, col, item)
        self._plan_table.selectionModel().selectionChanged.connect(
            self._on_plan_selection_changed
        )
        who_layout.addWidget(self._plan_table)

        caption_row = QHBoxLayout()
        self._roster_label = QLabel()
        self._excluded_label = QLabel()
        self._captions += [self._roster_label, self._excluded_label]
        caption_row.addWidget(self._roster_label)
        caption_row.addStretch()
        caption_row.addWidget(self._excluded_label)
        who_layout.addLayout(caption_row)

        left.addWidget(self._who_box)

        # ── WHEN ───────────────────────────────────────────────────
        self._when_box = QGroupBox()
        when_outer = QVBoxLayout(self._when_box)
        when_outer.setSpacing(4)
        when_outer.setContentsMargins(8, 4, 8, 6)
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
        self._fix_size(self._year_spin, width=80)
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
        self._fix_size(self._range_from_spin, width=56)
        self._range_from_spin.setEnabled(False)
        range_row.addWidget(self._range_from_spin)
        self._range_to_label = QLabel()
        range_row.addWidget(self._range_to_label)
        self._range_to_spin = QSpinBox()
        self._range_to_spin.setRange(1, 31)
        self._range_to_spin.setValue(31)
        self._fix_size(self._range_to_spin, width=56)
        self._range_to_spin.setEnabled(False)
        range_row.addWidget(self._range_to_spin)
        range_row.addStretch()
        when_outer.addLayout(range_row)

        # Keep the spin-box maxima in sync with the selected month/year
        # so a user can't pick April 31 or Feb 29 in a non-leap year.
        self._month_combo.currentIndexChanged.connect(self._update_range_max)
        self._year_spin.valueChanged.connect(self._update_range_max)
        self._month_combo.currentIndexChanged.connect(
            lambda _i: self._counts_timer.start()
        )
        self._year_spin.valueChanged.connect(
            lambda _v: self._counts_timer.start()
        )
        self._update_range_max()
        left.addWidget(self._when_box)

        # ── SAVE TO ────────────────────────────────────────────────
        # A plain row, not a group box: the group frame and title cost
        # ~25px the left column cannot spare (spec 2026-09-23).
        save_layout = QHBoxLayout()
        save_layout.setContentsMargins(8, 0, 8, 0)
        self._save_title = QLabel()
        save_font = QFont()
        save_font.setBold(True)
        self._save_title.setFont(save_font)
        save_layout.addWidget(self._save_title)
        # One line, elided in the middle: a long path that wrapped would
        # push the column below the fold. The full path is the tooltip.
        self._out_label = QLabel()
        save_layout.addWidget(self._out_label, 1)
        self._set_out_path(self._settings.get("output_path", "."))
        self._change_btn = QPushButton()
        self._fix_size(self._change_btn, width=80)
        self._change_btn.clicked.connect(self._open_settings)
        save_layout.addWidget(self._change_btn)
        left.addLayout(save_layout)

        # ── Actions ────────────────────────────────────────────────
        self._actions_box = QGroupBox()
        actions = QVBoxLayout(self._actions_box)
        actions.setSpacing(4)
        actions.setContentsMargins(8, 4, 8, 6)
        self._debug_check = QCheckBox()
        actions.addWidget(self._debug_check)
        # All-Members only: split output into per-MLTC folders. Default
        # off -> everyone in one <Month>_<Year>_Timesheets folder.
        self._mltc_folders_check = QCheckBox()
        actions.addWidget(self._mltc_folders_check)

        self._generate_btn = QPushButton()
        self._fix_size(self._generate_btn, height=34)
        self._fix_font(self._generate_btn, 11, bold=True)
        self._generate_btn.clicked.connect(self._run)
        actions.addWidget(self._generate_btn)

        self._scope_label = QLabel()
        self._scope_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._captions.append(self._scope_label)
        actions.addWidget(self._scope_label)

        btn_row = QHBoxLayout()
        self._open_folder_btn = QPushButton()
        self._open_folder_btn.clicked.connect(self._open_output_folder)
        btn_row.addWidget(self._open_folder_btn)
        # Prints every schedule from the last run (never debug CSVs);
        # enabled only once a run has produced files.
        self._print_btn = QPushButton()
        self._print_btn.setEnabled(False)
        self._print_btn.clicked.connect(self._print_schedules)
        btn_row.addWidget(self._print_btn)
        actions.addLayout(btn_row)
        left.addWidget(self._actions_box)
        left.addStretch(1)

        # ── Right column: progress, log, summary ───────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        right.addWidget(self._progress)

        self._log_label = QLabel()
        right.addWidget(self._log_label)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._fix_font(self._log, 9, family="Consolas")
        # A long run logs a line per member; cap the scrollback.
        self._log.setMaximumBlockCount(5000)
        right.addWidget(self._log, 2)

        self._summary_label = QLabel()
        right.addWidget(self._summary_label)
        self._summary = QPlainTextEdit()
        self._summary.setReadOnly(True)
        right.addWidget(self._summary, 3)

        self.setMinimumSize(*MIN_SIZE)
        self.resize(*WINDOW_SIZE)

        self._update_plan_table()
        self._apply_ui_scale(1.0)

        # Wire up live retranslation and apply once.
        LanguageManager.instance().languageChanged.connect(self._retranslate)
        self._retranslate()

        self._start_counts_refresh()

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
        self._plan_hint_label.setText(tr("who.plan_hint"))
        self._plan_table.setHorizontalHeaderLabels([
            tr("plan_table.header.plan"),
            tr("plan_table.header.active"),
            tr("plan_table.header.inactive"),
        ])
        self._excluded_label.setText(tr("plan_table.excluded"))
        self._update_plan_table()
        self._all_hint_label.setText(tr("who.all_hint"))

        self._when_box.setTitle(tr("when.title"))
        self._month_label_widget.setText(tr("when.month_label"))
        self._year_label_widget.setText(tr("when.year_label"))
        for i in range(12):
            self._month_combo.setItemText(i, tr(f"when.month.{i + 1}"))
        self._range_check.setText(tr("when.range_check"))
        self._range_from_label.setText(tr("when.range_from"))
        self._range_to_label.setText(tr("when.range_to"))

        self._save_title.setText(tr("save.title"))
        self._change_btn.setText(tr("save.change"))

        self._debug_check.setText(tr("opts.debug"))
        self._mltc_folders_check.setText(tr("opts.mltc_folders"))
        self._generate_btn.setText(tr("opts.generate"))
        self._open_folder_btn.setText(tr("opts.open_folder"))
        self._print_btn.setText(tr("opts.print"))
        self._actions_box.setTitle(tr("actions.title"))
        self._log_label.setText(tr("log.title"))
        self._summary_label.setText(tr("summary.title"))
        # New text can change the left column's height (Chinese uses a
        # taller font), so measure every scale again.
        self._left_heights.clear()
        self._fit_ui_scale()

    # ── Slots ─────────────────────────────────────────────────────

    def _on_who_changed(self, btn_id: int, checked: bool):
        if checked:
            self._who_stack.setCurrentIndex(btn_id)
            self._sync_plan_selection()

    def _on_plan_row_clicked(self, row: int, _col: int):
        if row < len(PLAN_CODES):
            self._plan_row = row
            self._radio_plan.setChecked(True)
        else:
            self._radio_all.setChecked(True)
        self._sync_plan_selection()

    def _on_plan_selection_changed(self, _selected, _deselected):
        """User-driven selection (click, press, drag) picks a plan; the
        guard skips our own programmatic selectRow/clearSelection."""
        if self._syncing_selection:
            return
        rows = self._plan_table.selectionModel().selectedRows()
        if not rows:
            # Ctrl+click deselect: snap the highlight back to the mode's
            # row (runs under the guard inside _sync_plan_selection).
            if self._who_group.checkedId() in (2, 3):
                self._sync_plan_selection()
            return
        self._on_plan_row_clicked(rows[0].row(), 0)

    def _sync_plan_selection(self):
        """Reflect the Who mode in the table highlight + scope caption."""
        mode_id = self._who_group.checkedId()
        self._syncing_selection = True
        try:
            if mode_id == 2:
                self._plan_table.selectRow(self._plan_row)
            elif mode_id == 3:
                self._plan_table.selectRow(len(PLAN_CODES))
            else:
                self._plan_table.clearSelection()
        finally:
            self._syncing_selection = False
        self._update_scope_label()

    def _update_plan_table(self):
        rows, total = plan_table_rows(self._plan_counts)
        for i, (code, active, inactive) in enumerate(rows):
            self._plan_table.item(i, 0).setText(code)
            self._plan_table.item(i, 1).setText(active)
            self._plan_table.item(i, 2).setText(inactive)
        last = len(PLAN_CODES)
        self._plan_table.item(last, 0).setText(tr("plan_table.all_members"))
        self._plan_table.item(last, 1).setText(total)
        self._plan_table.item(last, 2).setText("")
        month = self._month_combo.currentIndex() + 1
        if self._counts_failed:
            self._roster_label.setText(tr("plan_table.unavailable"))
        else:
            self._roster_label.setText(tr(
                "plan_table.roster",
                month=tr(f"when.month.{month}"),
                year=self._year_spin.value(),
            ))
        self._update_scope_label()

    def _update_scope_label(self):
        mode_id = self._who_group.checkedId()
        if mode_id < 0:
            self._scope_label.setText("")
            return
        mode = ["single", "multiple", "plan", "all"][mode_id]
        month = self._month_combo.currentIndex() + 1
        self._scope_label.setText(scope_caption(
            self._plan_counts, mode, PLAN_CODES[self._plan_row],
            tr(f"when.month.{month}"), self._year_spin.value(),
        ))

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

    def _start_counts_refresh(self):
        """Fetch counts for the selected month on a background thread.
        Only the latest request's result is applied."""
        self._counts_seq += 1
        seq = self._counts_seq
        self._plan_counts = None
        self._counts_failed = False
        self._update_plan_table()
        worker = CountsWorker(
            self._settings.get("db_path", ""),
            self._year_spin.value(),
            self._month_combo.currentIndex() + 1,
        )
        worker.finished.connect(
            lambda ok, payload, w=worker:
                self._on_counts_finished(seq, w, ok, payload)
        )
        self._counts_workers.add(worker)
        worker.start()

    def _on_counts_finished(self, seq: int, worker, success: bool,
                            payload: dict):
        # The worker's custom finished signal fires BEFORE its thread
        # exits; wait() (near-instant here) then discard, so a running
        # QThread is never garbage-collected mid-run (hard crash).
        # This must happen on the stale path too.
        worker.wait()
        self._counts_workers.discard(worker)
        if seq != self._counts_seq:
            return   # a newer request superseded this one
        if success:
            self._plan_counts = payload
            self._counts_failed = False
        else:
            self._plan_counts = None
            self._counts_failed = True
        self._update_plan_table()

    def closeEvent(self, event):
        """Block close until in-flight counts fetches finish, so a
        running QThread is never garbage-collected at interpreter
        teardown (hard crash on exit). Counts queries are short —
        worst case one ODBC connect timeout. Schedule/print workers
        keep their pre-existing behavior (their buttons stay disabled
        while they run)."""
        for worker in list(self._counts_workers):
            worker.wait()
        super().closeEvent(event)

    def _open_settings(self):
        dlg = SettingsDialog(self._settings, self)
        if dlg.exec():
            result = dlg.get_settings()
            if result:
                old_db = self._settings.get("db_path")
                self._settings.update(result)
                app_settings.save(self._settings)
                self._set_out_path(self._settings.get("output_path", "."))
                if self._settings.get("db_path") != old_db:
                    self._start_counts_refresh()

    def _set_out_path(self, path: str):
        self._out_path = path
        metrics = self._out_label.fontMetrics()
        self._out_label.setText(metrics.elidedText(
            path, Qt.TextElideMode.ElideMiddle, self._px(OUT_PATH_WIDTH)))
        self._out_label.setToolTip(path)

    # -- Scaling on large windows (spec 2026-09-25) --------------------

    def _px(self, design_px: int) -> int:
        """A design-size pixel value at the current UI scale."""
        return round(design_px * self._ui_scale)

    def _fix_size(self, widget, width=None, height=None):
        """Fix the widget's width and/or height, given in design pixels;
        _apply_ui_scale keeps it in step with the UI scale."""
        self._fixed_sizes.append((widget, width, height))

    def _fix_font(self, widget, points, bold=False, family=None):
        """Give the widget its own font size (design points) that
        _apply_ui_scale keeps in step with the UI scale."""
        self._fixed_fonts.append((widget, family, points, bold))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_ui_scale()

    def _fit_ui_scale(self):
        """Use the largest scale the window width allows whose left
        column still fits the window height."""
        margins = self.layout().contentsMargins()
        room = self.height() - margins.top() - margins.bottom()
        scale = max_ui_scale(self.width())
        while scale > 1.0 and self._left_height(scale) > room:
            scale = round(scale - UI_SCALE_STEP, 1)
        if scale != self._ui_scale:
            self._apply_ui_scale(scale)

    def _left_height(self, scale: float) -> int:
        """The left column's height at this scale, measured the first
        time it is asked for, so dragging the window edge re-lays out
        only when the chosen scale changes."""
        if scale not in self._left_heights:
            self._apply_ui_scale(scale)
            self._left_heights[scale] = self._left_panel.sizeHint().height()
        return self._left_heights[scale]

    def _apply_ui_scale(self, scale: float):
        """Re-apply every font and fixed size at this scale (1.0 is the
        design size). The window font carries the scale to every widget
        without a font of its own."""
        self._ui_scale = scale
        base = QFont(QApplication.font())
        base.setPointSizeF(BASE_FONT_PT * scale)
        self.setFont(base)
        for widget, family, points, bold in self._fixed_fonts:
            font = QFont(family) if family else QFont()
            font.setPointSizeF(points * scale)
            font.setBold(bold)
            widget.setFont(font)
        for label in self._captions:
            label.setStyleSheet(
                f"color: gray; font-size: {self._px(CAPTION_PX)}px;")
        for widget, width, height in self._fixed_sizes:
            if width is not None:
                widget.setFixedWidth(self._px(width))
            if height is not None:
                widget.setFixedHeight(self._px(height))
        self._left_panel.setMinimumWidth(self._px(LEFT_WIDTH - 40))
        self._left_panel.setMaximumWidth(self._px(LEFT_WIDTH))
        # Plan table: rows and number columns grow with the text, and
        # the table stays exactly tall enough to show every row.
        table = self._plan_table
        table.verticalHeader().setDefaultSectionSize(self._px(PLAN_ROW_HEIGHT))
        table.setColumnWidth(1, self._px(130))
        table.setColumnWidth(2, self._px(100))
        table.setFixedHeight(
            table.horizontalHeader().sizeHint().height()
            + table.verticalHeader().defaultSectionSize() * table.rowCount()
            + 2 * table.frameWidth()
        )
        self._set_out_path(self._out_path)

    def _open_output_folder(self):
        """The last run's folder, else the Settings output folder so the
        button works before any run this session."""
        target = self._last_out_dir or self._settings.get("output_path", "")
        if target and os.path.isdir(target):
            if sys.platform == "win32":
                os.startfile(target)
            else:
                subprocess.Popen(["xdg-open", target])

    def _print_schedules(self):
        files = printable_schedules(self._last_generated)
        if not files:
            QMessageBox.information(
                self, tr("print.title"), tr("print.none")
            )
            return
        printer = default_printer_name() or tr("print.default_printer")
        to_print = self._choose_files_to_print(files, printer)
        if not to_print:
            return
        # Disable the buttons and stream progress while printing.
        self._print_btn.setEnabled(False)
        self._generate_btn.setEnabled(False)
        self._progress.setRange(0, len(to_print))
        self._progress.setValue(0)
        self._log.appendPlainText("")
        self._log.appendPlainText(tr("print.started", count=len(to_print)))
        self._print_worker = PrintWorker(to_print)
        self._print_worker.progress.connect(self._on_print_progress)
        self._print_worker.finished.connect(self._on_print_finished)
        self._print_worker.start()

    def _choose_files_to_print(self, files, printer):
        """Confirm with the user and return the list to print ([] to
        cancel). When part of the batch already printed this session
        (printer failure mid-run), offer remaining-only vs everything."""
        remaining, already = partition_printed(files, self._printed_ok)
        if not already:
            confirm = QMessageBox.question(
                self,
                tr("print.confirm.title"),
                tr("print.confirm.body", count=len(files), printer=printer),
            )
            return files if confirm == QMessageBox.StandardButton.Yes else []
        if not remaining:
            confirm = QMessageBox.question(
                self,
                tr("print.confirm.title"),
                tr("print.confirm.reprint_all", count=len(files)),
            )
            return files if confirm == QMessageBox.StandardButton.Yes else []
        box = QMessageBox(self)
        box.setWindowTitle(tr("print.confirm.title"))
        box.setText(tr("print.confirm.remaining",
                       remaining=len(remaining), total=len(files),
                       printer=printer))
        remaining_btn = box.addButton(
            tr("print.btn.remaining", count=len(remaining)),
            QMessageBox.ButtonRole.AcceptRole,
        )
        all_btn = box.addButton(
            tr("print.btn.all", count=len(files)),
            QMessageBox.ButtonRole.ActionRole,
        )
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(remaining_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is remaining_btn:
            return remaining
        if clicked is all_btn:
            return files
        return []

    def _on_print_progress(self, done: int, total: int):
        self._progress.setRange(0, total)
        self._progress.setValue(done)

    def _on_print_finished(self, success: bool, payload: dict):
        self._print_btn.setEnabled(True)
        self._generate_btn.setEnabled(True)
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        # Remember every file that reached the printer, even on partial
        # failure — a re-click offers to print only the remainder.
        for p in payload.get("printed", []):
            self._printed_ok.add(os.path.abspath(p))
        if success:
            self._log.appendPlainText(
                tr("print.done", count=len(payload.get("printed", [])))
            )
            return
        if "error" in payload:
            # Whole-batch failure (Excel/pywin32 missing): nothing was
            # attempted per-file, keep the original message.
            msg = tr("print.failed", error=payload.get("error", ""))
            self._log.appendPlainText(msg)
            QMessageBox.warning(self, tr("print.title"), msg)
            return
        failed = payload.get("failed", [])
        not_attempted = payload.get("not_attempted", [])
        for path, err in failed:
            self._log.appendPlainText(
                tr("print.file_failed",
                   name=os.path.basename(path), error=err)
            )
        if not_attempted:
            key = ("print.stalled" if payload.get("stalled")
                   else "print.stopped_early")
            self._log.appendPlainText(tr(key, count=len(not_attempted)))
        printed_n = len(payload.get("printed", []))
        total_n = printed_n + len(failed) + len(not_attempted)
        summary = tr("print.partial",
                     printed=printed_n, total=total_n,
                     failed=len(failed) + len(not_attempted))
        self._log.appendPlainText(summary)
        QMessageBox.warning(self, tr("print.title"), summary)

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
            # All Members writes the billing workbook, whose filename
            # needs the billing name. Settings saved by an older version
            # may not have one yet.
            if not self._settings.get("billing_name", "").strip():
                QMessageBox.warning(
                    self,
                    tr("msg.billing_name_missing.title"),
                    tr("msg.billing_name_missing.body"),
                )
                return False

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
        plan_code = PLAN_CODES[self._plan_row] if mode == "plan" else None

        out_base = self._settings.get("output_path", "").strip() or "."
        out_dir = resolve_output_dir(out_base, plan_code, year, month)

        self._log.clear()
        self._summary.clear()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._generate_btn.setEnabled(False)
        self._print_btn.setEnabled(False)
        self._last_out_dir = out_dir

        self._worker = ScheduleWorker(
            mode=mode,
            center_id=center_id,
            center_ids=center_ids,
            plan_code=plan_code,
            year=year,
            month=month,
            out_dir=out_dir,
            db_path=self._settings["db_path"],
            google_api_key=self._settings["google_api_key"],
            geo_cache=self._settings["geo_cache"],
            debug=debug,
            start_day=start_day,
            end_day=end_day,
            schedule_rules=self._settings.get("schedule_rules"),
            separate_by_plan=separate_by_plan,
            billing_name=self._settings.get("billing_name", "").strip(),
            program_name=self._settings.get("program_name", "").strip(),
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
        self._summary.setPlainText(summary)
        self._generate_btn.setEnabled(True)
        self._last_generated = payload.get("generated_paths", []) or []
        self._printed_ok.clear()   # fresh files — nothing printed yet
        # Print only makes sense once at least one schedule was written,
        # even on a partial run where some members were skipped.
        self._print_btn.setEnabled(bool(self._last_generated))
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

        # Billing attendance workbook (All-Members runs): success shows
        # the filename; a build failure is noted without failing the run.
        if data.get("billing_path"):
            head += "\n" + tr(
                "summary.billing",
                filename=os.path.basename(data["billing_path"]),
            )
        elif data.get("billing_error"):
            head += "\n" + tr(
                "summary.billing_failed", error=data["billing_error"]
            )

        if not data["failures"]:
            return head

        lines = [head, tr("summary.failures_header")]
        for f in data["failures"]:
            stage = tr(f"summary.stage.{f['stage']}")
            reason = _translate_reason(f["reason"], f.get("detail"))
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
