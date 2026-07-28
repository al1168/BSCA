import sys

import pytest

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer


@pytest.fixture(scope="module", autouse=True)
def _qapp():
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    yield app


from gui.counts_worker import CountsWorker


def _run_to_completion(worker, timeout_ms=5000):
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


def test_counts_worker_passes_month_bounds(monkeypatch):
    seen = {}

    def fake_counts(db_path, month_start, month_end):
        seen["args"] = (db_path, month_start, month_end)
        return {"plans": {}, "total_active": 0}

    monkeypatch.setattr(
        "gui.counts_worker.get_plan_member_counts", fake_counts
    )
    worker = CountsWorker("some.accdb", 2024, 2)   # Feb 2024 (leap year)
    success, payload = _run_to_completion(worker)
    assert success is True
    assert payload == {"plans": {}, "total_active": 0}
    import datetime
    assert seen["args"] == (
        "some.accdb",
        datetime.date(2024, 2, 1),
        datetime.date(2024, 2, 29),
    )


def test_counts_worker_surfaces_errors(monkeypatch):
    def boom(db_path, month_start, month_end):
        raise RuntimeError("no driver")

    monkeypatch.setattr("gui.counts_worker.get_plan_member_counts", boom)
    worker = CountsWorker("some.accdb", 2026, 7)
    success, payload = _run_to_completion(worker)
    assert success is False
    assert "no driver" in payload["error"]
