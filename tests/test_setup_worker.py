import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from PyQt6.QtCore import QCoreApplication, QEventLoop


# A QCoreApplication must exist for QThread signal dispatch.
@pytest.fixture(scope="module", autouse=True)
def _qapp():
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    yield app


from setup_gui.setup_worker import SetupWorker, SETUP_STEPS


def _run_to_completion(worker, timeout_ms=5000):
    """Spin a QEventLoop until `worker` emits `finished`. Returns the
    payload tuple (success, payload_dict). A QTimer guard force-quits
    the loop after `timeout_ms` so a regressed worker that never emits
    finished can't hang the test runner forever."""
    from PyQt6.QtCore import QTimer

    loop = QEventLoop()
    captured = []

    def on_finished(success, payload):
        captured.append((success, payload))
        loop.quit()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)

    worker.finished.connect(on_finished)
    worker.start()
    loop.exec()
    timer.stop()
    worker.wait(timeout_ms)
    assert captured, "worker did not emit finished within timeout"
    return captured[0]


def _stub_all_scripts(monkeypatch, return_code=0):
    """Replace every script's main() with a MagicMock that returns
    `return_code`. Returns a list of the mocks, in step order, so
    tests can inspect call args."""
    mocks = []
    for _name, module_path in SETUP_STEPS:
        mock = MagicMock(return_value=return_code)
        monkeypatch.setattr(f"{module_path}.main", mock)
        mocks.append(mock)
    return mocks


def test_setup_steps_constant_lists_five_scripts():
    """The SETUP_STEPS constant is the canonical list of (display_name,
    module_path) tuples for the 5 setup scripts in execution order."""
    assert len(SETUP_STEPS) == 5
    names = [name for name, _path in SETUP_STEPS]
    assert names == [
        "create_supporting_tables",
        "add_long_lat_to_contacts",
        "backfill_enrollment_from_contacts",
        "backfill_authorization_from_contacts",
        "backfill_availability_from_hha",
    ]
    paths = [path for _name, path in SETUP_STEPS]
    for path in paths:
        assert path.startswith("scripts.")


def test_happy_path_runs_all_scripts_in_order(tmp_path, monkeypatch):
    """Backup succeeds, all 5 scripts return 0 — finished(True, ...)."""
    db_path = tmp_path / "members.accdb"
    db_path.write_bytes(b"fake-db-contents")

    mocks = _stub_all_scripts(monkeypatch, return_code=0)

    worker = SetupWorker(str(db_path))

    progress_events = []
    log_events = []
    worker.progress.connect(lambda d, t: progress_events.append((d, t)))
    worker.log_line.connect(log_events.append)

    success, payload = _run_to_completion(worker)

    assert success is True
    assert payload["backup"].endswith(".accdb")
    assert "step" not in payload
    # Each mock called exactly once, in order, with ["--db", db_path].
    for mock in mocks:
        mock.assert_called_once_with(["--db", str(db_path)])
    # Progress fires after each successful step.
    assert progress_events == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]
    # Backup file actually created on disk.
    assert Path(payload["backup"]).exists()
    # First log line should reference the backup.
    assert any("Backed up" in line for line in log_events)


def test_backup_filename_inserts_timestamp_before_extension(
    tmp_path, monkeypatch,
):
    """Backup filename is `<stem>.backup_<TS><ext>` — extension
    preserved at the very end so Access still opens it."""
    db_path = tmp_path / "members.accdb"
    db_path.write_bytes(b"fake")
    _stub_all_scripts(monkeypatch, return_code=0)

    worker = SetupWorker(str(db_path))
    success, payload = _run_to_completion(worker)

    assert success is True
    backup_name = Path(payload["backup"]).name
    assert backup_name.startswith("members.backup_")
    assert backup_name.endswith(".accdb")


def test_backup_failure_emits_finished_false_and_no_script_runs(
    tmp_path, monkeypatch,
):
    """If shutil.copy2 raises, finished(False, step='backup') and
    none of the script mocks are invoked."""
    db_path = tmp_path / "members.accdb"
    db_path.write_bytes(b"fake")

    mocks = _stub_all_scripts(monkeypatch, return_code=0)

    def raise_copy(_src, _dst):
        raise OSError("disk full")

    monkeypatch.setattr("setup_gui.setup_worker.shutil.copy2", raise_copy)

    worker = SetupWorker(str(db_path))
    success, payload = _run_to_completion(worker)

    assert success is False
    assert payload["step"] == "backup"
    assert "disk full" in payload["error"]
    for mock in mocks:
        mock.assert_not_called()


def test_mid_chain_failure_stops_remaining_steps(tmp_path, monkeypatch):
    """The 3rd script returns a non-zero rc; downstream steps NOT
    called; finished payload identifies the failing step."""
    db_path = tmp_path / "members.accdb"
    db_path.write_bytes(b"fake")

    mocks = []
    for i, (_name, module_path) in enumerate(SETUP_STEPS):
        rc = 2 if i == 2 else 0  # 3rd step fails.
        mock = MagicMock(return_value=rc)
        monkeypatch.setattr(f"{module_path}.main", mock)
        mocks.append(mock)

    worker = SetupWorker(str(db_path))
    success, payload = _run_to_completion(worker)

    assert success is False
    assert payload["step"] == "backfill_enrollment_from_contacts"
    assert "backup" in payload  # the backup path is still surfaced
    # Steps 1-3 ran; steps 4-5 did not.
    mocks[0].assert_called_once()
    mocks[1].assert_called_once()
    mocks[2].assert_called_once()
    mocks[3].assert_not_called()
    mocks[4].assert_not_called()


def test_exception_in_script_main_is_caught(tmp_path, monkeypatch):
    """If a script's main() raises (not just returns non-zero), the
    worker catches it and reports finished(False, ...) with the
    exception message instead of crashing the thread."""
    db_path = tmp_path / "members.accdb"
    db_path.write_bytes(b"fake")

    # First step raises; later steps would return 0 if they ran.
    for i, (_name, module_path) in enumerate(SETUP_STEPS):
        if i == 0:
            monkeypatch.setattr(
                f"{module_path}.main",
                MagicMock(side_effect=RuntimeError("pyodbc boom")),
            )
        else:
            monkeypatch.setattr(
                f"{module_path}.main", MagicMock(return_value=0),
            )

    worker = SetupWorker(str(db_path))
    success, payload = _run_to_completion(worker)

    assert success is False
    assert payload["step"] == "create_supporting_tables"
    assert "pyodbc boom" in payload["error"]


def test_script_stdout_streamed_through_log_line_signal(
    tmp_path, monkeypatch,
):
    """A script that does print() inside main() has each line of its
    output forwarded through the worker's log_line signal."""
    db_path = tmp_path / "members.accdb"
    db_path.write_bytes(b"fake")

    # All scripts: print one log line, return 0.
    def make_chatty(name):
        def fake_main(_argv):
            print(f"{name}: did the thing")
            return 0
        return fake_main

    for name, module_path in SETUP_STEPS:
        monkeypatch.setattr(f"{module_path}.main", make_chatty(name))

    worker = SetupWorker(str(db_path))
    log_events = []
    worker.log_line.connect(log_events.append)

    success, payload = _run_to_completion(worker)

    assert success is True
    # Each script's chatty line is somewhere in the log stream.
    for name, _ in SETUP_STEPS:
        assert any(
            f"{name}: did the thing" in line for line in log_events
        ), f"missing chatty line for {name}"
