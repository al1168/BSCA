# -*- coding: utf-8 -*-
"""Tests for the aggregate billing-days workbook (billing_workbook.py).

Fixture month is June 2026: starts on a Monday, 30 days (so the day-31
slot AS is a purple strip) and Sundays fall on 7/14/21/28."""

from datetime import date, datetime

import pytest
from openpyxl import load_workbook

from monthly_schedule.billing_workbook import (
    SECTIONS,
    BillingRow,
    billing_filename,
    build_billing_workbook,
    collect_billing_row,
    format_absence_remarks,
    format_auth_days_dots,
    normalize_billing_plan,
    normalize_gender,
    parse_flex_date,
    save_billing_workbook,
)

YEAR, MONTH = 2026, 6
GREEN = "FF00B050"
TITLE_GREEN = "FF92D050"
PURPLE = "FF975CCB"


# --------------------------------------------------------------- helpers

def test_normalize_billing_plan_variants():
    assert normalize_billing_plan("HF") == "HF"
    assert normalize_billing_plan(" hf ") == "HF"
    assert normalize_billing_plan("Aetna") == "AE"
    assert normalize_billing_plan("Anthem") == "BCBS"
    assert normalize_billing_plan(" bcsb ") == "BCBS"
    assert normalize_billing_plan("") is None
    assert normalize_billing_plan(None) is None
    assert normalize_billing_plan("XYZ") is None


def test_normalize_gender():
    assert normalize_gender("M") == "M"
    assert normalize_gender("M/男") == "M"
    assert normalize_gender("女") == "F"
    assert normalize_gender("f") == "F"
    assert normalize_gender("") == ""
    assert normalize_gender(None) == ""


def test_format_auth_days_dots():
    assert format_auth_days_dots({5, 1, 3}) == "1.3.5"
    assert format_auth_days_dots(set()) == ""
    assert format_auth_days_dots({1, 9}) == "1"


def test_parse_flex_date():
    assert parse_flex_date(None) is None
    assert parse_flex_date("") is None
    assert parse_flex_date("  ") is None
    assert parse_flex_date(date(1953, 2, 1)) == date(1953, 2, 1)
    assert parse_flex_date(datetime(1953, 2, 1)) == date(1953, 2, 1)
    assert parse_flex_date("2/1/1953") == date(1953, 2, 1)
    assert parse_flex_date("1953-02-01") == date(1953, 2, 1)
    # garbage seen in the live DB stays visible as raw text
    assert parse_flex_date("4/1/20167") == "4/1/20167"


def test_billing_filename():
    assert billing_filename(2026, 6, "Jane Doe") == (
        "6. June 2026 billing Jane Doe.xlsx"
    )


# ------------------------------------------------- format_absence_remarks

def _absence(leave_type, start, end=None):
    return {"id": 1, "center_id": 1, "leave_type": leave_type,
            "start_date": start, "end_date": end or start}


def test_format_absence_remarks_range():
    text = format_absence_remarks([
        _absence("Vacation", date(2026, 3, 15), date(2026, 4, 15)),
    ])
    assert text == "Vacation 03-15-2026 - 04-15-2026"


def test_format_absence_remarks_single_day():
    text = format_absence_remarks([
        _absence("Doctor visit", date(2026, 4, 15)),
    ])
    assert text == "Doctor visit 04-15-2026"


def test_format_absence_remarks_joins_entries():
    text = format_absence_remarks([
        _absence("Vacation", date(2026, 3, 15), date(2026, 4, 15)),
        _absence("Doctor visit", date(2026, 4, 20)),
    ])
    assert text == (
        "Vacation 03-15-2026 - 04-15-2026, Doctor visit 04-20-2026"
    )


def test_format_absence_remarks_blank_leave_type():
    assert format_absence_remarks([
        _absence(None, date(2026, 4, 15)),
    ]) == "04-15-2026"
    assert format_absence_remarks([
        _absence("  ", date(2026, 4, 1), date(2026, 4, 3)),
    ]) == "04-01-2026 - 04-03-2026"


def test_format_absence_remarks_empty():
    assert format_absence_remarks([]) == ""


# --------------------------------------------------- collect_billing_row

class _FakeCtx:
    """Enrolled all month; authorized Mon/Wed/Fri via auth_days text."""

    def __init__(self, auth_days="1,3,5",
                 auth_end=date(2026, 7, 31),
                 member_id="134972571", absences=(),
                 enrollment_start=date(2024, 12, 1),
                 plan_type="MAP"):
        self._auth = {"auth_days": auth_days, "auth_end": auth_end,
                      "member_id": member_id, "plan_type": plan_type}
        self._absences = list(absences)
        self._enrollment_start = enrollment_start
        self.absences_asked = None

    def is_enrolled(self, day):
        return True

    def earliest_enrollment_start(self):
        return self._enrollment_start

    def active_authorization(self, day):
        return self._auth

    def absences_overlapping(self, start, end):
        self.absences_asked = (start, end)
        return self._absences


def _member(plan="HF"):
    return {
        "center_id": 24128,
        "last_name": "Luo",
        "first_name": "Dezhi",
        "health_plan": plan,
    }


def _timesheet_rows(days, missing=()):
    """Rows shaped like rows.build_rows output: scheduled days have a
    time_in, others ''."""
    out = []
    for d in days:
        out.append({
            "date": date(YEAR, MONTH, d),
            "time_in": "" if d in missing else "09:00",
        })
    return out


MWF_JUNE = [1, 3, 5, 8, 10, 12, 15, 17, 19, 22, 24, 26, 29]


def test_collect_billing_row_greens_and_ones():
    extra = {"gender": "M/男", "dob": "8/1/1947", "medicaid": " SA84152W "}
    row = collect_billing_row(
        _member(), _FakeCtx(), extra,
        _timesheet_rows(MWF_JUNE, missing={10}),
        {1, 3, 5}, YEAR, MONTH,
    )
    assert row.plan == "HF"
    assert row.plan_type == "MAP"
    assert row.name == "Luo, Dezhi"
    assert row.gender == "M"
    assert row.dob == date(1947, 8, 1)
    assert row.registered == date(2024, 12, 1)
    assert row.medicaid == "SA84152W"
    assert row.num_days == 3
    assert row.auth_days_text == "1.3.5"
    assert row.auth_end == date(2026, 7, 31)
    # Plan ID: Member ID of the latest auth active in the month
    assert row.plan_id == "134972571"
    assert row.green_days == frozenset(MWF_JUNE)
    # absent Jun 10: green but no 1
    assert row.one_days == frozenset(set(MWF_JUNE) - {10})
    assert row.remarks == ""


def test_collect_billing_row_null_member_id():
    row = collect_billing_row(
        _member(), _FakeCtx(member_id=None), {},
        _timesheet_rows(MWF_JUNE), {1, 3, 5}, YEAR, MONTH,
    )
    assert row.plan_id == ""


def test_collect_billing_row_null_plan_type():
    row = collect_billing_row(
        _member(), _FakeCtx(plan_type=None), {},
        _timesheet_rows(MWF_JUNE), {1, 3, 5}, YEAR, MONTH,
    )
    assert row.plan_type == ""


def test_collect_billing_row_remarks_from_month_absences():
    ctx = _FakeCtx(absences=[
        _absence("Vacation", date(2026, 5, 20), date(2026, 6, 10)),
        _absence("Doctor visit", date(2026, 6, 15)),
    ])
    row = collect_billing_row(
        _member(), ctx, {},
        _timesheet_rows(MWF_JUNE), {1, 3, 5}, YEAR, MONTH,
    )
    # asked for exactly the billing month, full ranges kept in the text
    assert ctx.absences_asked == (date(2026, 6, 1), date(2026, 6, 30))
    assert row.remarks == (
        "Vacation 05-20-2026 - 06-10-2026, Doctor visit 06-15-2026"
    )


def test_collect_billing_row_unmapped_plan_returns_none():
    row = collect_billing_row(
        _member(plan="Mystery"), _FakeCtx(), {},
        _timesheet_rows(MWF_JUNE), {1, 3, 5}, YEAR, MONTH,
    )
    assert row is None


def test_collect_billing_row_empty_extra():
    row = collect_billing_row(
        _member(), _FakeCtx(enrollment_start=None), {},
        _timesheet_rows(MWF_JUNE), {1, 3, 5}, YEAR, MONTH,
    )
    assert row.gender == ""
    assert row.dob is None
    assert row.registered is None
    assert row.medicaid == ""


def test_collect_billing_row_registered_from_enrollment_not_admission():
    # Contacts.[Admission Date] is ignored even when present; the
    # earliest Enrollment start_date is what prints in column G.
    extra = {"admission_date": "12/1/2024"}
    row = collect_billing_row(
        _member(), _FakeCtx(enrollment_start=date(2026, 7, 22)), extra,
        _timesheet_rows(MWF_JUNE), {1, 3, 5}, YEAR, MONTH,
    )
    assert row.registered == date(2026, 7, 22)


# ----------------------------------------------------- workbook geometry

def _row(center_id, plan, green, ones, remarks="", plan_id="134972571"):
    return BillingRow(
        center_id=center_id,
        name="Last, First",
        gender="F",
        dob=date(1950, 1, 28),
        registered=date(2026, 5, 7),
        medicaid="SP29056H",
        plan=plan,
        plan_type="MAP",
        num_days=3,
        auth_end=date(2027, 4, 30),
        auth_days_text="1.3.5",
        green_days=frozenset(green),
        one_days=frozenset(ones),
        remarks=remarks,
        plan_id=plan_id,
    )


VACATION_REMARK = "Vacation 05-20-2026 - 06-10-2026"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Two AE members + one HF member; every other plan empty. Saved
    and re-loaded so we assert what Excel will actually see."""
    rows = [
        _row(25102, "AE", MWF_JUNE, set(MWF_JUNE) - {10}),
        # sorts first by ID; carries a remark
        _row(24128, "AE", MWF_JUNE, MWF_JUNE, remarks=VACATION_REMARK),
        _row(24031, "HF", [7, 14, 21, 28], [7, 14, 21]),  # Sundays
    ]
    wb = build_billing_workbook(
        YEAR, MONTH, rows,
        codes={"AE": ("S5102", "A0110"), "HF": ("S5105", "T2003")},
    )
    path = tmp_path_factory.mktemp("billing") / "out.xlsx"
    wb.save(path)
    return load_workbook(path)


def _expected_layout(counts):
    """Replicate the row bookkeeping: {code: (first, last, count_row)}
    plus the bottom summary header row."""
    cursor = 3
    layout = {}
    for code, _title in SECTIONS:
        n = counts.get(code, 0)
        first = cursor + 3
        if n:
            last = first + n - 1
            count_row = last + 2
        else:
            last = first
            count_row = last + 1
        layout[code] = (first, last, count_row)
        cursor = count_row + 2
    return layout, cursor + 1


COUNTS = {"AE": 2, "HF": 1}

HEADERS = [
    "Number", "ID #", "NAME", "MLTC HEALTH PLAN", "PLAN TYPE", "DOB",
    "GENDER", "ENROLLMENT DATE", "PLAN ID", "MEDICAID", "SADC CODE",
    "TRANSPTATION  CODE", "No. Days", "AUTH EXPIRATION DATE",
    "AUTH.  DAYS",
]


def test_section_geometry(built):
    ws = built["Sheet1"]
    layout, summary_row = _expected_layout(COUNTS)
    merges = {str(m) for m in ws.merged_cells.ranges}

    # AE section at the top
    first, last, count_row = layout["AE"]
    assert (first, last, count_row) == (6, 7, 9)
    assert ws["Q3"].value == "AETNA-AE"
    assert "Q3:S3" in merges
    assert ws["T3"].value.startswith('= CHOOSE((MONTH(P$1)), "January\'"')
    for col in "ABCDEFGHIJKLMNO":
        assert f"{col}4:{col}5" in merges
    assert "AU4:AU5" in merges and "AV4:AV5" in merges
    for col, label in zip("ABCDEFGHIJKLMNO", HEADERS):
        assert ws[f"{col}4"].value == label
    assert ws["AU4"].value == "Total" and ws["AV4"].value == "Remark"
    assert ws["P4"].value == datetime(2026, 6, 1)
    assert ws["P4"].number_format == "d"
    assert ws["P5"].value == '=TEXT(P4, "ddd")'
    # top strip above section 1
    assert ws["P1"].value == datetime(2026, 6, 1)
    assert ws["P2"].value == '=TEXT(P1, "ddd")'

    # members sorted by ID; formulas
    assert ws["B6"].value == 24128 and ws["B7"].value == 25102
    assert ws["A6"].value == "=ROW()-5"
    assert ws["D6"].value == "AE"             # MLTC HEALTH PLAN code
    assert ws["E6"].value == "MAP"            # PLAN TYPE (auth Plan Type)
    assert ws["I6"].value == "134972571"      # PLAN ID (auth Member ID)
    assert ws["AU6"].value == "=SUM(P6:AT6)"
    assert ws["AV6"].value == VACATION_REMARK
    assert ws["AV7"].value is None            # no absences -> blank
    # total + count rows
    assert ws["AU8"].value == "=SUM(AU6:AU7)"
    assert ws["A9"].value == "AE"
    assert ws["B9"].value == "=COUNT(B6:B7)"
    assert ws["F9"].value == "Member with authorization"
    assert "F9:H9" in merges
    assert ws["P9"].value == "=SUM(P6:P7)"
    assert ws["AU9"].value == "=SUM(P9:AT9)"

    # empty section right after (BCBS): 6-row block, no total row
    first, last, count_row = layout["BCBS"]
    assert ws[f"Q{first - 3}"].value == "Anthem-BCBS"
    assert ws[f"A{first}"].value == 1
    assert ws[f"AU{first}"].value == f"=SUM(P{first}:AT{first})"
    assert ws[f"B{count_row}"].value == f"=COUNT(B{first}:B{first})"

    # every section title in place
    for (code, title) in SECTIONS:
        f, _l, _c = layout[code]
        assert ws[f"Q{f - 3}"].value == title


def test_bottom_summary(built):
    ws = built["Sheet1"]
    layout, summary_row = _expected_layout(COUNTS)
    assert ws[f"D{summary_row}"].value == "MLTC"
    assert ws[f"E{summary_row}"].value == "会员数"
    assert ws[f"F{summary_row}"].value == "授权天数"
    row = summary_row + 1
    for code, _title in SECTIONS:
        _f, _l, count_row = layout[code]
        assert ws[f"D{row}"].value == code
        assert ws[f"E{row}"].value == f"=B{count_row}"
        assert ws[f"F{row}"].value == f"=AU{count_row}"
        row += 1
    assert ws[f"D{row}"].value == "TOTAL"
    assert ws[f"E{row}"].value == f"=SUM(E{summary_row + 1}:E{row - 1})"
    assert ws[f"F{row}"].value == f"=SUM(F{summary_row + 1}:F{row - 1})"


def _fill_of(cell):
    fill = cell.fill
    if not fill or fill.patternType != "solid":
        return None
    fg = fill.fgColor
    if fg.type == "rgb":
        return fg.rgb
    return (fg.theme, round(fg.tint, 2))


def test_day_cell_semantics(built):
    ws = built["Sheet1"]
    # member row 6 (24128, MWF, no absence): Jun 1 = P6 green with 1
    assert _fill_of(ws["P6"]) == GREEN and ws["P6"].value == 1
    # Jun 2 (Q6): not authorized -> no fill, no value
    assert _fill_of(ws["Q6"]) is None and ws["Q6"].value is None
    # row 7 (25102, absent Jun 10 = Y7): green but empty
    assert _fill_of(ws["Y7"]) == GREEN and ws["Y7"].value is None
    # Sunday strip: Jun 7 = V column, unauthorized member rows get tint
    theme, tint = _fill_of(ws["V6"])
    assert theme == 7 and tint == pytest.approx(0.6, abs=0.01)
    # green wins over Sunday for the HF Sunday member
    layout, _ = _expected_layout(COUNTS)
    hf_first, _l, _c = layout["HF"]
    assert _fill_of(ws[f"V{hf_first}"]) == GREEN
    assert ws[f"V{hf_first}"].value == 1
    assert ws[f"AJ{hf_first}"].value == 1          # Jun 21
    assert ws[f"AQ{hf_first}"].value is None       # Jun 28 absent, green
    assert _fill_of(ws[f"AQ{hf_first}"]) == GREEN
    # trailing day-31 slot AT is purple on strip/header/member rows
    for addr in ("AT1", "AT4", "AT6"):
        assert _fill_of(ws[addr]) == PURPLE
    # date headers gold; Sundays darker
    assert _fill_of(ws["P4"]) == (7, pytest.approx(0.8, abs=0.01))
    assert _fill_of(ws["V4"]) == (7, pytest.approx(0.6, abs=0.01))


def test_styles(built):
    ws = built["Sheet1"]
    assert ws.sheet_view.zoomScale == 70
    assert ws.sheet_format.defaultRowHeight == pytest.approx(24.8)
    assert ws.row_dimensions[6].height == pytest.approx(24.8)
    assert ws.column_dimensions["A"].width == pytest.approx(5.625, abs=0.01)
    assert ws.column_dimensions["C"].width == 18.5
    assert ws.column_dimensions["D"].width == pytest.approx(8.0, abs=0.01)
    assert ws.column_dimensions["E"].width == pytest.approx(8.0, abs=0.01)
    assert ws.column_dimensions["F"].width == pytest.approx(11.625, abs=0.01)
    assert ws.column_dimensions["G"].width == pytest.approx(7.0, abs=0.01)
    assert ws.column_dimensions["H"].width == pytest.approx(12.125, abs=0.01)
    assert ws.column_dimensions["I"].width == pytest.approx(13.75, abs=0.01)
    assert ws.column_dimensions["O"].width == pytest.approx(13.75, abs=0.01)
    assert ws.column_dimensions["P"].width == pytest.approx(4.625, abs=0.01)
    assert ws.column_dimensions["AT"].width == pytest.approx(4.625, abs=0.01)
    assert ws.column_dimensions["AU"].width == pytest.approx(6.625, abs=0.01)
    assert ws.column_dimensions["AV"].width == 61.25
    # fonts: Calibri 12 everywhere, bold headers / regular demographics
    assert ws["A4"].font.name == "Calibri"
    assert ws["A4"].font.size == 12
    assert ws["A4"].font.bold
    assert ws["G6"].font.bold is not True
    assert ws["B6"].font.bold and ws["C6"].font.bold
    assert ws["P6"].font.bold
    # number formats
    assert ws["F6"].number_format == "mm-dd-yy"
    assert ws["H6"].number_format == "mm-dd-yy"
    assert ws["N6"].number_format == "mm-dd-yy"
    assert ws["O6"].number_format == "@"
    # section title fill
    assert _fill_of(ws["Q3"]) == TITLE_GREEN
    # total/count row fills
    assert _fill_of(ws["A8"]) == (9, pytest.approx(0.8, abs=0.01))
    assert _fill_of(ws["P9"]) == (3, pytest.approx(0.8, abs=0.01))
    assert _fill_of(ws["B9"]) == (0, 0.0)


def test_divider_layout_31_day_month():
    """July has 31 days: the purple divider must still separate the
    days from Total (everything shifts one column right vs June)."""
    wb = build_billing_workbook(
        2026, 7, [_row(1, "AE", [1, 31], [1, 31])],
        codes={"AE": ("S5102", "A0110")},
    )
    ws = wb["Sheet1"]
    assert ws["AT4"].value == datetime(2026, 7, 31)   # day 31 is a day
    assert ws["AU4"].value is None                    # divider
    assert _fill_of(ws["AU6"]) == PURPLE
    assert _fill_of(ws["AU1"]) == PURPLE
    assert ws["AV4"].value == "Total"
    assert ws["AV6"].value == "=SUM(P6:AU6)"
    assert ws["AW4"].value == "Remark"
    assert ws["AT6"].value == 1                       # scheduled Jul 31
    assert ws.column_dimensions["AU"].width == pytest.approx(4.625,
                                                             abs=0.01)
    assert ws.column_dimensions["AV"].width == pytest.approx(6.625,
                                                             abs=0.01)
    assert ws.column_dimensions["AW"].width == 61.25


def test_divider_layout_february():
    """28-day month: divider right after Feb 28 (col AQ)."""
    wb = build_billing_workbook(2026, 2, [_row(1, "AE", [2], [2])])
    ws = wb["Sheet1"]
    assert ws["AQ4"].value == datetime(2026, 2, 28)   # last day col
    assert _fill_of(ws["AR6"]) == PURPLE              # divider
    assert ws["AS4"].value == "Total"
    assert ws["AT4"].value == "Remark"
    assert ws["AS6"].value == "=SUM(P6:AR6)"


def test_codes_from_lookup_table(built):
    """K/L come from the codes mapping (the Access Codes table)."""
    ws = built["Sheet1"]
    assert ws["K6"].value == "S5102" and ws["L6"].value == "A0110"
    layout, _ = _expected_layout(COUNTS)
    hf_first, _l, _c = layout["HF"]
    assert ws[f"K{hf_first}"].value == "S5105"
    assert ws[f"L{hf_first}"].value == "T2003"


def test_codes_missing_plan_shows_question_marks(tmp_path):
    """A plan absent from the Codes table (or no table at all) renders
    '????' in both code columns so the gap is visible."""
    wb = build_billing_workbook(
        YEAR, MONTH, [_row(1, "AE", MWF_JUNE, MWF_JUNE)],
        codes={"HF": ("S5105", "T2003")},
    )
    ws = wb["Sheet1"]
    assert ws["K6"].value == "????" and ws["L6"].value == "????"
    wb2 = build_billing_workbook(
        YEAR, MONTH, [_row(1, "AE", MWF_JUNE, MWF_JUNE)]
    )
    ws2 = wb2["Sheet1"]
    assert ws2["K6"].value == "????" and ws2["L6"].value == "????"


# ----------------------------------------------------------------- save

def test_save_billing_workbook_fallback(tmp_path):
    wb = build_billing_workbook(YEAR, MONTH, [])
    primary = billing_filename(YEAR, MONTH, "Jane Doe")
    (tmp_path / primary).mkdir()      # lock the primary name
    fallbacks = []
    path = save_billing_workbook(
        wb, str(tmp_path), YEAR, MONTH, "Jane Doe",
        on_fallback=lambda p, a: fallbacks.append((p, a)),
    )
    stem = primary[:-len(".xlsx")]
    assert path.endswith(f"{stem}_1.xlsx")
    assert (tmp_path / f"{stem}_1.xlsx").exists()
    assert len(fallbacks) == 1


def test_save_billing_workbook_all_locked(tmp_path):
    wb = build_billing_workbook(YEAR, MONTH, [])
    stem = billing_filename(YEAR, MONTH, "Jane Doe")[:-len(".xlsx")]
    (tmp_path / f"{stem}.xlsx").mkdir()
    for n in range(1, 10):
        (tmp_path / f"{stem}_{n}.xlsx").mkdir()
    with pytest.raises(PermissionError):
        save_billing_workbook(wb, str(tmp_path), YEAR, MONTH, "Jane Doe")


def test_workbook_carries_modern_office_theme(tmp_path):
    """openpyxl's default theme is the old 2007 palette (accent4 purple,
    accent6 orange); the builder must embed the Office 2013+ theme or
    every theme-indexed fill renders the wrong color (regression: the
    first shipped build had purple Sundays and orange headers)."""
    import re
    import zipfile

    wb = build_billing_workbook(YEAR, MONTH, [])
    path = tmp_path / "theme.xlsx"
    wb.save(path)
    theme = zipfile.ZipFile(path).read("xl/theme/theme1.xml").decode()
    for name, want in (("accent4", "FFC000"), ("accent6", "70AD47"),
                       ("dk2", "44546A"), ("accent1", "4472C4")):
        got = re.search(
            rf'<a:{name}><a:srgbClr val="([0-9A-Fa-f]{{6}})"', theme
        ).group(1)
        assert got == want, f"{name}: {got} != {want}"
