import os

from PyQt6.QtCore import Qt, QTime
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTimeEdit,
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


def _hhmm(t: QTime) -> str:
    return f"{t.hour():02d}:{t.minute():02d}"


def _minutes_to_qtime(total: int) -> QTime:
    """Treat `total` (minutes) as a duration and render as QTime so the
    visit-length spinbox can use a familiar HH:MM picker."""
    return QTime(total // 60, total % 60)


def _qtime_to_minutes(t: QTime) -> int:
    return t.hour() * 60 + t.minute()


# Characters Windows forbids in filenames; the billing name is pasted
# straight into the billing workbook's filename.
_FORBIDDEN_FILENAME_CHARS = set('\\/:*?"<>|')


def billing_name_error(text: str) -> str | None:
    """Validate the billing file name. Returns "missing" when blank,
    "invalid" when it contains a character Windows forbids in
    filenames, None when usable."""
    stripped = text.strip()
    if not stripped:
        return "missing"
    if _FORBIDDEN_FILENAME_CHARS & set(stripped):
        return "invalid"
    return None


def _format_member_ids(ids) -> str:
    return ", ".join(str(i) for i in ids)


def parse_member_ids(text: str):
    """'24010, 24011' -> [24010, 24011]. Blank -> []. Returns None when
    any token is not an integer (caller warns and blocks the save)."""
    tokens = [t for t in text.replace(",", " ").split() if t]
    ids = []
    for t in tokens:
        try:
            ids.append(int(t))
        except ValueError:
            return None
    return ids


class _RangeSpins(QHBoxLayout):
    """Two side-by-side QSpinBoxes for a (min, max) integer range."""

    def __init__(self, lo: int, hi: int,
                 spin_min: int = 0, spin_max: int = 60):
        super().__init__()
        self.setContentsMargins(0, 0, 0, 0)
        self.lo_spin = QSpinBox()
        self.lo_spin.setRange(spin_min, spin_max)
        self.lo_spin.setValue(lo)
        self.lo_spin.setFixedWidth(64)
        self.hi_spin = QSpinBox()
        self.hi_spin.setRange(spin_min, spin_max)
        self.hi_spin.setValue(hi)
        self.hi_spin.setFixedWidth(64)
        self.dash = QLabel(" – ")
        self.addWidget(self.lo_spin)
        self.addWidget(self.dash)
        self.addWidget(self.hi_spin)
        self.addStretch()

    def value(self):
        return (self.lo_spin.value(), self.hi_spin.value())


class _RangeTimes(QHBoxLayout):
    """Two side-by-side QTimeEdits for a (lo HH:MM, hi HH:MM) range."""

    def __init__(self, lo: QTime, hi: QTime):
        super().__init__()
        self.setContentsMargins(0, 0, 0, 0)
        self.lo_edit = QTimeEdit()
        self.lo_edit.setDisplayFormat("HH:mm")
        self.lo_edit.setTime(lo)
        self.lo_edit.setFixedWidth(82)
        self.hi_edit = QTimeEdit()
        self.hi_edit.setDisplayFormat("HH:mm")
        self.hi_edit.setTime(hi)
        self.hi_edit.setFixedWidth(82)
        self.dash = QLabel(" – ")
        self.addWidget(self.lo_edit)
        self.addWidget(self.dash)
        self.addWidget(self.hi_edit)
        self.addStretch()

    def hhmm_value(self):
        return (_hhmm(self.lo_edit.time()), _hhmm(self.hi_edit.time()))

    def minutes_value(self):
        return (
            _qtime_to_minutes(self.lo_edit.time()),
            _qtime_to_minutes(self.hi_edit.time()),
        )


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
        self._billing_name_edit = QLineEdit(
            settings.get("billing_name", "")
        )
        self._program_name_edit = QLineEdit(
            settings.get("program_name", "")
        )

        self._db_label = QLabel()
        self._out_label = QLabel()
        self._api_key_label = QLabel()
        self._cache_label = QLabel()
        self._billing_name_label = QLabel()
        self._program_name_label = QLabel()

        form.addRow(self._db_label, self._db_row)
        form.addRow(self._out_label, self._out_row)
        form.addRow(self._api_key_label, self._key_row)
        form.addRow(self._cache_label, self._cache_row)
        form.addRow(self._billing_name_label, self._billing_name_edit)
        form.addRow(self._program_name_label, self._program_name_edit)
        layout.addLayout(form)

        # ── Scheduling Rules ─────────────────────────────────────
        rules = settings.get("schedule_rules") or {}
        self._rules_group = QGroupBox()
        rules_form = QFormLayout(self._rules_group)
        rules_form.setVerticalSpacing(8)

        sess_lo, sess_hi = rules.get("session_length_min", [210, 240])
        self._session_row = _RangeTimes(
            _minutes_to_qtime(int(sess_lo)),
            _minutes_to_qtime(int(sess_hi)),
        )
        self._session_label = QLabel()
        rules_form.addRow(self._session_label, self._session_row)

        tb_lo, tb_hi = rules.get("travel_buffer_min", [1, 5])
        self._travel_row = _RangeSpins(int(tb_lo), int(tb_hi))
        self._travel_label = QLabel()
        rules_form.addRow(self._travel_label, self._travel_row)

        ti_lo, ti_hi = rules.get("time_in_drift_min", [2, 2])
        self._time_in_row = _RangeSpins(int(ti_lo), int(ti_hi))
        self._time_in_label = QLabel()
        rules_form.addRow(self._time_in_label, self._time_in_row)

        to_lo, to_hi = rules.get("time_out_drift_min", [2, 2])
        self._time_out_row = _RangeSpins(int(to_lo), int(to_hi))
        self._time_out_label = QLabel()
        rules_form.addRow(self._time_out_label, self._time_out_row)

        self._dropoff_deadline_check = QCheckBox()
        self._dropoff_deadline_check.setChecked(
            bool(rules.get("dropoff_by_avail_end", True))
        )
        self._dropoff_deadline_label = QLabel()
        rules_form.addRow(self._dropoff_deadline_label,
                          self._dropoff_deadline_check)

        self._pickup_deadline_check = QCheckBox()
        self._pickup_deadline_check.setChecked(
            bool(rules.get("pickup_by_avail_start", True))
        )
        self._pickup_deadline_label = QLabel()
        rules_form.addRow(self._pickup_deadline_label,
                          self._pickup_deadline_check)

        self._band_enabled_check = QCheckBox()
        self._band_enabled_check.setChecked(
            bool(rules.get("band_enabled", False))
        )
        self._band_enabled_label = QLabel()
        rules_form.addRow(self._band_enabled_label,
                          self._band_enabled_check)

        self._morning_percent_spin = QSpinBox()
        self._morning_percent_spin.setRange(0, 100)
        self._morning_percent_spin.setValue(
            int(rules.get("morning_percent", 80))
        )
        self._morning_percent_spin.setFixedWidth(64)
        self._morning_percent_label = QLabel()
        rules_form.addRow(self._morning_percent_label,
                          self._morning_percent_spin)

        self._morning_window_edit = QTimeEdit()
        self._morning_window_edit.setDisplayFormat("HH:mm")
        self._morning_window_edit.setTime(
            _minutes_to_qtime(int(rules.get("morning_window_min", 180)))
        )
        self._morning_window_edit.setFixedWidth(82)
        self._morning_window_label = QLabel()
        rules_form.addRow(self._morning_window_label,
                          self._morning_window_edit)

        self._saved_morning_ids = list(rules.get("morning_members") or [])
        self._saved_afternoon_ids = list(rules.get("afternoon_members") or [])

        self._morning_ids_edit = QLineEdit(
            _format_member_ids(rules.get("morning_members") or [])
        )
        self._morning_ids_label = QLabel()
        rules_form.addRow(self._morning_ids_label, self._morning_ids_edit)

        self._afternoon_ids_edit = QLineEdit(
            _format_member_ids(rules.get("afternoon_members") or [])
        )
        self._afternoon_ids_label = QLabel()
        rules_form.addRow(self._afternoon_ids_label,
                          self._afternoon_ids_edit)

        # Grey out the band fields while the feature is off, so it's
        # obvious they have no effect.
        self._band_enabled_check.toggled.connect(self._update_band_enabled)
        self._update_band_enabled()

        layout.addWidget(self._rules_group)

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
        self._billing_name_label.setText(tr("settings.billing_name_label"))
        self._program_name_label.setText(tr("settings.program_name_label"))
        self._db_row.retranslate()
        self._out_row.retranslate()
        self._key_row.retranslate()
        self._cache_row.retranslate()
        if self._test_btn is not None:
            self._test_btn.setText(tr("settings.test_connection"))
        self._rules_group.setTitle(tr("settings.rules.title"))
        self._session_label.setText(tr("settings.rules.session"))
        self._travel_label.setText(tr("settings.rules.travel_buffer"))
        self._time_in_label.setText(tr("settings.rules.time_in"))
        self._time_out_label.setText(tr("settings.rules.time_out"))
        self._dropoff_deadline_label.setText(
            tr("settings.rules.dropoff_deadline")
        )
        self._pickup_deadline_label.setText(
            tr("settings.rules.pickup_deadline")
        )
        self._band_enabled_label.setText(tr("settings.rules.band_enabled"))
        self._morning_percent_label.setText(
            tr("settings.rules.morning_percent")
        )
        self._morning_window_label.setText(
            tr("settings.rules.morning_window")
        )
        self._morning_ids_label.setText(
            tr("settings.rules.morning_members")
        )
        self._afternoon_ids_label.setText(
            tr("settings.rules.afternoon_members")
        )

    def _update_band_enabled(self):
        on = self._band_enabled_check.isChecked()
        for w in (self._morning_percent_spin, self._morning_window_edit,
                  self._morning_ids_edit, self._afternoon_ids_edit):
            w.setEnabled(on)

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
        name_problem = billing_name_error(self._billing_name_edit.text())
        if name_problem is not None:
            QMessageBox.warning(
                self,
                tr(f"settings.billing_name_{name_problem}.title"),
                tr(f"settings.billing_name_{name_problem}.body"),
            )
            return
        session = self._session_row.minutes_value()
        travel = self._travel_row.value()
        time_in = self._time_in_row.value()
        time_out = self._time_out_row.value()
        # Guardrail: each min must be <= its max. On any violation we
        # warn and ask the user to fix it rather than silently swapping
        # (which would change their intent).
        ranges = [session, travel, time_in, time_out]
        bad = any(lo > hi for lo, hi in ranges)
        if bad:
            QMessageBox.warning(
                self,
                tr("settings.rules.invalid_range.title"),
                tr("settings.rules.invalid_range.body"),
            )
            return
        band_enabled = self._band_enabled_check.isChecked()
        morning_ids = parse_member_ids(self._morning_ids_edit.text())
        afternoon_ids = parse_member_ids(self._afternoon_ids_edit.text())
        if band_enabled:
            if morning_ids is None or afternoon_ids is None:
                QMessageBox.warning(
                    self,
                    tr("settings.rules.band_invalid_ids.title"),
                    tr("settings.rules.band_invalid_ids.body"),
                )
                return
            overlap = sorted(set(morning_ids) & set(afternoon_ids))
            if overlap:
                QMessageBox.warning(
                    self,
                    tr("settings.rules.band_conflict.title"),
                    tr("settings.rules.band_conflict.body",
                       ids=_format_member_ids(overlap)),
                )
                return
        else:
            # Fields are disabled while off; junk left in a field must
            # not erase the previously saved list.
            if morning_ids is None:
                morning_ids = self._saved_morning_ids
            if afternoon_ids is None:
                afternoon_ids = self._saved_afternoon_ids
        self._result = {
            "db_path": self._db_row.value(),
            "output_path": self._out_row.value(),
            "google_api_key": self._key_row.value(),
            "geo_cache": self._cache_row.value(),
            "billing_name": self._billing_name_edit.text().strip(),
            "program_name": self._program_name_edit.text().strip(),
            "schedule_rules": {
                "session_length_min": list(session),
                "travel_buffer_min": list(travel),
                "time_in_drift_min": list(time_in),
                "time_out_drift_min": list(time_out),
                "dropoff_by_avail_end":
                    self._dropoff_deadline_check.isChecked(),
                "pickup_by_avail_start":
                    self._pickup_deadline_check.isChecked(),
                "band_enabled": band_enabled,
                "morning_percent": self._morning_percent_spin.value(),
                "morning_window_min":
                    _qtime_to_minutes(self._morning_window_edit.time()),
                "morning_members": morning_ids,
                "afternoon_members": afternoon_ids,
            },
        }
        self.accept()

    def get_settings(self) -> dict | None:
        return self._result
