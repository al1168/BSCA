# BSCA Setup GUI

Status: Draft
Date: 2026-06-09

## Goal

A second standalone GUI executable (`dist/BSCASetup.exe`) that runs the five database-preparation scripts in order against an operator-selected `.accdb`, with an automatic backup beforehand. Used to set up a fresh database on a new machine in one click instead of five command-line invocations.

## Motivation

Today the operator has to run five Python scripts in the right order with the right `--db` flag whenever they set up a new database, and they have to remember to `cp` the `.accdb` to a backup first. That's six command-line invocations for what is conceptually one action ("prep this DB"). On a new computer without Python installed, they can't do it at all. A single packaged exe with a file-picker + Run button removes both problems.

## Scope

In scope:

- New top-level directory `setup_gui/` mirroring the existing `gui/` layout in shape but independent in content (no shared code).
- New entry point `setup.py` (sibling of `gui.py`) and PyInstaller spec `BSCASetup.spec` (sibling of `MonthlyScheduleGenerator.spec`).
- A single-window PyQt6 GUI: DB file picker, "Run Setup" button, progress bar, scrolling log area.
- Background `SetupWorker(QThread)` that copies the DB to a timestamped backup, then imports each of the five script modules and calls their `main(argv)` with `--db <path>` argv. Captures `stdout` via a line-buffered helper, forwards each line to the log through a Qt signal.
- Tests for the line-buffered helper and for the worker's chain-runner logic (using monkey-patched script modules).
- A new PyInstaller spec; both exes ship together in `dist/`.

Out of scope:

- `terminate_long_id_enrollments` (destructive cleanup, run separately when needed).
- Multi-language support (English only — operator tool, not for end users).
- Persistent settings (one-time-per-DB tool; no need to remember the path).
- Per-script flag toggles (`--exclude-test-members`, `--dry-run`, `--quiet`). Defaults only.
- Re-running individual steps. If a step fails, the operator restores the backup and starts over.
- Sharing UI code with the scheduler GUI (`gui/`). Setup is small enough that copy-paste of the few widgets we need is simpler than refactoring shared base classes.

## Design

### Module layout

```
setup_gui/
  __init__.py        # empty
  main_window.py     # QWidget with the layout shown below
  setup_worker.py    # QThread that backs up + chains the 5 scripts
  log_buffer.py      # Line-buffered file-like that fires a callback per complete line
setup.py             # entry point
BSCASetup.spec       # PyInstaller spec
tests/
  test_setup_log_buffer.py
  test_setup_worker.py
```

### UI

A single window, fixed-ish width, English only:

```
┌────────────────────────────────────────────┐
│ BSCA Setup                                 │
├────────────────────────────────────────────┤
│ Database File:                             │
│ [path text field             ] [Browse...] │
│                                            │
│ [         Run Setup           ]            │
│                                            │
│ Progress: ━━━━━━━━━━━━░░░░  3 of 5         │
│                                            │
│ ┌────────────────────────────────────────┐ │
│ │ [scrolling log area]                   │ │
│ │ Backed up to members.backup_2026-06... │ │
│ │ Step 1/5: create_supporting_tables     │ │
│ │   Created: Enrollment, Authorization,..│ │
│ │ Step 2/5: add_long_lat_to_contacts     │ │
│ │ ...                                    │ │
│ └────────────────────────────────────────┘ │
└────────────────────────────────────────────┘
```

Widgets: `QLineEdit` + Browse `QPushButton` (file picker — `.accdb`/`.mdb` filter), `QPushButton` "Run Setup" (disabled while a run is in flight), `QProgressBar` with range `(0, 5)`, `QPlainTextEdit` for the log.

### Backend approach

Each of the five scripts already exposes `main(argv: list[str] | None = None) -> int`. The setup worker imports them as Python modules and calls their `main([...])` directly. No subprocess. Benefits:

- Works seamlessly in a PyInstaller-packaged exe (the scripts ship inside the bundle; no need to find external `.py` files).
- Easier to test (we can monkey-patch the imported `main` functions in unit tests).
- Easier to capture stdout (one process, one redirect).

### Step sequence

| # | Step | Action |
|---|---|---|
| 0 | backup | `shutil.copy2(db, <stem>.backup_<YYYY-MM-DD-HHMMSS><ext>)` in the same folder — e.g. `members.accdb` → `members.backup_2026-06-09-145632.accdb`. Extension preserved so Access still opens the backup if double-clicked. |
| 1 | `create_supporting_tables` | `main(["--db", db])` |
| 2 | `add_long_lat_to_contacts` | `main(["--db", db])` |
| 3 | `backfill_enrollment_from_contacts` | `main(["--db", db])` |
| 4 | `backfill_authorization_from_contacts` | `main(["--db", db])` |
| 5 | `backfill_availability_from_hha` | `main(["--db", db])` |

Step 0 always runs first; steps 1–5 only run if the previous one returned 0. The progress bar advances after each successful step.

### Line-buffered stdout capture

`setup_gui/log_buffer.py` defines:

```python
class LineBuffer:
    """File-like object that buffers writes until a newline arrives,
    then fires `on_line(line_text)` for each complete line. Final
    partial-line on close fires too. Used inside contextlib.redirect_stdout
    so each script's print() output streams to the log in real time."""
    def __init__(self, on_line: Callable[[str], None]):
        ...
    def write(self, s: str) -> int: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...  # flushes any trailing partial line
```

The worker wraps each script invocation in:

```python
buf = LineBuffer(self._emit_log_line)
with contextlib.redirect_stdout(buf):
    rc = module.main(["--db", db])
buf.flush()
```

`_emit_log_line` is a Qt signal emit on the worker; the main window's slot appends it to `QPlainTextEdit`.

### `SetupWorker(QThread)` shape

```python
class SetupWorker(QThread):
    log_line = pyqtSignal(str)            # one complete line of output
    progress = pyqtSignal(int, int)        # (done_step, total_steps=5)
    finished = pyqtSignal(bool, dict)     # (success, payload)

    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = db_path

    def run(self):
        try:
            backup_path = self._make_backup()
        except OSError as exc:
            self.finished.emit(False, {"error": str(exc), "step": "backup"})
            return
        self.log_line.emit(f"Backed up to {backup_path}")
        steps = [
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
        for i, (name, module_path) in enumerate(steps, start=1):
            self.log_line.emit(f"Step {i}/5: {name}")
            try:
                module = importlib.import_module(module_path)
                buf = LineBuffer(self.log_line.emit)
                with contextlib.redirect_stdout(buf):
                    rc = module.main(["--db", self._db_path])
                buf.flush()
            except Exception as exc:
                self.finished.emit(
                    False,
                    {"error": str(exc), "step": name, "backup": backup_path},
                )
                return
            if rc != 0:
                self.finished.emit(
                    False,
                    {"error": f"step returned {rc}", "step": name,
                     "backup": backup_path},
                )
                return
            self.progress.emit(i, 5)
        self.finished.emit(True, {"backup": backup_path})
```

### Error handling

- **File picker yields a path that doesn't exist** → Browse button validates; Run Setup is disabled until a valid file is picked. Optional additional check on click.
- **Backup fails** (source locked by Excel, etc.) → error dialog: "Could not back up the database: \<error\>. Setup did not run." No script invoked.
- **Script returns non-zero or raises** → worker stops, log captures the error, main window shows a warning dialog: "Setup failed at step \<name\>. The original database may be partially modified. To restore, copy `<backup_path>` over the original."
- **Re-run on already-set-up DB** → safe. Every script we're chaining is idempotent: `create_supporting_tables` skips existing tables, `add_long_lat_to_contacts` skips the existing column, the three backfill scripts skip members that already have rows.

### `setup.py` (entry point)

Mirrors `gui.py` in spirit:

```python
import sys
from PyQt6.QtWidgets import QApplication
from setup_gui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
```

### `BSCASetup.spec`

A copy of `MonthlyScheduleGenerator.spec` with two changes:

- `Analysis(['setup.py'], ...)` instead of `['gui.py']`.
- `EXE(... name='BSCASetup', ...)` instead of `name='MonthlyScheduleGenerator'`.

`hiddenimports=['pyodbc', 'openpyxl', 'requests']` stays the same (the scripts import pyodbc; openpyxl and requests are unused here but harmless to bundle — keeping them matches the scheduler spec for consistency).

Build command: `.venv/Scripts/pyinstaller.exe BSCASetup.spec` produces `dist/BSCASetup.exe`. Both exes coexist in `dist/`.

## Testing

- `tests/test_setup_log_buffer.py`:
  - Writing without a newline buffers, fires no callback.
  - Writing with a newline fires the callback with the line content (no trailing `\n`).
  - Multi-line writes fire the callback once per complete line.
  - Partial trailing line is flushed on close()/flush().
- `tests/test_setup_worker.py`:
  - Backup-only success path (mocked scripts all return 0): verifies `log_line`, `progress`, `finished(True, ...)` events.
  - Backup failure: verifies `finished(False, {"step": "backup", ...})`, no script ever called.
  - Mid-chain failure (3rd script returns 2): verifies `finished(False, {"step": "backfill_enrollment_from_contacts", ...})`, downstream scripts not called.
  - Call order: scripts are invoked in the exact order listed.
  - Argv shape: each script's `main` receives `["--db", <path>]`.
- Manual verification: launch `dist/BSCASetup.exe`, point at a fresh copy of `members.accdb`, confirm the backup file appears and all 5 steps complete in order with sensible log output.
