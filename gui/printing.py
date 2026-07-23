"""Print generated schedule workbooks to the default Windows printer.

Schedules are .xlsx files, so we drive Microsoft Excel via COM
(win32com) to open each workbook and PrintOut() it to the default
printer. Debug/skipped `.csv` files are never printed — only existing
`.xlsx` paths are considered.

The core `print_workbooks` accepts an injected Excel COM object so it
can be unit-tested with a mock; the GUI runs it on a background thread
(see gui/print_worker.py).
"""

import os
import time


def printable_schedules(paths):
    """Return the subset of `paths` that are existing `.xlsx` files.
    Drops `.csv` (debug/skipped) files and any path that no longer
    exists, preserving order."""
    out = []
    for p in paths:
        if p.lower().endswith(".xlsx") and os.path.isfile(p):
            out.append(p)
    return out


def default_printer_name():
    """Name of the current default Windows printer, or None when it
    can't be determined (non-Windows, pywin32 missing, or no printer)."""
    try:
        import win32print
    except ImportError:
        return None
    try:
        return win32print.GetDefaultPrinter()
    except Exception:
        return None


def _make_excel():
    """Create a hidden Excel.Application COM object. Raises RuntimeError
    with a friendly message when Excel or pywin32 is unavailable."""
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError(
            "pywin32 is not installed, so schedules can't be printed. "
            f"Original error: {exc}"
        )
    try:
        excel = win32com.client.Dispatch("Excel.Application")
    except Exception as exc:
        raise RuntimeError(
            "Could not start Microsoft Excel. Excel must be installed "
            f"to print schedules. Original error: {exc}"
        )
    excel.Visible = False
    excel.DisplayAlerts = False
    return excel


def partition_printed(paths, printed_ok):
    """Split `paths` into (remaining, already) by whether each file's
    absolute path is in `printed_ok` (the set of files successfully
    printed earlier this session). Order preserved."""
    remaining, already = [], []
    for p in paths:
        if os.path.abspath(p) in printed_ok:
            already.append(p)
        else:
            remaining.append(p)
    return remaining, already


# Stop the batch once this many files fail back-to-back: the printer is
# clearly down and each further attempt just burns time on a COM error.
# A single success resets the streak.
MAX_CONSECUTIVE_FAILURES = 3

# Queue throttle: never let more than this many jobs pile up in the
# Windows print queue (a backed-up spooler is the state that makes
# Excel throw its misleading "No printers are installed" error).
MAX_QUEUED_JOBS = 10
QUEUE_POLL_SECONDS = 2.0
# While waiting for room, if the queue length hasn't decreased for this
# long the printer is stalled (out of paper / offline) — stop cleanly.
QUEUE_STALL_TIMEOUT = 120.0


def _default_queue_len():
    """Number of jobs currently in the default printer's Windows queue,
    or None when it can't be determined (no pywin32, no default printer,
    spooler unreachable). None disables throttling."""
    try:
        import win32print
    except ImportError:
        return None
    try:
        name = win32print.GetDefaultPrinter()
        handle = win32print.OpenPrinter(name)
        try:
            return len(win32print.EnumJobs(handle, 0, 9999, 1))
        finally:
            win32print.ClosePrinter(handle)
    except Exception:
        return None


def _wait_for_queue_room(queue_len, sleep, monotonic):
    """Poll until the print queue drops below MAX_QUEUED_JOBS. Returns
    False when the queue makes no progress for QUEUE_STALL_TIMEOUT
    (printer stalled), True when there's room (or the length is
    unknowable, in which case throttling is skipped)."""
    last_len = None
    last_progress = monotonic()
    while True:
        n = queue_len()
        if n is None or n < MAX_QUEUED_JOBS:
            return True
        if last_len is None or n < last_len:
            last_len = n
            last_progress = monotonic()
        elif monotonic() - last_progress >= QUEUE_STALL_TIMEOUT:
            return False
        sleep(QUEUE_POLL_SECONDS)


def print_workbooks(paths, excel=None, on_progress=None,
                    queue_len=_default_queue_len,
                    sleep=time.sleep, monotonic=time.monotonic):
    """Print each existing `.xlsx` in `paths` to the default printer.

    `excel` is an Excel.Application COM object; when None a hidden Excel
    instance is created and quit at the end (when provided, the caller
    owns its lifecycle — used by tests). `on_progress(index, total,
    path)` is called after each ATTEMPT — success or failure — so
    progress reporting always advances.

    A failure on one file does not abort the batch (a paper-out midway
    must not strand the rest); after MAX_CONSECUTIVE_FAILURES straight
    failures the remaining files are skipped instead of grinding out
    one COM error each.

    `queue_len` (callable → int or None) throttles submission: before
    each file, wait while the Windows queue holds MAX_QUEUED_JOBS or
    more, and stop cleanly ("stalled") when the queue makes no progress
    for QUEUE_STALL_TIMEOUT. Pass None to disable. `sleep`/`monotonic`
    are injectable time sources for tests. Returns a dict:
      "printed"        — paths sent to the printer, in order
      "failed"         — (path, error message) per failed attempt
      "not_attempted"  — paths skipped (failure streak or stall)
      "stalled"        — True when the queue stopped draining
    """
    result = {"printed": [], "failed": [], "not_attempted": [],
              "stalled": False}
    files = printable_schedules(paths)
    if not files:
        return result
    owns_excel = excel is None
    if owns_excel:
        excel = _make_excel()
    total = len(files)
    consecutive = 0
    try:
        for i, path in enumerate(files, start=1):
            if queue_len is not None and not _wait_for_queue_room(
                    queue_len, sleep, monotonic):
                result["stalled"] = True
                result["not_attempted"] = files[i - 1:]
                break
            try:
                wb = excel.Workbooks.Open(os.path.abspath(path))
                try:
                    wb.PrintOut()          # -> default printer
                finally:
                    wb.Close(False)        # discard (never modified)
            except Exception as exc:  # noqa: BLE001 - per-file, reported
                result["failed"].append((path, str(exc)))
                consecutive += 1
            else:
                result["printed"].append(path)
                consecutive = 0
            if on_progress is not None:
                on_progress(i, total, path)
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                result["not_attempted"] = files[i:]
                break
    finally:
        if owns_excel:
            excel.Quit()
    return result
