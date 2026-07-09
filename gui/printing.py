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


def print_workbooks(paths, excel=None, on_printed=None):
    """Print each existing `.xlsx` in `paths` to the default printer.

    `excel` is an Excel.Application COM object; when None a hidden Excel
    instance is created and quit at the end (when provided, the caller
    owns its lifecycle — used by tests). `on_printed(index, total,
    path)` is called after each file for progress reporting. Returns the
    number of files printed."""
    files = printable_schedules(paths)
    if not files:
        return 0
    owns_excel = excel is None
    if owns_excel:
        excel = _make_excel()
    printed = 0
    total = len(files)
    try:
        for i, path in enumerate(files, start=1):
            wb = excel.Workbooks.Open(os.path.abspath(path))
            try:
                wb.PrintOut()          # -> default printer
            finally:
                wb.Close(False)        # discard (never modified)
            printed += 1
            if on_printed is not None:
                on_printed(i, total, path)
    finally:
        if owns_excel:
            excel.Quit()
    return printed
