"""Background worker that prepares a fresh BSCA database by chaining
the 7 setup scripts in order: backup → create_supporting_tables →
add_long_lat_to_contacts → add_document_to_authorization →
backfill_enrollment_from_contacts → backfill_authorization_from_contacts
→ backfill_availability_from_hha → backfill_emergency_contacts_from_contacts.

Optionally appends an 8th step (terminate_long_id_enrollments) when
the worker is constructed with `also_terminate=True`. That step is
opt-in because it's destructive cleanup (sets end_date=2000-01-01
for any member whose Center ID is more than 5 digits), not setup.

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
    ("add_document_to_authorization",
     "scripts.add_document_to_authorization"),
    ("add_document_to_transport_authorization",
     "scripts.add_document_to_transport_authorization"),
    ("add_created_at_to_authorization",
     "scripts.add_created_at_to_authorization"),
    ("add_member_id_to_authorization",
     "scripts.add_member_id_to_authorization"),
    ("add_auth_number_to_authorization",
     "scripts.add_auth_number_to_authorization"),
    ("change_dob_to_date_in_contacts",
     "scripts.change_dob_to_date_in_contacts"),
    ("backfill_enrollment_from_contacts",
     "scripts.backfill_enrollment_from_contacts"),
    ("backfill_authorization_from_contacts",
     "scripts.backfill_authorization_from_contacts"),
    ("backfill_availability_from_hha",
     "scripts.backfill_availability_from_hha"),
    ("backfill_emergency_contacts_from_contacts",
     "scripts.backfill_emergency_contacts_from_contacts"),
]


# Optional opt-in step. Same shape as the SETUP_STEPS tuples; the
# worker appends it to its local steps list when `also_terminate=True`.
TERMINATE_STEP: tuple[str, str] = (
    "terminate_long_id_enrollments",
    "scripts.terminate_long_id_enrollments",
)


def _backup_path(db_path: str) -> str:
    """Return `<stem>.backup_<YYYY-MM-DD-HHMMSS><ext>` in the same
    folder as `db_path`. Extension preserved so Access still opens
    the backup if double-clicked. `db_path` is expected to be
    absolute (the GUI's QFileDialog.getOpenFileName always returns
    an absolute path on Windows); a relative path would place the
    backup in the process CWD."""
    p = Path(db_path)
    ts = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return str(p.with_name(f"{p.stem}.backup_{ts}{p.suffix}"))


class SetupWorker(QThread):
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int, int)        # (done_step, total_steps)
    finished = pyqtSignal(bool, dict)      # (success, payload)

    def __init__(
        self, db_path: str, also_terminate: bool = False, parent=None,
    ):
        super().__init__(parent)
        self._db_path = db_path
        self._also_terminate = also_terminate

    def run(self):
        steps = list(SETUP_STEPS)
        if self._also_terminate:
            steps.append(TERMINATE_STEP)
        total = len(steps)

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

        # Chain the steps (5 by default; 6 if `also_terminate=True`).
        for i, (name, module_path) in enumerate(steps, start=1):
            self.log_line.emit(f"Step {i}/{total}: {name}")
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
                     "backup": backup_path, "total_steps": total},
                )
                return
            if rc is not None and rc != 0:
                self.finished.emit(
                    False,
                    {"step": name, "error": f"returned exit code {rc}",
                     "backup": backup_path, "total_steps": total},
                )
                return
            self.progress.emit(i, total)

        self.finished.emit(
            True, {"backup": backup_path, "total_steps": total},
        )
