"""Render the two schedule tables side by side in one workbook.

Both tables sit on one sheet so they display side by side when the
file is opened; a manual column page break between them makes each
print on its own page. Header lines are merged across each table's
column span so long text shows fully without widening a data column.
Each table has a bold caption and a ruled Signature/Date line below
it, and is horizontally centered on its printed page. The Attendance
(left) columns have a generous minimum width so that table fills the
page; the Signature/Date rule lines are guaranteed a minimum length
in both footers.
"""

from openpyxl import Workbook
from openpyxl.styles import Border, Side, Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.pagebreak import Break

from monthly_schedule.health_plan import display_plan

COMPANY_NAME = "Bowery Senior Care Inc"

_THIN = Side(style="thin")
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_RULE = Border(bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center")
_BOLD = Font(bold=True)

TABLE1_HEADERS = ["Date", "Day", "Time-In", "Time-Out"]
TABLE1_KEYS = ["time_in", "time_out"]
TABLE2_HEADERS = [
    "Date", "Day", "Pick-Up Time", "Arrival Time",
    "Departure Time", "Drop-Off Time",
]
TABLE2_KEYS = ["pickup", "arrival", "departure", "dropoff"]

LEFT_FIRST_COL = 1                      # A
SPACER_COL = 5                          # E
RIGHT_FIRST_COL = 6                     # F
SPACER_WIDTH = 3
HEADER_ROWS = 3                         # company / MLTC / ID-Name-Auth
LEFT_CAPTION = "Attendance Sheet"
RIGHT_CAPTION = "Transportation Sheet"
_WIDTH_FACTOR = 1.15
_WIDTH_PAD = 2
_WIDTH_MIN = 4
_WIDTH_MAX = 40
_LEFT_MIN_WIDTH = 16                    # Attendance (left) column floor
_SIG_LINE_MIN = 22                      # min total Signature rule width
_DATE_LINE_MIN = 14                     # min total Date rule width


def _member_name(member):
    return f"{member['last_name']}, {member['first_name']}"


def _write_header_block(ws, start_row, first_col, last_col, member):
    """Write the 3 header lines, each merged across [first_col,
    last_col]. Returns the first free row after the block."""
    lines = (
        COMPANY_NAME,
        f"MLTC: {display_plan(member['health_plan'])}",
        (
            f"ID: {member['center_id']}   "
            f"Name: {_member_name(member)}"
        ),
    )
    for offset, text in enumerate(lines):
        row = start_row + offset
        cell = ws.cell(row=row, column=first_col, value=text)
        if offset == 0:
            cell.font = _BOLD
        ws.merge_cells(
            start_row=row, start_column=first_col,
            end_row=row, end_column=last_col,
        )
    return start_row + HEADER_ROWS


def _write_table(ws, start_row, first_col, headers, keys, rows):
    """Write the table-header row then one row per day, with Date at
    `first_col`, Day next, then `keys`. Returns the first free row
    after the table."""
    for offset, text in enumerate(headers):
        cell = ws.cell(row=start_row, column=first_col + offset,
                       value=text)
        cell.font = _BOLD
        cell.alignment = _CENTER
        cell.border = _BOX
    r = start_row + 1
    for row in rows:
        date_cell = ws.cell(row=r, column=first_col,
                            value=row["date"])
        date_cell.number_format = "m/d/yyyy"
        ws.cell(row=r, column=first_col + 1, value=row["day"])
        for k_off, key in enumerate(keys):
            ws.cell(row=r, column=first_col + 2 + k_off,
                    value=row[key])
        for col_off in range(len(headers)):
            cell = ws.cell(row=r, column=first_col + col_off)
            cell.alignment = _CENTER
            cell.border = _BOX
        r += 1
    return r


def _write_footer(ws, data_last_row, first_col, last_col, caption,
                  sig_label_col, sig_rule_cols,
                  date_label_col, date_rule_cols):
    """After a blank spacer row: a bold caption merged across
    [first_col, last_col], then a Signature/Date row with
    bottom-bordered blank rule cells. Row layout:
      data_last_row + 1  -> blank spacer (nothing written)
      data_last_row + 2  -> caption
      data_last_row + 3  -> Signature/Date line
    """
    cap_row = data_last_row + 2
    sig_row = data_last_row + 3
    cap = ws.cell(row=cap_row, column=first_col, value=caption)
    cap.font = _BOLD
    ws.merge_cells(
        start_row=cap_row, start_column=first_col,
        end_row=cap_row, end_column=last_col,
    )
    ws.cell(row=sig_row, column=sig_label_col, value="Signature:")
    for col in sig_rule_cols:
        ws.cell(row=sig_row, column=col).border = _RULE
    ws.cell(row=sig_row, column=date_label_col, value="Date:")
    for col in date_rule_cols:
        ws.cell(row=sig_row, column=col).border = _RULE


def _autosize_columns(ws, table_header_row, last_row):
    """Width per data column = longest value/label in it (rows from
    the table-header row down through `last_row`; merged header lines
    and the footer are excluded by the caller's bound). Left
    (Attendance) columns get the `_LEFT_MIN_WIDTH` floor so that
    table fills the page; the spacer column is fixed."""
    data_cols = (
        list(range(LEFT_FIRST_COL,
                    LEFT_FIRST_COL + len(TABLE1_HEADERS)))
        + list(range(RIGHT_FIRST_COL,
                      RIGHT_FIRST_COL + len(TABLE2_HEADERS)))
    )
    for col in data_cols:
        longest = 0
        for r in range(table_header_row, last_row + 1):
            value = ws.cell(row=r, column=col).value
            if value is None:
                continue
            longest = max(longest, len(str(value)))
        floor = _LEFT_MIN_WIDTH if col < SPACER_COL else _WIDTH_MIN
        width = longest * _WIDTH_FACTOR + _WIDTH_PAD
        width = min(_WIDTH_MAX, max(floor, width))
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.column_dimensions[
        get_column_letter(SPACER_COL)
    ].width = SPACER_WIDTH


def _ensure_line_min(ws, rule_cols, line_min):
    """Raise the given rule columns' widths (distributed evenly,
    only increasing) until their combined width is at least
    `line_min`. Columns already summing to >= line_min are
    untouched."""
    total = sum(
        ws.column_dimensions[get_column_letter(c)].width
        for c in rule_cols
    )
    if total >= line_min:
        return
    add = (line_min - total) / len(rule_cols)
    for c in rule_cols:
        letter = get_column_letter(c)
        ws.column_dimensions[letter].width += add


def build_workbook(member, rows, output_path):
    """Write the side-by-side workbook to output_path; return it."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Schedule"

    left_last_col = LEFT_FIRST_COL + len(TABLE1_HEADERS) - 1   # D
    right_last_col = RIGHT_FIRST_COL + len(TABLE2_HEADERS) - 1  # K

    _write_header_block(ws, 1, LEFT_FIRST_COL, left_last_col,
                        member)
    _write_header_block(ws, 1, RIGHT_FIRST_COL, right_last_col,
                        member)
    table_header_row = 1 + HEADER_ROWS                         # 4

    end_left = _write_table(ws, table_header_row, LEFT_FIRST_COL,
                            TABLE1_HEADERS, TABLE1_KEYS, rows)
    end_right = _write_table(ws, table_header_row, RIGHT_FIRST_COL,
                             TABLE2_HEADERS, TABLE2_KEYS, rows)
    last_data_row = max(end_left, end_right) - 1

    _write_footer(
        ws, last_data_row, LEFT_FIRST_COL, left_last_col,
        LEFT_CAPTION,
        sig_label_col=1, sig_rule_cols=(2,),
        date_label_col=3, date_rule_cols=(4,),
    )
    _write_footer(
        ws, last_data_row, RIGHT_FIRST_COL, right_last_col,
        RIGHT_CAPTION,
        sig_label_col=6, sig_rule_cols=(7, 8),
        date_label_col=9, date_rule_cols=(10, 11),
    )
    footer_last_row = last_data_row + 3

    # column page break after spacer col E -> Table 1 | Table 2 pages
    ws.col_breaks.append(Break(id=SPACER_COL))

    ws.print_area = (
        f"A1:{get_column_letter(right_last_col)}{footer_last_row}"
    )
    ws.print_options.horizontalCentered = True
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 0
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    _autosize_columns(ws, table_header_row, last_data_row)
    _ensure_line_min(ws, (2,), _SIG_LINE_MIN)      # left signature (B)
    _ensure_line_min(ws, (4,), _DATE_LINE_MIN)     # left date (D)
    _ensure_line_min(ws, (7, 8), _SIG_LINE_MIN)    # right signature
    _ensure_line_min(ws, (10, 11), _DATE_LINE_MIN)  # right date (J,K)

    wb.save(output_path)
    return output_path
