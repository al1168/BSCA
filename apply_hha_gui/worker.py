"""Background worker for the Apply HHA Answers GUI.

Runs scripts.apply_hha_answers.main() on a QThread — with --dry-run
for preview, or backup-then-apply for the real run — streaming the
script's stdout/stderr to the GUI line by line via `LineBuffer` (reused
from setup_gui; spec §6)."""
import contextlib
import datetime
import shutil
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from setup_gui.log_buffer import LineBuffer
from scripts import apply_hha_answers


def _backup_path(db_path: str) -> str:
    """`<stem>.backup_<YYYY-MM-DD-HHMMSS><ext>` in the same folder —
    same convention as setup_gui so operators see one backup style."""
    p = Path(db_path)
    ts = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return str(p.with_name(f"{p.stem}.backup_{ts}{p.suffix}"))


class ApplyHhaWorker(QThread):
    log_line = pyqtSignal(str)
    finished_run = pyqtSignal(bool, dict)   # (success, payload)

    def __init__(self, csv_path: str, db_path: str, mode: str,
                 parent=None):
        if mode not in ("preview", "apply"):
            raise ValueError(f"unknown mode: {mode!r}")
        super().__init__(parent)
        self._csv_path = csv_path
        self._db_path = db_path
        self._mode = mode

    def run(self):
        payload = {"mode": self._mode}

        if self._mode == "apply":
            backup = _backup_path(self._db_path)
            try:
                shutil.copy2(self._db_path, backup)
            except OSError as exc:
                self.finished_run.emit(
                    False,
                    {**payload, "step": "backup", "error": str(exc)},
                )
                return
            payload["backup"] = backup
            self.log_line.emit(f"Backed up to {backup}")

        argv = ["--csv", self._csv_path, "--db", self._db_path]
        if self._mode == "preview":
            argv.append("--dry-run")

        buf = LineBuffer(self.log_line.emit)
        try:
            with contextlib.redirect_stdout(buf), \
                    contextlib.redirect_stderr(buf):
                rc = apply_hha_answers.main(argv)
            buf.flush()
        except Exception as exc:
            buf.flush()
            self.finished_run.emit(
                False, {**payload, "step": "run", "error": str(exc)},
            )
            return
        if rc is not None and rc != 0:
            self.finished_run.emit(
                False,
                {**payload, "step": "run",
                 "error": f"returned exit code {rc}"},
            )
            return
        self.finished_run.emit(True, payload)
