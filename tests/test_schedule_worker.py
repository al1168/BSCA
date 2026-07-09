import sys
from datetime import date

import pytest

from PyQt6.QtCore import QCoreApplication, QEventLoop


# A QCoreApplication must exist for QThread signal dispatch.
@pytest.fixture(scope="module", autouse=True)
def _qapp():
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    yield app


from gui.worker import ScheduleWorker


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


def _stub_db_and_caches(monkeypatch, tmp_path):
    """Stub every DB/cache dependency of ScheduleWorker._run_inner so a
    run exercises only the failure-collection and CSV-writing path.
    `get_member` returns None, so the single member fails at lookup."""
    monkeypatch.setattr("gui.worker.get_member", lambda cid, db: None)
    for name in (
        "get_all_enrollments",
        "get_all_authorizations",
        "get_all_absences",
        "get_all_availability",
        "get_all_one_offs",
    ):
        monkeypatch.setattr(f"gui.worker.{name}", lambda db: {})
    monkeypatch.setattr("gui.worker.load_cache", lambda path: {})
    monkeypatch.setattr("gui.worker.save_cache", lambda path, cache: None)
    monkeypatch.setattr("gui.worker.load_time_cache", lambda path: {})
    monkeypatch.setattr(
        "gui.worker.save_time_cache", lambda path, cache: None
    )
    monkeypatch.setattr(
        "gui.worker.app_time_cache_path",
        lambda legacy_path=None: str(tmp_path / "time_cache.json"),
    )


def _make_worker(tmp_path):
    return ScheduleWorker(
        mode="single",
        center_id=24010,
        center_ids=None,
        plan_code=None,
        year=2026,
        month=5,
        out_dir=str(tmp_path),
        db_path="unused.accdb",
        google_api_key="K",
        geo_cache=str(tmp_path / "geo_cache.json"),
    )


def test_worker_warns_and_falls_back_when_skipped_csv_locked(
        monkeypatch, tmp_path):
    """When the primary skipped-members CSV is locked (e.g. open in
    Excel), the worker logs a fallback warning and writes the report
    under the `_1` name instead of dying with an unhandled error."""
    _stub_db_and_caches(monkeypatch, tmp_path)
    today = date.today().isoformat()
    (tmp_path / f"skipped_members_{today}.csv").mkdir()

    worker = _make_worker(tmp_path)
    log_events = []
    worker.log_line.connect(lambda key, args: log_events.append((key, args)))

    success, payload = _run_to_completion(worker)

    assert success is False
    assert "error_text" not in payload
    assert payload["failures"][0]["stage"] == "lookup"
    fallback = tmp_path / f"skipped_members_{today}_1.csv"
    assert fallback.exists()
    assert ("worker.skipped_csv_fallback", {
        "primary": f"skipped_members_{today}.csv",
        "filename": f"skipped_members_{today}_1.csv",
    }) in log_events
    assert ("worker.wrote_skipped_csv", {
        "filename": f"skipped_members_{today}_1.csv",
    }) in log_events


def test_worker_warns_when_skipped_csv_unwritable(monkeypatch, tmp_path):
    """When every candidate CSV name is locked, the worker logs a
    warning and still finishes with the normal summary payload instead
    of surfacing an unhandled-error crash."""
    _stub_db_and_caches(monkeypatch, tmp_path)
    today = date.today().isoformat()
    (tmp_path / f"skipped_members_{today}.csv").mkdir()
    for n in range(1, 10):
        (tmp_path / f"skipped_members_{today}_{n}.csv").mkdir()

    worker = _make_worker(tmp_path)
    log_events = []
    worker.log_line.connect(lambda key, args: log_events.append((key, args)))

    success, payload = _run_to_completion(worker)

    assert success is False
    assert "error_text" not in payload
    assert payload["failures"][0]["stage"] == "lookup"
    assert any(
        key == "worker.skipped_csv_failed" for key, _args in log_events
    )
    assert not any(
        key == "worker.wrote_skipped_csv" for key, _args in log_events
    )
