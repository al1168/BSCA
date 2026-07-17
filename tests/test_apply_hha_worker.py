import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer


# A QCoreApplication must exist for QThread signal dispatch.
@pytest.fixture(scope="module", autouse=True)
def _qapp():
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    yield app


from apply_hha_gui.worker import ApplyHhaWorker


def _run_to_completion(worker, timeout_ms=5000):
    """Spin a QEventLoop until `worker` emits `finished_run`."""
    loop = QEventLoop()
    captured = []

    def on_finished(success, payload):
        captured.append((success, payload))
        loop.quit()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)

    worker.finished_run.connect(on_finished)
    worker.start()
    loop.exec()
    timer.stop()
    worker.wait(timeout_ms)
    assert captured, "worker did not emit finished_run within timeout"
    return captured[0]


@pytest.fixture
def paths(tmp_path):
    csv_path = tmp_path / "answers.csv"
    csv_path.write_text("center_id,answer\n", encoding="utf-8-sig")
    db_path = tmp_path / "members.accdb"
    db_path.write_bytes(b"fake-db")
    return str(csv_path), str(db_path)


def test_preview_passes_dry_run_and_makes_no_backup(
    paths, tmp_path, monkeypatch,
):
    csv_path, db_path = paths
    mock = MagicMock(return_value=0)
    monkeypatch.setattr("scripts.apply_hha_answers.main", mock)

    worker = ApplyHhaWorker(csv_path, db_path, mode="preview")
    success, payload = _run_to_completion(worker)

    assert success is True
    assert payload["mode"] == "preview"
    assert "backup" not in payload
    mock.assert_called_once_with(
        ["--csv", csv_path, "--db", db_path, "--dry-run"]
    )
    assert list(tmp_path.glob("*.backup_*")) == []


def test_apply_backs_up_before_running_without_dry_run(
    paths, tmp_path, monkeypatch,
):
    csv_path, db_path = paths
    backups_seen_at_call_time = []

    def fake_main(argv):
        backups_seen_at_call_time.append(
            len(list(tmp_path.glob("members.backup_*.accdb")))
        )
        return 0

    monkeypatch.setattr("scripts.apply_hha_answers.main", fake_main)

    worker = ApplyHhaWorker(csv_path, db_path, mode="apply")
    log_lines = []
    worker.log_line.connect(log_lines.append)
    success, payload = _run_to_completion(worker)

    assert success is True
    assert payload["mode"] == "apply"
    assert Path(payload["backup"]).exists()
    assert Path(payload["backup"]).name.startswith("members.backup_")
    assert Path(payload["backup"]).name.endswith(".accdb")
    # The backup existed by the time the script ran.
    assert backups_seen_at_call_time == [1]
    assert any("Backed up to" in line for line in log_lines)


def test_apply_backup_failure_short_circuits(paths, monkeypatch):
    csv_path, db_path = paths
    mock = MagicMock(return_value=0)
    monkeypatch.setattr("scripts.apply_hha_answers.main", mock)

    def raise_copy(_src, _dst):
        raise OSError("locked by Access")

    monkeypatch.setattr("apply_hha_gui.worker.shutil.copy2", raise_copy)

    worker = ApplyHhaWorker(csv_path, db_path, mode="apply")
    success, payload = _run_to_completion(worker)

    assert success is False
    assert payload["step"] == "backup"
    assert "locked by Access" in payload["error"]
    mock.assert_not_called()


def test_nonzero_return_code_reports_failure(paths, monkeypatch):
    csv_path, db_path = paths
    monkeypatch.setattr(
        "scripts.apply_hha_answers.main", MagicMock(return_value=2),
    )

    worker = ApplyHhaWorker(csv_path, db_path, mode="preview")
    success, payload = _run_to_completion(worker)

    assert success is False
    assert payload["step"] == "run"
    assert "exit code 2" in payload["error"]


def test_exception_in_main_is_caught(paths, monkeypatch):
    csv_path, db_path = paths
    monkeypatch.setattr(
        "scripts.apply_hha_answers.main",
        MagicMock(side_effect=RuntimeError("pyodbc boom")),
    )

    worker = ApplyHhaWorker(csv_path, db_path, mode="apply")
    success, payload = _run_to_completion(worker)

    assert success is False
    assert payload["step"] == "run"
    assert "pyodbc boom" in payload["error"]


def test_stdout_is_streamed_through_log_line(paths, monkeypatch):
    csv_path, db_path = paths

    def chatty_main(argv):
        print("  25023 day 7: 08:00-13:00 -> 08:00-12:00")
        print("Apply HHA answers summary")
        return 0

    monkeypatch.setattr("scripts.apply_hha_answers.main", chatty_main)

    worker = ApplyHhaWorker(csv_path, db_path, mode="preview")
    log_lines = []
    worker.log_line.connect(log_lines.append)
    success, _ = _run_to_completion(worker)

    assert success is True
    assert any("25023 day 7" in line for line in log_lines)
    assert any("summary" in line for line in log_lines)
