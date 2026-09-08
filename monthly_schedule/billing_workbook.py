# -*- coding: utf-8 -*-
"""Aggregate monthly "Member Attendance - Bowery billing days" workbook.

One sheet, one section per insurance plan (fixed order), each section a
day-of-month grid: green fill = authorized day, `1` = scheduled day
(matches the member's generated timesheet, absences included). Totals,
counts and the bottom per-plan summary are live Excel formulas so staff
can hand-edit `1`s afterwards and every total recalculates.

The layout replicates the hand-maintained reference workbook
(`6. June 2026 Member Attendance-Bowery billing days.xlsx`) cell-for-cell
in *format*; deliberate deviations from that file's hand errors: no stale
dates in empty sections, uniform fills, no leftover freeze panes.

Pure module: data in (BillingRow list) -> Workbook out. No DB, no Qt.
"""

import calendar
import os
from collections import namedtuple
from dataclasses import dataclass
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import (
    Alignment, Border, Color, Font, PatternFill, Side,
)
from openpyxl.utils import get_column_letter

from monthly_schedule.auth_days import get_authorized_weekdays
from monthly_schedule.month_dates import get_month_dates
from monthly_schedule.office_theme import OFFICE_THEME_XML

# Section order and title text exactly as the reference sheet.
SECTIONS = [
    ("AE", "AETNA-AE"),
    ("BCBS", "Anthem-BCBS"),
    ("CL", "CenterLight-CL"),
    ("CP", "Centers Plan-CP"),
    ("ES", "RiverSpring-ES"),
    ("HC", "Hamaspik-HC"),
    ("HF", "HealthFirst-HF"),
    ("HOF", "Homefirst-HOF"),
    ("SWH", "SWH"),
    ("VCM", "VCM"),
    ("VNS", "VNS"),
]
_SECTION_CODES = {code for code, _ in SECTIONS}

# Hand-typed Access [Health Plan] variants -> section code.
PLAN_ALIASES = {
    "AETNA": "AE",
    "ANTHEM": "BCBS",
    "BCSB": "BCBS",
}

# Columns H / I come from the Codes lookup table in the Access DB
# ({plan: (sadc, trans)} via db.get_billing_codes). Plans without a
# table row render as '????' so missing codes are visible, not silent.
UNKNOWN_CODE = "????"

# ---------------------------------------------------------------- styles

# Excel's exact tint values for the "80% lighter" / "60% lighter"
# theme-color variants (what the reference file stores).
_TINT_80 = 0.7999816888943144
_TINT_60 = 0.5999938962981048

GREEN_RGB = "FF00B050"      # authorized-day cell
TITLE_RGB = "FF92D050"      # section title box
PURPLE_RGB = "FF975CCB"     # trailing unused day slots (e.g. day 31)

_GREEN_FILL = PatternFill("solid", fgColor=GREEN_RGB)
_TITLE_FILL = PatternFill("solid", fgColor=TITLE_RGB)
_PURPLE_FILL = PatternFill("solid", fgColor=PURPLE_RGB)
# theme 9 = accent6 (green): column headers, AR cells, section total row
_HEADER_FILL = PatternFill("solid", fgColor=Color(theme=9, tint=_TINT_80))
# theme 7 = accent4 (gold): date headers 80%, Sunday strip + Number col 60%
_DATE_FILL = PatternFill("solid", fgColor=Color(theme=7, tint=_TINT_80))
_SUNDAY_FILL = PatternFill("solid", fgColor=Color(theme=7, tint=_TINT_60))
# theme 3 = dk2 (blue-gray): count rows
_COUNT_FILL = PatternFill("solid", fgColor=Color(theme=3, tint=_TINT_80))
# theme 4 = accent1 (blue): bottom summary table
_SUMMARY_FILL = PatternFill("solid", fgColor=Color(theme=4, tint=_TINT_80))
# count-row member-count cell is painted white in the reference
_WHITE_FILL = PatternFill("solid", fgColor=Color(theme=0, tint=0.0))

_THIN = Side(style="thin")
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_TOP_BOTTOM = Border(top=_THIN, bottom=_THIN)
_FONT_NAME = "Calibri"
_FONT_SIZE = 12
_BOLD = Font(name=_FONT_NAME, size=_FONT_SIZE, bold=True)
_REGULAR = Font(name=_FONT_NAME, size=_FONT_SIZE)
_CENTER = Alignment(horizontal="center", vertical="center")
_CENTER_WRAP = Alignment(horizontal="center", vertical="center",
                         wrap_text=True)
_LEFT = Alignment(horizontal="left", vertical="center")

_DATE_NUMFMT = "mm-dd-yy"

# Grid geometry: day d (1..n_days) lives at column 15+d, then one
# always-purple divider column, then Total, then Remark. For a 30-day
# month that lands the divider on AT and Total on AU; 31-day months
# shift Total/Remark right one.
DAY_FIRST_COL = 16          # P
_Layout = namedtuple(
    "_Layout", "n_days sundays div_col total_col remark_col"
)


def _make_layout(year, month):
    n_days = calendar.monthrange(year, month)[1]
    sundays = {
        d for d in range(1, n_days + 1)
        if date(year, month, d).isoweekday() == 7
    }
    div_col = DAY_FIRST_COL + n_days
    return _Layout(n_days, sundays, div_col, div_col + 1, div_col + 2)


_COLUMN_WIDTHS = {
    1: 5.625,        # A Number
    2: 7.625,        # B ID #
    3: 18.5,         # C NAME
    4: 8.0,          # D MLTC HEALTH PLAN
    5: 8.0,          # E PLAN TYPE
    6: 11.625,       # F DOB
    7: 7.0,          # G GENDER
    8: 12.125,       # H ENROLLMENT DATE
    9: 13.75,        # I PLAN ID
    10: 11.625,      # J MEDICAID
    11: 8.625,       # K SADC CODE
    12: 8.625,       # L TRANSPTATION CODE
    13: 6.625,       # M No. Days
    14: 11.625,      # N AUTH EXPIRATION DATE
    15: 13.75,       # O AUTH. DAYS
}
_DAY_COL_WIDTH = 4.625      # day cells + purple divider
_TOTAL_COL_WIDTH = 6.625
_REMARK_COL_WIDTH = 61.25
_ROW_HEIGHT = 24.8

# Header labels keep the reference sheet's quirks where unchanged
# (the TRANSPTATION typo and double spaces). ENROLLMENT DATE is the
# member's earliest Enrollment start_date (not Contacts.[Admission
# Date], which newer members leave blank); AUTH EXPIRATION DATE was
# AUTHORIZATION — rename only, same data; MLTC HEALTH PLAN is the
# member's section code; PLAN TYPE and PLAN ID are the Plan Type and
# Member ID of the latest authorization active in the month.
_HEADER_LABELS = [
    "Number", "ID #", "NAME", "MLTC HEALTH PLAN", "PLAN TYPE", "DOB",
    "GENDER", "ENROLLMENT DATE", "PLAN ID", "MEDICAID", "SADC CODE",
    "TRANSPTATION  CODE", "No. Days", "AUTH EXPIRATION DATE",
    "AUTH.  DAYS",
]

# Exact month-name formula string from the reference title rows (typo
# "January'" included) — it displays the month name from the O1 date
# (the first day column of the top strip).
_MONTH_FORMULA = (
    '= CHOOSE((MONTH(P$1)), "January\'", "February", "March", "April", '
    '"May", "June", "July", "August", "September", "October", '
    '"November", "December")'
)


# ------------------------------------------------------------- data model

@dataclass
class BillingRow:
    """One member's line on the billing sheet."""
    center_id: int
    name: str                # "Last, First"
    gender: str              # "M" / "F" / ""
    dob: object              # date | str (unparseable raw) | None
    registered: object       # date | None (earliest Enrollment start)
    medicaid: str
    plan: str                # normalized section code (also column D)
    num_days: int            # M: authorized days per week
    auth_end: object         # date | None (N)
    auth_days_text: str      # O: "1.3.5"
    green_days: frozenset    # day-of-month ints: authorized
    one_days: frozenset      # day-of-month ints: scheduled
    remarks: str = ""        # Remark: this month's absences
    plan_id: str = ""        # I: Member ID of the month's latest auth
    plan_type: str = ""      # E: Plan Type of the month's latest auth


# ------------------------------------------------------------ pure helpers

def normalize_billing_plan(raw):
    """Access [Health Plan] free text -> section code, or None when the
    value is blank/unrecognized (member is left off the billing sheet)."""
    plan = str(raw or "").strip().upper()
    plan = PLAN_ALIASES.get(plan, plan)
    return plan if plan in _SECTION_CODES else None


def normalize_gender(raw):
    """'M/男' -> 'M', '女' -> 'F', 'f' -> 'F', blank/None -> ''."""
    text = str(raw or "")
    for ch in text:
        up = ch.upper()
        if up in ("M", "F"):
            return up
        if ch == "男":
            return "M"
        if ch == "女":
            return "F"
    return ""


def format_auth_days_dots(weekdays):
    """{1,3,5} -> '1.3.5' (the sheet's AUTH. DAYS notation)."""
    return ".".join(str(d) for d in sorted(weekdays) if 1 <= d <= 7)


def format_absence_remarks(absences):
    """Absence rows -> 'Vacation 03-15-2026 - 04-15-2026, Doctor visit
    04-15-2026'. Full start-end range (single date when one day); a
    blank Leave Type leaves just the dates. Order preserved."""
    parts = []
    for row in absences:
        start = row["start_date"].strftime("%m-%d-%Y")
        end = row["end_date"].strftime("%m-%d-%Y")
        dates = start if start == end else f"{start} - {end}"
        leave_type = str(row["leave_type"] or "").strip()
        parts.append(f"{leave_type} {dates}".strip())
    return ", ".join(parts)


def parse_flex_date(value):
    """Best-effort date for the Short Text DOB / Admission Date columns.

    datetime/date -> date; parseable text ('2/1/1953', '2-1-1953',
    '1953-02-01') -> date; other non-empty text (e.g. the '4/1/20167'
    typos in the live DB) -> the stripped raw string so it stays visible
    for correction; ''/None -> None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        if 1900 <= parsed.year <= 2100:
            return parsed
    return text


def billing_filename(year, month, name):
    """'6. June 2026 billing Jane Doe.xlsx' — `name` is the required
    "Billing file name" from the GUI Settings dialog."""
    return f"{month}. {calendar.month_name[month]} {year} billing {name}.xlsx"


def collect_billing_row(member, ctx, extra, timesheet_rows,
                        auth_weekdays, year, month):
    """Build one BillingRow from a successfully-scheduled member.

    `extra` is this member's dict from db.get_all_billing_fields (may be
    empty when the roster query failed). `timesheet_rows` are the rows
    that fed the member's timesheet workbook, so the `1`s here always
    match what was printed — absences included. Returns None when the
    member's health plan doesn't map to a billing section.

    Note: green_days always spans the full month; one_days follows the
    rows given (identical today — All Members runs are full-month)."""
    plan = normalize_billing_plan(member.get("health_plan"))
    if plan is None:
        return None

    green_days = set()
    auth_end = None
    plan_id = ""
    plan_type = ""
    for day in get_month_dates(year, month):
        if not ctx.is_enrolled(day):
            continue
        auth = ctx.active_authorization(day)
        if auth is None:
            continue
        if day.isoweekday() in get_authorized_weekdays(auth["auth_days"]):
            green_days.add(day.day)
            auth_end = auth["auth_end"]   # last authorized day wins
            plan_id = str(auth.get("member_id") or "").strip()
            plan_type = str(auth.get("plan_type") or "").strip()

    one_days = {
        row["date"].day for row in timesheet_rows if row.get("time_in")
    }

    month_days = get_month_dates(year, month)
    remarks = format_absence_remarks(
        ctx.absences_overlapping(month_days[0], month_days[-1])
    )

    return BillingRow(
        center_id=member["center_id"],
        name=f"{member['last_name']}, {member['first_name']}",
        gender=normalize_gender(extra.get("gender")),
        dob=parse_flex_date(extra.get("dob")),
        registered=parse_flex_date(ctx.earliest_enrollment_start()),
        medicaid=str(extra.get("medicaid") or "").strip(),
        plan=plan,
        num_days=len(auth_weekdays or ()),
        auth_end=auth_end,
        auth_days_text=format_auth_days_dots(auth_weekdays or ()),
        green_days=frozenset(green_days),
        one_days=frozenset(one_days),
        remarks=remarks,
        plan_id=plan_id,
        plan_type=plan_type,
    )


# --------------------------------------------------------------- builders

def _paint_grid_cell(cell, fill=None):
    cell.font = _BOLD
    cell.alignment = _CENTER
    cell.border = _BOX
    if fill is not None:
        cell.fill = fill


def _write_day_headers(ws, row_dates, row_ddd, year, month, lay):
    """The paired date / =TEXT(...,"ddd") rows used by both the top
    strip (rows 1-2) and every section header, ending with the purple
    divider column."""
    for day in range(1, lay.n_days + 1):
        col = DAY_FIRST_COL + day - 1
        letter = get_column_letter(col)
        top = ws.cell(row=row_dates, column=col)
        bottom = ws.cell(row=row_ddd, column=col)
        top.value = datetime(year, month, day)
        top.number_format = "d"
        bottom.value = f'=TEXT({letter}{row_dates}, "ddd")'
        fill = _SUNDAY_FILL if day in lay.sundays else _DATE_FILL
        _paint_grid_cell(top, fill)
        _paint_grid_cell(bottom, fill)
    _paint_grid_cell(ws.cell(row=row_dates, column=lay.div_col),
                     _PURPLE_FILL)
    _paint_grid_cell(ws.cell(row=row_ddd, column=lay.div_col),
                     _PURPLE_FILL)


def _write_title_row(ws, row, title):
    """P:R merged green title box + the month-name formula in S."""
    ws.merge_cells(start_row=row, start_column=17,
                   end_row=row, end_column=19)
    for col in (17, 18, 19):
        cell = ws.cell(row=row, column=col)
        cell.fill = _TITLE_FILL
        cell.font = _BOLD
        cell.alignment = _CENTER
        cell.border = _TOP_BOTTOM
    ws.cell(row=row, column=17, value=title)
    q = ws.cell(row=row, column=20, value=_MONTH_FORMULA)
    q.font = _BOLD
    q.alignment = _LEFT


def _write_section_header(ws, row, year, month, lay):
    """Two header rows starting at `row`: merged A-O / Total / Remark
    labels and the day date/ddd pair."""
    h1, h2 = row, row + 1
    labels = list(zip(range(1, 16), _HEADER_LABELS)) + [
        (lay.total_col, "Total"), (lay.remark_col, "Remark"),
    ]
    for col, label in labels:
        ws.merge_cells(start_row=h1, start_column=col,
                       end_row=h2, end_column=col)
        for r in (h1, h2):
            cell = ws.cell(row=r, column=col)
            cell.font = _BOLD
            cell.alignment = _CENTER_WRAP if col <= 15 else _CENTER
            cell.border = _BOX
            cell.fill = _HEADER_FILL
        ws.cell(row=h1, column=col, value=label)
    _write_day_headers(ws, h1, h2, year, month, lay)


def _write_left_cell(ws, row, col, value, font=_REGULAR,
                     align=_CENTER_WRAP, numfmt=None, fill=None):
    cell = ws.cell(row=row, column=col)
    if value is not None and value != "":
        cell.value = value
    cell.font = font
    cell.alignment = align
    cell.border = _BOX
    if numfmt is not None and isinstance(value, (date, datetime)):
        cell.number_format = numfmt
    if fill is not None:
        cell.fill = fill
    return cell


def _write_day_cells(ws, row, lay, green_days=(), one_days=()):
    for day in range(1, lay.n_days + 1):
        col = DAY_FIRST_COL + day - 1
        cell = ws.cell(row=row, column=col)
        if day in green_days:
            cell.fill = _GREEN_FILL      # green wins over Sunday tint
            if day in one_days:
                cell.value = 1
        elif day in lay.sundays:
            cell.fill = _SUNDAY_FILL
        _paint_grid_cell(cell, None)
    _paint_grid_cell(ws.cell(row=row, column=lay.div_col), _PURPLE_FILL)


def _sum_formula(row, lay):
    """Day range + divider, mirroring the reference's =SUM(O6:AS6)."""
    return (
        f"=SUM({get_column_letter(DAY_FIRST_COL)}{row}"
        f":{get_column_letter(lay.div_col)}{row})"
    )


def _write_total_and_remark(ws, row, lay, remark_text=""):
    total = ws.cell(row=row, column=lay.total_col,
                    value=_sum_formula(row, lay))
    total.font = _BOLD
    total.alignment = _CENTER
    total.border = _BOX
    total.fill = _HEADER_FILL
    remark = ws.cell(row=row, column=lay.remark_col)
    if remark_text:
        remark.value = remark_text
    remark.font = _REGULAR
    remark.alignment = _LEFT
    remark.border = _BOX


def _write_member_row(ws, row, first_row, item, lay, codes):
    _write_left_cell(ws, row, 1, f"=ROW()-{first_row - 1}",
                     fill=_SUNDAY_FILL)
    _write_left_cell(ws, row, 2, item.center_id, font=_BOLD)
    _write_left_cell(ws, row, 3, item.name, font=_BOLD,
                     align=Alignment(horizontal="left",
                                     vertical="center", wrap_text=True))
    _write_left_cell(ws, row, 4, item.plan)
    _write_left_cell(ws, row, 5, item.plan_type)
    _write_left_cell(ws, row, 6, item.dob, numfmt=_DATE_NUMFMT)
    _write_left_cell(ws, row, 7, item.gender)
    _write_left_cell(ws, row, 8, item.registered, numfmt=_DATE_NUMFMT)
    _write_left_cell(ws, row, 9, item.plan_id)
    _write_left_cell(ws, row, 10, item.medicaid)
    sadc, trans = codes.get(item.plan, (UNKNOWN_CODE, UNKNOWN_CODE))
    _write_left_cell(ws, row, 11, sadc)
    _write_left_cell(ws, row, 12, trans)
    _write_left_cell(ws, row, 13, item.num_days or None)
    _write_left_cell(ws, row, 14, item.auth_end, numfmt=_DATE_NUMFMT)
    ell = _write_left_cell(ws, row, 15, item.auth_days_text)
    ell.number_format = "@"
    _write_day_cells(ws, row, lay,
                     green_days=item.green_days, one_days=item.one_days)
    _write_total_and_remark(ws, row, lay, remark_text=item.remarks)


def _write_blank_member_row(ws, row, lay):
    """The single placeholder row of an empty section (A=1 literal)."""
    _write_left_cell(ws, row, 1, 1)
    for col in range(2, 16):
        _write_left_cell(ws, row, col, None)
    _write_day_cells(ws, row, lay)
    _write_total_and_remark(ws, row, lay)


def _write_total_row(ws, row, first, last, lay):
    """Section total: whole row banded green, the Total column sums
    the member totals."""
    for col in range(1, lay.remark_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = _BOLD
        cell.alignment = _CENTER
        cell.border = _BOX
        cell.fill = _HEADER_FILL
    letter = get_column_letter(lay.total_col)
    ws.cell(row=row, column=lay.total_col,
            value=f"=SUM({letter}{first}:{letter}{last})")


def _write_count_row(ws, row, code, first, last, lay):
    """'Member with authorization' row: per-day column sums + counts."""
    a = ws.cell(row=row, column=1, value=code)
    a.font = _BOLD
    a.alignment = _CENTER_WRAP
    a.border = _BOX
    b = ws.cell(row=row, column=2, value=f"=COUNT(B{first}:B{last})")
    b.font = _REGULAR
    b.alignment = _CENTER_WRAP
    b.border = _BOX
    b.fill = _WHITE_FILL
    for col in (3, 4, 5):
        cell = ws.cell(row=row, column=col)
        cell.border = _BOX
    ws.merge_cells(start_row=row, start_column=6,
                   end_row=row, end_column=8)
    for col in range(6, 9):
        cell = ws.cell(row=row, column=col)
        cell.font = _BOLD
        cell.alignment = _CENTER_WRAP
        cell.border = _BOX
        cell.fill = _COUNT_FILL
    ws.cell(row=row, column=6, value="Member with authorization")
    for col in range(9, 16):
        # I..O stay unfilled in the reference (only borders)
        cell = ws.cell(row=row, column=col)
        cell.border = _BOX
    for col in range(DAY_FIRST_COL, lay.div_col + 1):   # days + divider
        letter = get_column_letter(col)
        cell = ws.cell(
            row=row, column=col,
            value=f"=SUM({letter}{first}:{letter}{last})",
        )
        cell.font = _BOLD
        cell.alignment = _CENTER
        cell.border = _BOX
        cell.fill = _COUNT_FILL
    total = ws.cell(row=row, column=lay.total_col,
                    value=_sum_formula(row, lay))
    total.font = _BOLD
    total.alignment = _CENTER
    total.border = _BOX
    total.fill = _COUNT_FILL
    remark = ws.cell(row=row, column=lay.remark_col)
    remark.border = _BOX


def _write_bottom_summary(ws, header_row, count_rows, lay):
    """Per-plan member-count / authorized-days table (cols D:F)."""
    def styled(row, col, value=None):
        cell = ws.cell(row=row, column=col)
        if value is not None:
            cell.value = value
        cell.font = _BOLD
        cell.alignment = _CENTER
        cell.border = _BOX
        cell.fill = _SUMMARY_FILL
        return cell

    total_letter = get_column_letter(lay.total_col)
    styled(header_row, 4, "MLTC")
    styled(header_row, 5, "会员数")
    styled(header_row, 6, "授权天数")
    row = header_row + 1
    first_code_row = row
    for code, _title in SECTIONS:
        cr = count_rows[code]
        styled(row, 4, code)
        styled(row, 5, f"=B{cr}")
        styled(row, 6, f"={total_letter}{cr}")
        row += 1
    styled(row, 4, "TOTAL")
    styled(row, 5, f"=SUM(E{first_code_row}:E{row - 1})")
    styled(row, 6, f"=SUM(F{first_code_row}:F{row - 1})")


def build_billing_workbook(year, month, rows, codes=None):
    """Assemble the workbook for `year`/`month` from BillingRows.

    `codes` is {plan: (sadc_code, trans_code)} from the Access Codes
    table (db.get_billing_codes). Plans missing from it — including
    everything when the table couldn't be read and None is passed —
    show '????' in columns H/I."""
    codes = codes or {}
    lay = _make_layout(year, month)

    wb = Workbook()
    # openpyxl's default theme is the old Office 2007 palette; without
    # this, every theme-indexed fill below renders the wrong color
    # (purple Sundays, orange headers). See office_theme.py.
    wb.loaded_theme = OFFICE_THEME_XML
    ws = wb.active
    ws.title = "Sheet1"
    ws.sheet_view.zoomScale = 70
    ws.sheet_format.defaultRowHeight = _ROW_HEIGHT
    ws.sheet_format.defaultColWidth = 9.0
    for col, width in _COLUMN_WIDTHS.items():
        ws.column_dimensions[get_column_letter(col)].width = width
    for col in range(DAY_FIRST_COL, lay.div_col + 1):
        ws.column_dimensions[get_column_letter(col)].width = _DAY_COL_WIDTH
    ws.column_dimensions[
        get_column_letter(lay.total_col)].width = _TOTAL_COL_WIDTH
    ws.column_dimensions[
        get_column_letter(lay.remark_col)].width = _REMARK_COL_WIDTH

    by_plan = {}
    for item in rows:
        by_plan.setdefault(item.plan, []).append(item)
    for members in by_plan.values():
        members.sort(key=lambda r: r.center_id)

    _write_day_headers(ws, 1, 2, year, month, lay)

    cursor = 3
    count_rows = {}
    for code, title in SECTIONS:
        members = by_plan.get(code, [])
        _write_title_row(ws, cursor, title)
        _write_section_header(ws, cursor + 1, year, month, lay)
        first = cursor + 3
        if members:
            for i, item in enumerate(members):
                _write_member_row(ws, first + i, first, item, lay,
                                  codes)
            last = first + len(members) - 1
            _write_total_row(ws, last + 1, first, last, lay)
            count_row = last + 2
        else:
            _write_blank_member_row(ws, first, lay)
            last = first
            count_row = last + 1      # empty sections have no total row
        _write_count_row(ws, count_row, code, first, last, lay)
        count_rows[code] = count_row
        cursor = count_row + 2        # skip the spacer row
    _write_bottom_summary(ws, cursor + 1, count_rows, lay)

    last_row = cursor + 1 + len(SECTIONS) + 1     # summary TOTAL row
    # Uniform row height across the sheet (the hand-made sheets set an
    # explicit height on every row).
    for r in range(1, last_row + 1):
        ws.row_dimensions[r].height = _ROW_HEIGHT
    # The reference styles the whole grid (spacer rows, title-row
    # leftovers, cells right of the tables) at Calibri 12 via row and
    # column styles; without this pass anything the user later types
    # in an untouched cell would come out Calibri 11.
    for excel_row in ws.iter_rows(min_row=1, max_row=last_row,
                                  min_col=1, max_col=lay.remark_col):
        for cell in excel_row:
            if cell.font.name != _FONT_NAME or cell.font.size != _FONT_SIZE:
                cell.font = _REGULAR
    return wb


def save_billing_workbook(wb, out_dir, year, month, billing_name,
                          on_fallback=None):
    """Save into `out_dir`; when the primary name is locked (open in
    Excel), retry `_1`..`_9` suffixes; `on_fallback(primary, actual)` is
    called once when a fallback is used. Raises PermissionError only
    when every candidate is locked. Returns the path written."""
    stem, ext = os.path.splitext(billing_filename(year, month, billing_name))
    primary = os.path.join(out_dir, f"{stem}{ext}")
    candidates = [primary] + [
        os.path.join(out_dir, f"{stem}_{n}{ext}") for n in range(1, 10)
    ]
    last_error = None
    for path in candidates:
        try:
            wb.save(path)
        except PermissionError as exc:
            last_error = exc
            continue
        if path != primary and on_fallback is not None:
            on_fallback(primary, path)
        return path
    raise last_error
