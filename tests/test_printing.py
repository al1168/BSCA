from unittest.mock import MagicMock, call

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


def test_print_workbooks_no_files_returns_zero():
    excel = MagicMock()
    assert printing.print_workbooks([], excel=excel) == 0
    excel.Workbooks.Open.assert_not_called()


def test_print_workbooks_prints_each_via_excel(tmp_path):
    a = tmp_path / "Schedule_1_2026-07.xlsx"
    a.write_bytes(b"x")
    b = tmp_path / "Schedule_2_2026-07.xlsx"
    b.write_bytes(b"x")

    excel = MagicMock()
    wb = MagicMock()
    excel.Workbooks.Open.return_value = wb

    progress = []
    printed = printing.print_workbooks(
        [str(a), str(b)], excel=excel,
        on_printed=lambda i, total, p: progress.append((i, total)),
    )

    assert printed == 2
    # Each file was opened, printed to the default printer, and closed.
    assert wb.PrintOut.call_count == 2
    assert wb.Close.call_count == 2
    assert progress == [(1, 2), (2, 2)]
    # Injected Excel is not quit by the caller (caller owns it).
    excel.Quit.assert_not_called()


def test_print_workbooks_closes_workbook_even_if_printout_raises(tmp_path):
    a = tmp_path / "Schedule_1_2026-07.xlsx"
    a.write_bytes(b"x")
    excel = MagicMock()
    wb = MagicMock()
    wb.PrintOut.side_effect = RuntimeError("printer offline")
    excel.Workbooks.Open.return_value = wb

    try:
        printing.print_workbooks([str(a)], excel=excel)
    except RuntimeError:
        pass
    wb.Close.assert_called_once_with(False)
