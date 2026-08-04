# -*- coding: utf-8 -*-
"""Tests for the aggregate billing-days workbook (billing_workbook.py).

Fixture month is June 2026: starts on a Monday, 30 days (so the day-31
slot AQ is a purple strip) and Sundays fall on 7/14/21/28."""

from datetime import date, datetime

import pytest
from openpyxl import load_workbook

from monthly_schedule.billing_workbook import (
    SECTIONS,
    BillingRow,
    billing_filename,
    build_billing_workbook,
    collect_billing_row,
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
    assert billing_filename(2026, 6) == (
        "6. June 2026 Member Attendance-Bowery.xlsx"
    )


# --------------------------------------------------- collect_billing_row

class _FakeCtx:
    """Enrolled all month; authorized Mon/Wed/Fri via auth_days text."""

    def __init__(self, auth_days="1,3,5",
                 auth_end=date(2026, 7, 31)):
        self._auth = {"auth_days": auth_days, "auth_end": auth_end}

    def is_enrolled(self, day):
        return True

    def active_authorization(self, day):
        return self._auth


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
    extra = {"gender": "M/男", "dob": "8/1/1947",
             "admission_date": "12/1/2024", "medicaid": " SA84152W "}
    row = collect_billing_row(
        _member(), _FakeCtx(), extra,
        _timesheet_rows(MWF_JUNE, missing={10}),
        {1, 3, 5}, YEAR, MONTH,
    )
    assert row.plan == "HF"
    assert row.name == "Luo, Dezhi"
    assert row.gender == "M"
    assert row.dob == date(1947, 8, 1)
    assert row.registered == date(2024, 12, 1)
    assert row.medicaid == "SA84152W"
    assert row.num_days == 3
    assert row.auth_days_text == "1.3.5"
    assert row.auth_end == date(2026, 7, 31)
    assert row.green_days == frozenset(MWF_JUNE)
    # absent Jun 10: green but no 1
    assert row.one_days == frozenset(set(MWF_JUNE) - {10})


def test_collect_billing_row_unmapped_plan_returns_none():
    row = collect_billing_row(
        _member(plan="Mystery"), _FakeCtx(), {},
        _timesheet_rows(MWF_JUNE), {1, 3, 5}, YEAR, MONTH,
    )
    assert row is None


def test_collect_billing_row_empty_extra():
    row = collect_billing_row(
        _member(), _FakeCtx(), {},
        _timesheet_rows(MWF_JUNE), {1, 3, 5}, YEAR, MONTH,
    )
    assert row.gender == ""
    assert row.dob is None
    assert row.registered is None
    assert row.medicaid == ""


# ----------------------------------------------------- workbook geometry

def _row(center_id, plan, green, ones):
    return BillingRow(
        center_id=center_id,
        name="Last, First",
        gender="F",
        dob=date(1950, 1, 28),
        registered=date(2026, 5, 7),
        medicaid="SP29056H",
        plan=plan,
        num_days=3,
        auth_end=date(2027, 4, 30),
        auth_days_text="1.3.5",
        green_days=frozenset(green),
        one_days=frozenset(ones),
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Two AE members + one HF member; every other plan empty. Saved
    and re-loaded so we assert what Excel will actually see."""
    rows = [
        _row(25102, "AE", MWF_JUNE, set(MWF_JUNE) - {10}),
        _row(24128, "AE", MWF_JUNE, MWF_JUNE),   # sorts first by ID
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


def test_section_geometry(built):
    ws = built["Sheet1"]
    layout, summary_row = _expected_layout(COUNTS)
    merges = {str(m) for m in ws.merged_cells.ranges}

    # AE section at the top
    first, last, count_row = layout["AE"]
    assert (first, last, count_row) == (6, 7, 9)
    assert ws["N3"].value == "AETNA-AE"
    assert "N3:P3" in merges
    assert ws["Q3"].value.startswith('= CHOOSE((MONTH(M$1)), "January\'"')
    for col in "ABCDEFGHIJKL":
        assert f"{col}4:{col}5" in merges
    assert "AR4:AR5" in merges and "AS4:AS5" in merges
    assert ws["A4"].value == "Number"
    assert ws["I4"].value == "TRANSPTATION  CODE"
    assert ws["L4"].value == "AUTH.  DAYS"
    assert ws["AR4"].value == "Total" and ws["AS4"].value == "Remark"
    assert ws["M4"].value == datetime(2026, 6, 1)
    assert ws["M4"].number_format == "d"
    assert ws["M5"].value == '=TEXT(M4, "ddd")'
    # top strip above section 1
    assert ws["M1"].value == datetime(2026, 6, 1)
    assert ws["M2"].value == '=TEXT(M1, "ddd")'

    # members sorted by ID; formulas
    assert ws["B6"].value == 24128 and ws["B7"].value == 25102
    assert ws["A6"].value == "=ROW()-5"
    assert ws["AR6"].value == "=SUM(M6:AQ6)"
    assert ws["AS6"].value is None            # Remark left blank
    # total + count rows
    assert ws["AR8"].value == "=SUM(AR6:AR7)"
    assert ws["A9"].value == "AE"
    assert ws["B9"].value == "=COUNT(B6:B7)"
    assert ws["E9"].value == "Member with authorization"
    assert "E9:G9" in merges
    assert ws["M9"].value == "=SUM(M6:M7)"
    assert ws["AR9"].value == "=SUM(M9:AQ9)"

    # empty section right after (BCBS): 6-row block, no total row
    first, last, count_row = layout["BCBS"]
    assert ws[f"N{first - 3}"].value == "Anthem-BCBS"
    assert ws[f"A{first}"].value == 1
    assert ws[f"AR{first}"].value == f"=SUM(M{first}:AQ{first})"
    assert ws[f"B{count_row}"].value == f"=COUNT(B{first}:B{first})"

    # every section title in place
    for (code, title) in SECTIONS:
        f, _l, _c = layout[code]
        assert ws[f"N{f - 3}"].value == title


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
        assert ws[f"F{row}"].value == f"=AR{count_row}"
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
    # member row 6 (24128, MWF, no absence): Jun 1 = M6 green with 1
    assert _fill_of(ws["M6"]) == GREEN and ws["M6"].value == 1
    # Jun 2 (N6): not authorized -> no fill, no value
    assert _fill_of(ws["N6"]) is None and ws["N6"].value is None
    # row 7 (25102, absent Jun 10 = V7): green but empty
    assert _fill_of(ws["V7"]) == GREEN and ws["V7"].value is None
    # Sunday strip: Jun 7 = S column, unauthorized member rows get tint
    theme, tint = _fill_of(ws["S6"])
    assert theme == 7 and tint == pytest.approx(0.6, abs=0.01)
    # green wins over Sunday for the HF Sunday member
    layout, _ = _expected_layout(COUNTS)
    hf_first, _l, _c = layout["HF"]
    assert _fill_of(ws[f"S{hf_first}"]) == GREEN
    assert ws[f"S{hf_first}"].value == 1
    assert ws[f"AG{hf_first}"].value == 1          # Jun 21
    assert ws[f"AN{hf_first}"].value is None       # Jun 28 absent, green
    assert _fill_of(ws[f"AN{hf_first}"]) == GREEN
    # trailing day-31 slot AQ is purple on strip/header/member rows
    for addr in ("AQ1", "AQ4", "AQ6"):
        assert _fill_of(ws[addr]) == PURPLE
    # date headers gold; Sundays darker
    assert _fill_of(ws["M4"]) == (7, pytest.approx(0.8, abs=0.01))
    assert _fill_of(ws["S4"]) == (7, pytest.approx(0.6, abs=0.01))


def test_styles(built):
    ws = built["Sheet1"]
    assert ws.sheet_view.zoomScale == 70
    assert ws.sheet_format.defaultRowHeight == pytest.approx(24.8)
    assert ws.row_dimensions[6].height == pytest.approx(24.8)
    assert ws.column_dimensions["A"].width == pytest.approx(5.625, abs=0.01)
    assert ws.column_dimensions["C"].width == 18.5
    assert ws.column_dimensions["M"].width == pytest.approx(4.625, abs=0.01)
    assert ws.column_dimensions["AQ"].width == pytest.approx(4.625, abs=0.01)
    assert ws.column_dimensions["AR"].width == pytest.approx(6.625, abs=0.01)
    assert ws.column_dimensions["AS"].width == 61.25
    # fonts: Calibri 12 everywhere, bold headers / regular demographics
    assert ws["A4"].font.name == "Calibri"
    assert ws["A4"].font.size == 12
    assert ws["A4"].font.bold
    assert ws["D6"].font.bold is not True
    assert ws["B6"].font.bold and ws["C6"].font.bold
    assert ws["M6"].font.bold
    # number formats
    assert ws["E6"].number_format == "mm-dd-yy"
    assert ws["F6"].number_format == "mm-dd-yy"
    assert ws["K6"].number_format == "mm-dd-yy"
    assert ws["L6"].number_format == "@"
    # section title fill
    assert _fill_of(ws["N3"]) == TITLE_GREEN
    # total/count row fills
    assert _fill_of(ws["A8"]) == (9, pytest.approx(0.8, abs=0.01))
    assert _fill_of(ws["M9"]) == (3, pytest.approx(0.8, abs=0.01))
    assert _fill_of(ws["B9"]) == (0, 0.0)


def test_divider_layout_31_day_month():
    """July has 31 days: the purple divider must still separate the
    days from Total (everything shifts one column right vs June)."""
    wb = build_billing_workbook(
        2026, 7, [_row(1, "AE", [1, 31], [1, 31])],
        codes={"AE": ("S5102", "A0110")},
    )
    ws = wb["Sheet1"]
    assert ws["AQ4"].value == datetime(2026, 7, 31)   # day 31 is a day
    assert ws["AR4"].value is None                    # divider
    assert _fill_of(ws["AR6"]) == PURPLE
    assert _fill_of(ws["AR1"]) == PURPLE
    assert ws["AS4"].value == "Total"
    assert ws["AS6"].value == "=SUM(M6:AR6)"
    assert ws["AT4"].value == "Remark"
    assert ws["AQ6"].value == 1                       # scheduled Jul 31
    assert ws.column_dimensions["AR"].width == pytest.approx(4.625,
                                                             abs=0.01)
    assert ws.column_dimensions["AS"].width == pytest.approx(6.625,
                                                             abs=0.01)
    assert ws.column_dimensions["AT"].width == 61.25


def test_divider_layout_february():
    """28-day month: divider right after Feb 28 (col AO)."""
    wb = build_billing_workbook(2026, 2, [_row(1, "AE", [2], [2])])
    ws = wb["Sheet1"]
    assert ws["AN4"].value == datetime(2026, 2, 28)   # last day col
    assert _fill_of(ws["AO6"]) == PURPLE              # divider
    assert ws["AP4"].value == "Total"
    assert ws["AQ4"].value == "Remark"
    assert ws["AP6"].value == "=SUM(M6:AO6)"


def test_codes_from_lookup_table(built):
    """H/I come from the codes mapping (the Access Codes table)."""
    ws = built["Sheet1"]
    assert ws["H6"].value == "S5102" and ws["I6"].value == "A0110"
    layout, _ = _expected_layout(COUNTS)
    hf_first, _l, _c = layout["HF"]
    assert ws[f"H{hf_first}"].value == "S5105"
    assert ws[f"I{hf_first}"].value == "T2003"


def test_codes_missing_plan_shows_question_marks(tmp_path):
    """A plan absent from the Codes table (or no table at all) renders
    '????' in both code columns so the gap is visible."""
    wb = build_billing_workbook(
        YEAR, MONTH, [_row(1, "AE", MWF_JUNE, MWF_JUNE)],
        codes={"HF": ("S5105", "T2003")},
    )
    ws = wb["Sheet1"]
    assert ws["H6"].value == "????" and ws["I6"].value == "????"
    wb2 = build_billing_workbook(
        YEAR, MONTH, [_row(1, "AE", MWF_JUNE, MWF_JUNE)]
    )
    ws2 = wb2["Sheet1"]
    assert ws2["H6"].value == "????" and ws2["I6"].value == "????"


# ----------------------------------------------------------------- save

def test_save_billing_workbook_fallback(tmp_path):
    wb = build_billing_workbook(YEAR, MONTH, [])
    primary = billing_filename(YEAR, MONTH)
    (tmp_path / primary).mkdir()      # lock the primary name
    fallbacks = []
    path = save_billing_workbook(
        wb, str(tmp_path), YEAR, MONTH,
        on_fallback=lambda p, a: fallbacks.append((p, a)),
    )
    stem = primary[:-len(".xlsx")]
    assert path.endswith(f"{stem}_1.xlsx")
    assert (tmp_path / f"{stem}_1.xlsx").exists()
    assert len(fallbacks) == 1


def test_save_billing_workbook_all_locked(tmp_path):
    wb = build_billing_workbook(YEAR, MONTH, [])
    stem = billing_filename(YEAR, MONTH)[:-len(".xlsx")]
    (tmp_path / f"{stem}.xlsx").mkdir()
    for n in range(1, 10):
        (tmp_path / f"{stem}_{n}.xlsx").mkdir()
    with pytest.raises(PermissionError):
        save_billing_workbook(wb, str(tmp_path), YEAR, MONTH)


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
