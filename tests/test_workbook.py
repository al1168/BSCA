from datetime import date, datetime

from openpyxl import load_workbook

from monthly_schedule.workbook import build_workbook, COMPANY_NAME

MEMBER = {
    "center_id": 24010,
    "last_name": "Cheng",
    "first_name": "Lizhu",
    "health_plan": "HOF",
}

ROWS = [
    {
        "date": date(2026, 5, 1), "day": "Fri",
        "pickup": "08:05", "arrival": "08:15", "time_in": "08:17",
        "time_out": "12:13", "departure": "12:15", "dropoff": "12:25",
    },
    {
        "date": date(2026, 5, 2), "day": "Sat",
        "pickup": "", "arrival": "", "time_in": "",
        "time_out": "", "departure": "", "dropoff": "",
    },
]


def test_side_by_side_workbook_structure(tmp_path):
    out = tmp_path / "sched.xlsx"
    build_workbook(MEMBER, ROWS, str(out))
    assert out.exists()

    wb = load_workbook(str(out))
    ws = wb["Schedule"]

    # per-block header: left block at col A, right block at col F
    assert ws["A1"].value == COMPANY_NAME
    assert ws["F1"].value == COMPANY_NAME
    assert ws["A2"].value == "MLTC: Elderplan Homefirst"
    assert ws["F2"].value == "MLTC: Elderplan Homefirst"
    for cell in ("A3", "F3"):
        v = ws[cell].value
        assert "ID: 24010" in v
        assert "Name: Cheng, Lizhu" in v

    merged = {str(rng) for rng in ws.merged_cells.ranges}
    for rng in ("A1:D1", "A2:D2", "A3:D3",
                "F1:K1", "F2:K2", "F3:K3"):
        assert rng in merged

    # table-header row is row 4 for both blocks
    assert [ws.cell(row=4, column=c).value
            for c in range(1, 5)] == [
        "Date", "Day", "Time-In", "Time-Out"
    ]
    assert [ws.cell(row=4, column=c).value
            for c in range(6, 12)] == [
        "Date", "Day", "Pick-Up Time", "Arrival Time",
        "Departure Time", "Drop-Off Time",
    ]

    # first data row (row 5), left and right blocks aligned
    assert ws.cell(row=5, column=1).value == datetime(2026, 5, 1)
    assert ws.cell(row=5, column=1).number_format == "m/d/yyyy"
    assert ws.cell(row=5, column=3).value == "08:17"   # Time-In
    assert ws.cell(row=5, column=4).value == "12:13"   # Time-Out
    assert ws.cell(row=5, column=6).value == datetime(2026, 5, 1)
    assert ws.cell(row=5, column=6).number_format == "m/d/yyyy"
    assert ws.cell(row=5, column=8).value == "08:05"   # Pick-Up
    assert ws.cell(row=5, column=9).value == "08:15"   # Arrival
    assert ws.cell(row=5, column=10).value == "12:15"  # Departure
    assert ws.cell(row=5, column=11).value == "12:25"  # Drop-Off

    # ineligible row (row 6) blank in both blocks
    assert ws.cell(row=6, column=3).value in (None, "")
    assert ws.cell(row=6, column=8).value in (None, "")

    # exactly one COLUMN break at column 5; no row breaks
    assert ws.col_breaks.count == 1
    assert list(ws.col_breaks.brk)[0].id == 5
    assert ws.row_breaks.count == 0

    # print area spans to column K, through the footer (row 9)
    assert ws.print_area is not None
    assert "K" in ws.print_area
    assert "K9" in ws.print_area.replace("$", "")

    # spacer column fixed width (unchanged)
    assert ws.column_dimensions["E"].width == 3

    # page setup: not fit-to-width, fit each page to one page tall
    assert ws.page_setup.fitToWidth == 0
    assert ws.page_setup.fitToHeight == 1

    # --- footer: bold caption merged per block ---
    # ROWS has 2 entries -> last_data_row = 6, caption row 8, sig row 9
    assert ws["A8"].value == "Attendance Sheet"
    assert ws["F8"].value == "Transportation Sheet"
    assert "A8:D8" in merged
    assert "F8:K8" in merged

    # --- signature/date row 9 with ruled (bottom-border) blanks ---
    assert ws.cell(row=9, column=1).value == "Signature:"
    assert ws.cell(row=9, column=3).value == "Date:"
    assert ws.cell(row=9, column=2).border.bottom.style == "thin"
    assert ws.cell(row=9, column=4).border.bottom.style == "thin"
    assert ws.cell(row=9, column=6).value == "Signature:"
    assert ws.cell(row=9, column=9).value == "Date:"
    for c in (7, 8, 10, 11):
        assert ws.cell(row=9, column=c).border.bottom.style == "thin"

    # --- horizontal print centering on ---
    assert ws.print_options.horizontalCentered is True

    # --- footer text did NOT bloat a data column ---
    # (autosize is bounded to the data region; col F is the right
    # Date col ~13.5 and is not a rule column)
    assert ws.column_dimensions["F"].width < 20

    # --- Attendance (left) column minimum: each left col >= 16 ---
    for c in ("A", "B", "C", "D"):
        assert ws.column_dimensions[c].width >= 16 - 1e-6

    # --- guaranteed Signature/Date line lengths (both footers) ---
    assert ws.column_dimensions["B"].width >= 22 - 1e-6   # left sig
    assert ws.column_dimensions["D"].width >= 14 - 1e-6   # left date
    assert (ws.column_dimensions["G"].width
            + ws.column_dimensions["H"].width) >= 22 - 1e-6
    assert (ws.column_dimensions["J"].width
            + ws.column_dimensions["K"].width) >= 14 - 1e-6

    # --- left 16-floor is NOT applied to the right block ---
    assert ws.column_dimensions["G"].width < 16
