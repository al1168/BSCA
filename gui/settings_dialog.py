import os

from PyQt6.QtCore import Qt, QTime
from PyQt6.QtWidgets import (
    QApplication,
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


def _time_from_hhmm(text: str) -> QTime:
    """'HH:MM' -> QTime, falling back to midnight on malformed input."""
    try:
        h, m = text.split(":")
        return QTime(int(h), int(m))
    except (ValueError, AttributeError):
        return QTime(0, 0)


def _hhmm(t: QTime) -> str:
    return f"{t.hour():02d}:{t.minute():02d}"


def _minutes_to_qtime(total: int) -> QTime:
    """Treat `total` (minutes) as a duration and render as QTime so the
    visit-length spinbox can use a familiar HH:MM picker."""
    return QTime(total // 60, total % 60)


def _qtime_to_minutes(t: QTime) -> int:
    return t.hour() * 60 + t.minute()


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

        self._db_label = QLabel()
        self._out_label = QLabel()
        self._api_key_label = QLabel()
        self._cache_label = QLabel()

        form.addRow(self._db_label, self._db_row)
        form.addRow(self._out_label, self._out_row)
        form.addRow(self._api_key_label, self._key_row)
        form.addRow(self._cache_label, self._cache_row)
        layout.addLayout(form)

        # ── Scheduling Rules ─────────────────────────────────────
        rules = settings.get("schedule_rules") or {}
        self._rules_group = QGroupBox()
        rules_form = QFormLayout(self._rules_group)
        rules_form.setVerticalSpacing(8)

        self._earliest_in_edit = QTimeEdit()
        self._earliest_in_edit.setDisplayFormat("HH:mm")
        self._earliest_in_edit.setTime(
            _time_from_hhmm(rules.get("earliest_time_in", "08:00"))
        )
        self._earliest_in_edit.setFixedWidth(82)
        self._earliest_in_label = QLabel()
        rules_form.addRow(self._earliest_in_label, self._earliest_in_edit)

        self._latest_out_edit = QTimeEdit()
        self._latest_out_edit.setDisplayFormat("HH:mm")
        self._latest_out_edit.setTime(
            _time_from_hhmm(rules.get("latest_time_out", "16:00"))
        )
        self._latest_out_edit.setFixedWidth(82)
        self._latest_out_label = QLabel()
        rules_form.addRow(self._latest_out_label, self._latest_out_edit)

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
        self._db_row.retranslate()
        self._out_row.retranslate()
        self._key_row.retranslate()
        self._cache_row.retranslate()
        if self._test_btn is not None:
            self._test_btn.setText(tr("settings.test_connection"))
        self._rules_group.setTitle(tr("settings.rules.title"))
        self._earliest_in_label.setText(tr("settings.rules.earliest_in"))
        self._latest_out_label.setText(tr("settings.rules.latest_out"))
        self._session_label.setText(tr("settings.rules.session"))
        self._travel_label.setText(tr("settings.rules.travel_buffer"))
        self._time_in_label.setText(tr("settings.rules.time_in"))
        self._time_out_label.setText(tr("settings.rules.time_out"))

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
        earliest_in = _hhmm(self._earliest_in_edit.time())
        latest_out = _hhmm(self._latest_out_edit.time())
        session = self._session_row.minutes_value()
        travel = self._travel_row.value()
        time_in = self._time_in_row.value()
        time_out = self._time_out_row.value()
        # Guardrail: each min must be <= its max, and the day bounds must
        # be ordered (earliest Time-In before latest Time-Out). On any
        # violation we warn and ask the user to fix it rather than
        # silently swapping (which would change their intent).
        ranges = [session, travel, time_in, time_out]
        bad = any(lo > hi for lo, hi in ranges)
        bad = bad or (
            _qtime_to_minutes(self._earliest_in_edit.time())
            >= _qtime_to_minutes(self._latest_out_edit.time())
        )
        if bad:
            QMessageBox.warning(
                self,
                tr("settings.rules.invalid_range.title"),
                tr("settings.rules.invalid_range.body"),
            )
            return
        self._result = {
            "db_path": self._db_row.value(),
            "output_path": self._out_row.value(),
            "google_api_key": self._key_row.value(),
            "geo_cache": self._cache_row.value(),
            "schedule_rules": {
                "earliest_time_in": earliest_in,
                "latest_time_out": latest_out,
                "session_length_min": list(session),
                "travel_buffer_min": list(travel),
                "time_in_drift_min": list(time_in),
                "time_out_drift_min": list(time_out),
            },
        }
        self.accept()

    def get_settings(self) -> dict | None:
        return self._result
