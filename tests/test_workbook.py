from datetime import date, datetime

from openpyxl import load_workbook

from monthly_schedule.workbook import build_workbook, COMPANY_NAME

MEMBER = {
    "center_id": 24010,
    "last_name": "Cheng",
    "first_name": "Lizhu",
    "health_plan": "Elderplan Homefirst",
    "sadc_auth": "1.3.4.5",
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


def test_workbook_structure(tmp_path):
    out = tmp_path / "sched.xlsx"
    build_workbook(MEMBER, ROWS, str(out))
    assert out.exists()

    wb = load_workbook(str(out))
    ws = wb["Schedule"]

    # header block
    assert ws["A1"].value == COMPANY_NAME
    assert ws["A2"].value == "MLTC: Elderplan Homefirst"
    assert ws["A3"].value == "ID: 24010"
    assert ws["B3"].value == "Name: Cheng, Lizhu"
    assert ws["D3"].value == "Auth Days: 1.3.4.5"

    # table 1 header on row 4
    assert [ws.cell(row=4, column=c).value for c in range(1, 5)] == [
        "Date", "Day", "Time-In", "Time-Out"
    ]
    # table 1 first data row
    # openpyxl reads date serial cells back as datetime.datetime, not datetime.date
    assert ws.cell(row=5, column=1).value == datetime(2026, 5, 1)
    assert ws.cell(row=5, column=1).number_format == "m/d/yyyy"
    assert ws.cell(row=5, column=3).value == "08:17"
    assert ws.cell(row=5, column=4).value == "12:13"
    # ineligible row blank
    assert ws.cell(row=6, column=3).value in (None, "")

    # exactly one manual page break
    assert ws.row_breaks.count == 1

    # table 2 appears later with its own header block + 6-col header
    found_t2 = False
    for r in range(1, ws.max_row + 1):
        if ws.cell(row=r, column=1).value == "Date" and ws.cell(
            row=r, column=3
        ).value == "Pick-Up Time":
            assert ws.cell(row=r, column=6).value == "Drop-Off Time"
            found_t2 = True
            break
    assert found_t2

    # print area set and spans to column F
    assert ws.print_area is not None
    assert "F" in ws.print_area
