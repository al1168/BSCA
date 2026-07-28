"""Background thread that fetches per-plan member counts.

Counts are informational (spec 2026-07-28): failures are emitted, not
raised — the main window shows an 'unavailable' caption, never a popup."""

import calendar
import datetime

from PyQt6.QtCore import QThread, pyqtSignal

from monthly_schedule.db import get_plan_member_counts


class CountsWorker(QThread):
    finished = pyqtSignal(bool, dict)   # (success, counts | {"error": str})

    def __init__(self, db_path, year, month, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._year = year
        self._month = month

    def run(self):
        try:
            last = calendar.monthrange(self._year, self._month)[1]
            counts = get_plan_member_counts(
                self._db_path,
                datetime.date(self._year, self._month, 1),
                datetime.date(self._year, self._month, last),
            )
            self.finished.emit(True, counts)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI caption
            self.finished.emit(False, {"error": str(exc)})
