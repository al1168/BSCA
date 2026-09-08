"""Render the two schedule tables side by side in one workbook.

Both tables sit on one sheet so they display side by side when the
file is opened; a manual column page break between them makes each
print on its own page. Header lines are merged across each table's
column span so long text shows fully without widening a data column.
Each table has a bold caption and a ruled Signature/Date line below
it, and is horizontally centered on its printed page. The Attendance
(left) columns have a generous minimum width so that table fills the
page; the Transportation columns autosize narrow so all six fit one
printed page. The Signature/Date rule lines are guaranteed a minimum
length in both footers (Signature over the first three columns; the
Attendance Date sits on its last column alone while the Transport
Date spans the last two columns for a longer write-on line).
"""

from openpyxl import Workbook
from openpyxl.styles import Border, Side, Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.pagebreak import Break
from openpyxl.worksheet.page import PageMargins

from monthly_schedule.health_plan import display_plan

COMPANY_NAME = "Bowery Senior Care Inc"

_THIN = Side(style="thin")
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_RULE = Border(bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center")
_FONT_SIZE = 12                        # slightly larger than the 11pt default
_BOLD = Font(bold=True, size=_FONT_SIZE)
_REGULAR = Font(size=_FONT_SIZE)
_ROW_HEIGHT = 18                       # taller than ~15pt default, but
                                       # still fits a full month on one
                                       # page so Excel doesn't shrink-to-
                                       # fit (which drops thin grid lines)

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
# Per-column width floors for the Attendance (left) table, keyed by
# column index (1=Date, 2=Day, 3=Time-In, 4=Time-Out). Day uses the
# default floor so it autosizes narrow (like the transport Day column);
# Time-In/Time-Out are widened to fill the space it gives up.
_LEFT_COL_FLOORS = {1: 16, 2: _WIDTH_MIN, 3: 24, 4: 24}
# Transport (right) floors: only Date (F) matches attendance Date (A).
# The four time columns autosize from their headers — with six columns
# the transport table must stay narrow enough to print on one page
# (wide floors here previously pushed Drop-Off onto an extra sheet).
# The footer lines rely on the _ensure_line_min minimums instead of
# matching the attendance lines' exact widths.
_RIGHT_COL_FLOORS = {6: 16}
_SIG_LINE_MIN = 22                      # min total Signature rule width
_DATE_LINE_MIN = 14                     # min total Date rule width


_RIGHT = Alignment(horizontal="right", vertical="center")


def _member_name(member):
    return f"{member['last_name']}, {member['first_name']}"


def format_auth_label(weekdays):
    """Render a set of weekday ints as 'Auth: 1.3.5' in weekday order
    (1=Mon..7=Sun), dot-separated. Empty/None -> '' (no label)."""
    if not weekdays:
        return ""
    days = ".".join(str(d) for d in sorted(weekdays) if 1 <= d <= 7)
    return f"Auth: {days}" if days else ""


def _write_header_block(ws, start_row, first_col, last_col, member,
                        auth_label=None):
    """Write the 3 header lines, each merged across [first_col,
    last_col]. When `auth_label` is given, the ID/Name line (offset 2 —
    the row directly above the table) splits: ID/Name keeps the left and
    most of the row, with the right-aligned authorized-days label in the
    rightmost column(s). Returns the first free row after the block."""
    lines = (
        COMPANY_NAME,
        f"MLTC: {display_plan(member['health_plan'])}",
        (
            f"ID: {member['center_id']}   "
            f"Name: {_member_name(member)}"
        ),
    )
    # Auth block = the rightmost column(s): 2 for the wider transport
    # table, 1 for the attendance table, so the ID/Name text keeps room.
    span = last_col - first_col + 1
    auth_first = last_col - (2 if span > 4 else 1) + 1
    for offset, text in enumerate(lines):
        row = start_row + offset
        cell = ws.cell(row=row, column=first_col, value=text)
        cell.font = _BOLD                          # all header lines bold
        if offset == 2 and auth_label:
            # ID/Name over the left block, auth right-aligned at far
            # right — directly on top of the table.
            ws.merge_cells(
                start_row=row, start_column=first_col,
                end_row=row, end_column=auth_first - 1,
            )
            auth_cell = ws.cell(row=row, column=auth_first, value=auth_label)
            auth_cell.font = _BOLD
            auth_cell.alignment = _RIGHT
            if auth_first < last_col:
                ws.merge_cells(
                    start_row=row, start_column=auth_first,
                    end_row=row, end_column=last_col,
                )
        else:
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
            cell.font = _REGULAR
        r += 1
    return r


def _write_ruled_label(ws, row, label, label_col, rule_cols):
    """Write `label` into `label_col`, then merge it together with
    `rule_cols` into one cell and run a bottom-border rule under the
    whole span. The label therefore sits on its own extended write-on
    line (no gap between the label and the line)."""
    cols = (label_col,) + tuple(rule_cols)
    lo, hi = min(cols), max(cols)
    label_cell = ws.cell(row=row, column=label_col, value=label)
    label_cell.font = _REGULAR
    for col in range(lo, hi + 1):
        ws.cell(row=row, column=col).border = _RULE
    if hi > lo:
        ws.merge_cells(
            start_row=row, start_column=lo, end_row=row, end_column=hi,
        )


def _write_footer(ws, data_last_row, first_col, last_col, caption,
                  sig_label_col, sig_rule_cols,
                  date_label_col, date_rule_cols):
    """After a blank spacer row: a bold caption merged across
    [first_col, last_col], then a Signature/Date row where each label
    shares one merged, bottom-bordered cell with its write-on line.
    Row layout:
      data_last_row + 1  -> blank spacer (nothing written)
      data_last_row + 2  -> caption
      data_last_row + 3  -> blank spacer  ┐ two cells of space between
      data_last_row + 4  -> blank spacer  ┘ the caption and the line
      data_last_row + 5  -> Signature/Date line
    """
    cap_row = data_last_row + 2
    sig_row = data_last_row + 5
    cap = ws.cell(row=cap_row, column=first_col, value=caption)
    cap.font = _BOLD
    ws.merge_cells(
        start_row=cap_row, start_column=first_col,
        end_row=cap_row, end_column=last_col,
    )
    _write_ruled_label(ws, sig_row, "Signature:",
                       sig_label_col, sig_rule_cols)
    _write_ruled_label(ws, sig_row, "Date:",
                       date_label_col, date_rule_cols)


def _autosize_columns(ws, table_header_row, last_row):
    """Width per data column = longest value/label in it (rows from
    the table-header row down through `last_row`; merged header lines
    and the footer are excluded by the caller's bound). Left
    (Attendance) columns use the per-column `_LEFT_COL_FLOORS` so the
    table fills the page while the Day column stays narrow; the spacer
    column is fixed."""
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
        floors = (_LEFT_COL_FLOORS if col < SPACER_COL
                  else _RIGHT_COL_FLOORS)
        floor = floors.get(col, _WIDTH_MIN)
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


def build_workbook(member, rows, output_path, auth_weekdays=None):
    """Write the side-by-side workbook to output_path; return it.

    `auth_weekdays` (optional) is a set of weekday ints (1=Mon..7=Sun)
    the member is authorized for; when given it is shown right-aligned
    in the top-right of each table header (e.g. 'Auth: Mon Fri Sun')."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Schedule"

    left_last_col = LEFT_FIRST_COL + len(TABLE1_HEADERS) - 1   # D
    right_last_col = RIGHT_FIRST_COL + len(TABLE2_HEADERS) - 1  # K

    auth_label = format_auth_label(auth_weekdays)
    _write_header_block(ws, 1, LEFT_FIRST_COL, left_last_col,
                        member, auth_label=auth_label)
    _write_header_block(ws, 1, RIGHT_FIRST_COL, right_last_col,
                        member, auth_label=auth_label)
    table_header_row = 1 + HEADER_ROWS                         # 4

    end_left = _write_table(ws, table_header_row, LEFT_FIRST_COL,
                            TABLE1_HEADERS, TABLE1_KEYS, rows)
    end_right = _write_table(ws, table_header_row, RIGHT_FIRST_COL,
                             TABLE2_HEADERS, TABLE2_KEYS, rows)
    last_data_row = max(end_left, end_right) - 1

    _write_footer(
        ws, last_data_row, LEFT_FIRST_COL, left_last_col,
        LEFT_CAPTION,
        sig_label_col=1, sig_rule_cols=(2, 3),
        date_label_col=4, date_rule_cols=(),
    )
    _write_footer(
        ws, last_data_row, RIGHT_FIRST_COL, right_last_col,
        RIGHT_CAPTION,
        sig_label_col=6, sig_rule_cols=(7, 8),
        date_label_col=10, date_rule_cols=(11,),
    )
    footer_last_row = last_data_row + 5

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
    # Tight margins so a full month (taller rows + larger font) still
    # fits one page at ~100% — avoids the shrink-to-fit that makes Excel
    # drop the thin grid lines.
    ws.page_margins = PageMargins(
        left=0.3, right=0.3, top=0.3, bottom=0.3, header=0.2, footer=0.2,
    )

    _autosize_columns(ws, table_header_row, last_data_row)
    # Footer write-on lines span the full merged label+rule cells; grow
    # those spans (not the narrow Day column) to guarantee a usable line.
    _ensure_line_min(ws, (1, 2, 3), _SIG_LINE_MIN)  # left signature (A:C)
    _ensure_line_min(ws, (4,), _DATE_LINE_MIN)      # left date (D)
    _ensure_line_min(ws, (7, 8), _SIG_LINE_MIN)    # right signature
    _ensure_line_min(ws, (10, 11), _DATE_LINE_MIN)  # right date (J:K)

    # Taller rows across the whole printed area for legibility.
    for r in range(1, footer_last_row + 1):
        ws.row_dimensions[r].height = _ROW_HEIGHT

    wb.save(output_path)
    return output_path
