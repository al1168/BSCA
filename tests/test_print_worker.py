import sys

import pytest

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer


@pytest.fixture(scope="module", autouse=True)
def _qapp():
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    yield app


from gui.print_worker import PrintWorker


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


def test_print_worker_reports_result_on_success(monkeypatch):
    def fake_print(paths, on_progress=None):
        for i, p in enumerate(paths, start=1):
            if on_progress:
                on_progress(i, len(paths), p)
        return {"printed": list(paths), "failed": [], "not_attempted": []}

    monkeypatch.setattr("gui.print_worker.print_workbooks", fake_print)

    worker = PrintWorker(["a.xlsx", "b.xlsx"])
    progress = []
    worker.progress.connect(lambda d, t: progress.append((d, t)))

    success, payload = _run_to_completion(worker)
    assert success is True
    assert payload["printed"] == ["a.xlsx", "b.xlsx"]
    assert payload["failed"] == []
    assert payload["not_attempted"] == []
    assert progress == [(1, 2), (2, 2)]


def test_print_worker_partial_failure_is_not_success(monkeypatch):
    def fake_print(paths, on_progress=None):
        return {"printed": ["a.xlsx"],
                "failed": [("b.xlsx", "printer offline")],
                "not_attempted": ["c.xlsx"]}

    monkeypatch.setattr("gui.print_worker.print_workbooks", fake_print)

    worker = PrintWorker(["a.xlsx", "b.xlsx", "c.xlsx"])
    success, payload = _run_to_completion(worker)
    assert success is False
    assert payload["printed"] == ["a.xlsx"]
    assert payload["failed"] == [("b.xlsx", "printer offline")]
    assert payload["not_attempted"] == ["c.xlsx"]


def test_print_worker_surfaces_errors(monkeypatch):
    def boom(paths, on_progress=None):
        raise RuntimeError("Excel not installed")

    monkeypatch.setattr("gui.print_worker.print_workbooks", boom)

    worker = PrintWorker(["a.xlsx"])
    success, payload = _run_to_completion(worker)
    assert success is False
    assert "Excel not installed" in payload["error"]
