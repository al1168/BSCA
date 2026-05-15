"""Render the two-table printable workbook with openpyxl (spec §5)."""

from openpyxl import Workbook
from openpyxl.styles import Border, Side, Alignment, Font
from openpyxl.worksheet.pagebreak import Break

COMPANY_NAME = "Bowery Senior Care Inc"

_THIN = Side(style="thin")
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center")
_BOLD = Font(bold=True)

TABLE1_HEADERS = ["Date", "Day", "Time-In", "Time-Out"]
TABLE1_KEYS = ["time_in", "time_out"]
TABLE2_HEADERS = [
    "Date", "Day", "Pick-Up Time", "Arrival Time",
    "Departure Time", "Drop-Off Time",
]
TABLE2_KEYS = ["pickup", "arrival", "departure", "dropoff"]


def _member_name(member):
    return f"{member['last_name']}, {member['first_name']}"


def _write_header_block(ws, start_row, member):
    ws.cell(row=start_row, column=1, value=COMPANY_NAME).font = _BOLD
    ws.cell(row=start_row + 1, column=1,
            value=f"MLTC: {member['health_plan']}")
    ws.cell(row=start_row + 2, column=1,
            value=f"ID: {member['center_id']}")
    ws.cell(row=start_row + 2, column=2,
            value=f"Name: {_member_name(member)}")
    ws.cell(row=start_row + 2, column=4,
            value=f"Auth Days: {member['sadc_auth']}")
    return start_row + 3  # first free row after the block


def _write_table(ws, start_row, headers, keys, rows):
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=col, value=text)
        cell.font = _BOLD
        cell.alignment = _CENTER
        cell.border = _BOX
    r = start_row + 1
    for row in rows:
        date_cell = ws.cell(row=r, column=1, value=row["date"])
        date_cell.number_format = "m/d/yyyy"
        ws.cell(row=r, column=2, value=row["day"])
        for offset, key in enumerate(keys, start=3):
            ws.cell(row=r, column=offset, value=row[key])
        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=r, column=col)
            cell.alignment = _CENTER
            cell.border = _BOX
        r += 1
    return r  # first free row after the table


def build_workbook(member, rows, output_path):
    """Write the workbook to output_path and return that path."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Schedule"

    after_h1 = _write_header_block(ws, 1, member)
    after_t1 = _write_table(ws, after_h1, TABLE1_HEADERS, TABLE1_KEYS, rows)
    last_t1_row = after_t1 - 1

    # manual page break AFTER the last table-1 row -> table 2 on next page
    ws.row_breaks.append(Break(id=last_t1_row))

    after_h2 = _write_header_block(ws, after_t1, member)
    after_t2 = _write_table(ws, after_h2, TABLE2_HEADERS, TABLE2_KEYS, rows)

    ws.print_area = f"A1:F{after_t2 - 1}"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    wb.save(output_path)
    return output_path
