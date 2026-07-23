from unittest.mock import MagicMock

from gui import printing


def test_printable_schedules_keeps_only_existing_xlsx(tmp_path):
    xlsx1 = tmp_path / "Schedule_1_2026-07.xlsx"
    xlsx1.write_bytes(b"x")
    xlsx2 = tmp_path / "Schedule_2_2026-07.xlsx"
    xlsx2.write_bytes(b"x")
    csv = tmp_path / "Debug_1_2026-07.csv"
    csv.write_text("a,b\n")
    missing = tmp_path / "gone.xlsx"

    out = printing.printable_schedules([
        str(xlsx1), str(csv), str(missing), str(xlsx2),
    ])
    assert out == [str(xlsx1), str(xlsx2)]   # .csv and missing dropped


def _files(tmp_path, n):
    paths = []
    for i in range(1, n + 1):
        p = tmp_path / f"Schedule_{i}_2026-07.xlsx"
        p.write_bytes(b"x")
        paths.append(str(p))
    return paths


def test_print_workbooks_no_files_returns_empty_result():
    excel = MagicMock()
    result = printing.print_workbooks([], excel=excel, queue_len=None)
    assert result == {"printed": [], "failed": [],
                      "not_attempted": [], "stalled": False}
    excel.Workbooks.Open.assert_not_called()


def test_print_workbooks_prints_each_via_excel(tmp_path):
    a, b = _files(tmp_path, 2)
    excel = MagicMock()
    wb = MagicMock()
    excel.Workbooks.Open.return_value = wb

    progress = []
    result = printing.print_workbooks(
        [a, b], excel=excel, queue_len=None,
        on_progress=lambda i, total, p: progress.append((i, total)),
    )

    assert result["printed"] == [a, b]
    assert result["failed"] == []
    assert result["not_attempted"] == []
    # Each file was opened, printed to the default printer, and closed.
    assert wb.PrintOut.call_count == 2
    assert wb.Close.call_count == 2
    assert progress == [(1, 2), (2, 2)]
    # Injected Excel is not quit by the caller (caller owns it).
    excel.Quit.assert_not_called()


def test_print_workbooks_continues_past_a_failed_file(tmp_path):
    # File 1 fails, file 2 still prints — one bad file must not abort
    # the batch (the 2026-07 paper-out incident).
    a, b = _files(tmp_path, 2)
    excel = MagicMock()
    wb = MagicMock()
    excel.Workbooks.Open.return_value = wb
    wb.PrintOut.side_effect = [RuntimeError("printer offline"), None]

    progress = []
    result = printing.print_workbooks(
        [a, b], excel=excel, queue_len=None,
        on_progress=lambda i, total, p: progress.append((i, total)),
    )

    assert result["printed"] == [b]
    assert [p for p, _err in result["failed"]] == [a]
    assert "printer offline" in result["failed"][0][1]
    assert result["not_attempted"] == []
    # Progress advanced for BOTH attempts, including the failed one.
    assert progress == [(1, 2), (2, 2)]


def test_print_workbooks_stops_after_three_consecutive_failures(tmp_path):
    # Printer clearly down: after 3 consecutive failures the rest are
    # reported as not_attempted instead of grinding out errors.
    paths = _files(tmp_path, 5)
    excel = MagicMock()
    wb = MagicMock()
    excel.Workbooks.Open.return_value = wb
    wb.PrintOut.side_effect = RuntimeError("no printers are installed")

    result = printing.print_workbooks(paths, excel=excel, queue_len=None)

    assert result["printed"] == []
    assert [p for p, _err in result["failed"]] == paths[:3]
    assert result["not_attempted"] == paths[3:]
    assert wb.PrintOut.call_count == 3


def test_print_workbooks_success_resets_failure_streak(tmp_path):
    # fail, fail, success, fail, fail, success — never 3 consecutive,
    # so every file is attempted.
    paths = _files(tmp_path, 6)
    excel = MagicMock()
    wb = MagicMock()
    excel.Workbooks.Open.return_value = wb
    wb.PrintOut.side_effect = [
        RuntimeError("jam"), RuntimeError("jam"), None,
        RuntimeError("jam"), RuntimeError("jam"), None,
    ]

    result = printing.print_workbooks(paths, excel=excel, queue_len=None)

    assert result["printed"] == [paths[2], paths[5]]
    assert len(result["failed"]) == 4
    assert result["not_attempted"] == []
    assert wb.PrintOut.call_count == 6


def test_print_workbooks_closes_workbook_even_if_printout_raises(tmp_path):
    (a,) = _files(tmp_path, 1)
    excel = MagicMock()
    wb = MagicMock()
    wb.PrintOut.side_effect = RuntimeError("printer offline")
    excel.Workbooks.Open.return_value = wb

    result = printing.print_workbooks([a], excel=excel, queue_len=None)
    wb.Close.assert_called_once_with(False)
    assert [p for p, _err in result["failed"]] == [a]


def test_print_workbooks_open_failure_is_a_file_failure(tmp_path):
    # Workbooks.Open itself failing (corrupt file, Excel hiccup) is a
    # per-file failure, not a batch abort.
    a, b = _files(tmp_path, 2)
    excel = MagicMock()
    wb = MagicMock()
    excel.Workbooks.Open.side_effect = [RuntimeError("cannot open"), wb]

    result = printing.print_workbooks([a, b], excel=excel, queue_len=None)
    assert result["printed"] == [b]
    assert [p for p, _err in result["failed"]] == [a]


def test_partition_printed_splits_by_abspath(tmp_path):
    a, b, c = _files(tmp_path, 3)
    import os
    printed_ok = {os.path.abspath(b)}
    remaining, already = printing.partition_printed([a, b, c], printed_ok)
    assert remaining == [a, c]
    assert already == [b]


def test_partition_printed_empty_record_keeps_all():
    remaining, already = printing.partition_printed(["x.xlsx"], set())
    assert remaining == ["x.xlsx"]
    assert already == []


class _FakeClock:
    """Injectable time source: sleep() advances the clock."""

    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def test_print_workbooks_waits_for_queue_room(tmp_path):
    # Queue full (>= cap) twice, then drains — both files print, with
    # two poll sleeps in between. The user's hypothesis from 2026-07:
    # don't dump the whole batch into a backed-up spooler.
    a, b = _files(tmp_path, 2)
    excel = MagicMock()
    wb = MagicMock()
    excel.Workbooks.Open.return_value = wb
    clock = _FakeClock()
    qlens = iter([10, 12, 3, 0])

    result = printing.print_workbooks(
        [a, b], excel=excel,
        queue_len=lambda: next(qlens),
        sleep=clock.sleep, monotonic=clock.monotonic,
    )

    assert result["printed"] == [a, b]
    assert result["stalled"] is False
    assert clock.sleeps == [printing.QUEUE_POLL_SECONDS] * 2


def test_print_workbooks_stops_when_queue_stalls(tmp_path):
    # Queue pinned at the cap and never draining (paper out): after
    # QUEUE_STALL_TIMEOUT without progress, stop cleanly — nothing is
    # attempted, no Excel error, stalled flag set for the UI.
    paths = _files(tmp_path, 3)
    excel = MagicMock()
    wb = MagicMock()
    excel.Workbooks.Open.return_value = wb
    clock = _FakeClock()

    result = printing.print_workbooks(
        paths, excel=excel,
        queue_len=lambda: 10,
        sleep=clock.sleep, monotonic=clock.monotonic,
    )

    assert result["stalled"] is True
    assert result["printed"] == []
    assert result["not_attempted"] == paths
    wb.PrintOut.assert_not_called()
    assert clock.t >= printing.QUEUE_STALL_TIMEOUT


def test_print_workbooks_stall_mid_batch_keeps_earlier_prints(tmp_path):
    # First file goes through while the queue has room; then the queue
    # jams permanently — remaining files land in not_attempted.
    paths = _files(tmp_path, 3)
    excel = MagicMock()
    wb = MagicMock()
    excel.Workbooks.Open.return_value = wb
    clock = _FakeClock()
    state = {"calls": 0}

    def qlen():
        state["calls"] += 1
        return 0 if state["calls"] == 1 else 10

    result = printing.print_workbooks(
        paths, excel=excel, queue_len=qlen,
        sleep=clock.sleep, monotonic=clock.monotonic,
    )

    assert result["printed"] == [paths[0]]
    assert result["not_attempted"] == paths[1:]
    assert result["stalled"] is True
    assert wb.PrintOut.call_count == 1


def test_print_workbooks_unknown_queue_length_skips_throttle(tmp_path):
    # Probe can't tell (no pywin32 / spooler unreachable) — print
    # exactly as before, no waiting.
    a, b = _files(tmp_path, 2)
    excel = MagicMock()
    wb = MagicMock()
    excel.Workbooks.Open.return_value = wb
    clock = _FakeClock()

    result = printing.print_workbooks(
        [a, b], excel=excel,
        queue_len=lambda: None,
        sleep=clock.sleep, monotonic=clock.monotonic,
    )

    assert result["printed"] == [a, b]
    assert clock.sleeps == []
