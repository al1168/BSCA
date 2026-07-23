"""Background thread that prints generated schedules via Excel COM.

Runs gui.printing.print_workbooks off the GUI thread so printing many
workbooks doesn't freeze the UI. COM must be initialised on the thread
that uses it, hence the CoInitialize/CoUninitialize bracket.
"""

from PyQt6.QtCore import QThread, pyqtSignal

from gui.printing import print_workbooks


class PrintWorker(QThread):
    progress = pyqtSignal(int, int)        # (done, total)
    finished = pyqtSignal(bool, dict)      # (success, payload)

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self._paths = list(paths)

    def run(self):
        pythoncom = None
        try:
            import pythoncom as _pythoncom
            pythoncom = _pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pythoncom = None  # non-Windows / pywin32 missing → let it fail below
        try:
            result = print_workbooks(
                self._paths,
                on_progress=lambda i, total, _p: self.progress.emit(i, total),
            )
            # Success only when every file actually went to the printer;
            # partial failures carry the full result for the UI to show.
            success = not result["failed"] and not result["not_attempted"]
            self.finished.emit(success, result)
        except Exception as exc:  # noqa: BLE001 - surface, never crash the thread
            self.finished.emit(False, {"error": str(exc)})
        finally:
            if pythoncom is not None:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
