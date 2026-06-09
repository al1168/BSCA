"""Background worker that prepares a fresh BSCA database by chaining
the 5 setup scripts in order: backup → create_supporting_tables →
add_long_lat_to_contacts → backfill_enrollment_from_contacts →
backfill_authorization_from_contacts → backfill_availability_from_hha.

Each script's stdout is captured through a `LineBuffer` and forwarded
to the `log_line` signal, so the GUI can stream progress in real time."""
import contextlib
import datetime
import importlib
import shutil
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from setup_gui.log_buffer import LineBuffer


# The canonical list of setup steps, in execution order. Each entry is
# (display_name, dotted_module_path). The worker calls
# `<module>.main(["--db", path])` and treats a non-zero return code as
# a stop-the-chain failure.
SETUP_STEPS: list[tuple[str, str]] = [
    ("create_supporting_tables",
     "scripts.create_supporting_tables"),
    ("add_long_lat_to_contacts",
     "scripts.add_long_lat_to_contacts"),
    ("backfill_enrollment_from_contacts",
     "scripts.backfill_enrollment_from_contacts"),
    ("backfill_authorization_from_contacts",
     "scripts.backfill_authorization_from_contacts"),
    ("backfill_availability_from_hha",
     "scripts.backfill_availability_from_hha"),
]


def _backup_path(db_path: str) -> str:
    """Return `<stem>.backup_<YYYY-MM-DD-HHMMSS><ext>` in the same
    folder as `db_path`. Extension preserved so Access still opens
    the backup if double-clicked."""
    p = Path(db_path)
    ts = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return str(p.with_name(f"{p.stem}.backup_{ts}{p.suffix}"))


class SetupWorker(QThread):
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int, int)        # (done_step, total_steps=5)
    finished = pyqtSignal(bool, dict)      # (success, payload)

    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = db_path

    def run(self):
        # Step 0: backup.
        backup_path = _backup_path(self._db_path)
        try:
            shutil.copy2(self._db_path, backup_path)
        except OSError as exc:
            self.finished.emit(
                False, {"step": "backup", "error": str(exc)},
            )
            return
        self.log_line.emit(f"Backed up to {backup_path}")

        # Steps 1-5: chain.
        for i, (name, module_path) in enumerate(SETUP_STEPS, start=1):
            self.log_line.emit(f"Step {i}/{len(SETUP_STEPS)}: {name}")
            buf = LineBuffer(self.log_line.emit)
            try:
                # import_module caches in sys.modules. That's fine for
                # the packaged exe (fresh process per launch). In tests,
                # patches via monkeypatch.setattr on the already-imported
                # module work correctly because they mutate the cached
                # module object's attributes.
                module = importlib.import_module(module_path)
                with contextlib.redirect_stdout(buf):
                    rc = module.main(["--db", self._db_path])
                buf.flush()
            except Exception as exc:
                buf.flush()
                self.finished.emit(
                    False,
                    {"step": name, "error": str(exc),
                     "backup": backup_path},
                )
                return
            if rc != 0:
                self.finished.emit(
                    False,
                    {"step": name, "error": f"returned exit code {rc}",
                     "backup": backup_path},
                )
                return
            self.progress.emit(i, len(SETUP_STEPS))

        self.finished.emit(True, {"backup": backup_path})
