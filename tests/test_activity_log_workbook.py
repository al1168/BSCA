# -*- coding: utf-8 -*-
"""Tests for the per-member Bowery activity log workbook."""

import calendar
import datetime as dt
import os

import pytest
from openpyxl import load_workbook

from monthly_schedule.activity_log_workbook import (
    ABSENT_TEXT,
    CHECK_CHAR,
    GRAY_RGB,
    activity_log_filename,
    activity_log_subdir,
    build_activity_log,
    default_template_path,
    is_bowery_program,
    latest_auth_member_id,
    parse_frequency,
    pick_activity_columns,
    save_activity_log,
)
from monthly_schedule.eligibility_context import MemberContext

MEMBER = {
    "center_id": 25347,
    "last_name": "Chan",
    "first_name": "Mei",
    "health_plan": "AE",
}

# A1..A14 like the live Activities table; A6/A8 are weekend-only, A14
# has a blank frequency (never offered).
ACTIVITIES = {}
for _i in range(1, 15):
    ACTIVITIES[f"A{_i}"] = {
        "name": f"Activity {_i}",
        "c_name": f"活动{_i}",
        "frequency": "1.2.3.4.5.6.7",
    }
ACTIVITIES["A6"] = {"name": "Dance", "c_name": "舞蹈", "frequency": "6.7"}
ACTIVITIES["A8"] = {"name": "Taichi", "c_name": "太极", "frequency": "6.7"}
ACTIVITIES["A14"] = {"name": "Poker", "c_name": "打牌", "frequency": ""}


def make_rows(year, month, attended_weekdays=(1, 2, 3, 4),
              absent_days=(10,)):
    """Full-month rows with the status key build_rows now emits."""
    n_days = calendar.monthrange(year, month)[1]
    rows = []
    for d in range(1, n_days + 1):
        day = dt.date(year, month, d)
        if d in absent_days:
            status = "absent"
        elif day.isoweekday() in attended_weekdays:
            status = "attended"
        else:
            status = "ineligible"
        rows.append({"date": day, "day": "x", "status": status})
    return rows


# --- pure helpers -----------------------------------------------------


def test_parse_frequency_weekday_range():
    assert parse_frequency("1.2.3.4.5") == frozenset({1, 2, 3, 4, 5})


def test_parse_frequency_weekend_only():
    assert parse_frequency("6.7") == frozenset({6, 7})


def test_parse_frequency_blank_and_none():
    assert parse_frequency("") == frozenset()
    assert parse_frequency(None) == frozenset()


def test_parse_frequency_ignores_junk_tokens():
    assert parse_frequency("1.x.9. 3") == frozenset({1, 3})


def test_is_bowery_program_variations():
    assert is_bowery_program("Bowery")
    assert is_bowery_program("BOWERY SADC")
    assert is_bowery_program("  bowery senior care ")


def test_is_bowery_program_rejects_others():
    assert not is_bowery_program("")
    assert not is_bowery_program(None)
    assert not is_bowery_program("Chinatown")


def test_activity_log_filename():
    assert (activity_log_filename(25347, 2026, 6)
            == "(25347) Jun 2026 Activity log.xlsx")


def test_activity_log_subdir_normalizes_plan():
    assert (activity_log_subdir(2026, 6, " hf ")
            == os.path.join("Activity Logs 2026-06", "HF"))


def test_activity_log_subdir_no_plan():
    assert (activity_log_subdir(2026, 6, None)
            == os.path.join("Activity Logs 2026-06", "_NoPlan"))
    assert (activity_log_subdir(2026, 6, "  ")
            == os.path.join("Activity Logs 2026-06", "_NoPlan"))


def test_pick_activity_columns_two_to_four():
    day = dt.date(2026, 6, 1)  # Monday
    cols = pick_activity_columns(25347, day, ACTIVITIES)
    assert 2 <= len(cols) <= 4
    assert cols == sorted(cols)


def test_pick_activity_columns_deterministic():
    day = dt.date(2026, 6, 1)
    assert (pick_activity_columns(25347, day, ACTIVITIES)
            == pick_activity_columns(25347, day, ACTIVITIES))


def test_pick_activity_columns_respects_frequency():
    # A6 (col H=8), A8 (col J=10) are weekend-only; A14 (col P=16) never.
    for d in range(1, 6):  # Mon..Fri
        day = dt.date(2026, 6, d)
        cols = pick_activity_columns(25347, day, ACTIVITIES)
        assert 8 not in cols
        assert 10 not in cols
        assert 16 not in cols


def test_pick_activity_columns_clamps_to_available():
    # Weekend: only A6 and A8 offered.
    weekend_only = {
        "A6": ACTIVITIES["A6"],
        "A8": ACTIVITIES["A8"],
    }
    cols = pick_activity_columns(25347, dt.date(2026, 6, 6), weekend_only)
    assert cols == [8, 10]


def test_pick_activity_columns_no_available_activities():
    cols = pick_activity_columns(25347, dt.date(2026, 6, 1),
                                 {"A14": ACTIVITIES["A14"]})
    assert cols == []


def test_latest_auth_member_id_latest_wins():
    def auth(id_, start, end, member_id):
        return {"id": id_, "effective_start": start, "effective_end": end,
                "auth_days": "1.2.3", "member_id": member_id}

    ctx = MemberContext(
        [], [
            auth(1, dt.date(2026, 6, 1), dt.date(2026, 6, 14), "OLD123"),
            auth(2, dt.date(2026, 6, 15), dt.date(2026, 6, 30), "NEW456"),
        ], [], [], [],
    )
    assert latest_auth_member_id(ctx, 2026, 6) == "NEW456"


def test_latest_auth_member_id_no_auth():
    ctx = MemberContext([], [], [], [], [])
    assert latest_auth_member_id(ctx, 2026, 6) == ""


def test_default_template_path_unfrozen():
    path = default_template_path()
    assert path.endswith(os.path.join(
        "assets", "templates", "Bowery activity log template.xlsx"))
    assert os.path.exists(path)


def test_default_template_path_frozen(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "_MEIPASS", r"C:\frozen\base", raising=False)
    path = default_template_path()
    assert path.startswith(r"C:\frozen\base")


# --- full build (June 2026, 30 days) ----------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    rows = make_rows(2026, 6)
    wb = build_activity_log(MEMBER, rows, ACTIVITIES, 2026, 6,
                            dob="2/1/1953", member_id="AB12345C")
    out = tmp_path_factory.mktemp("activity") / "log.xlsx"
    wb.save(str(out))
    return load_workbook(str(out))


def test_header_placeholders_filled(built):
    ws = built["Sheet1"]
    assert ws["B3"].value == 25347
    assert ws["E3"].value == "Chan, Mei"
    assert ws["H3"].value == dt.datetime(1953, 2, 1)
    assert ws["K3"].value == "AE"
    assert ws["K3"].number_format == "General"
    assert ws["O3"].value == "AB12345C"


def test_header_unparseable_dob_kept_as_text():
    rows = make_rows(2026, 6)
    wb = build_activity_log(MEMBER, rows, ACTIVITIES, 2026, 6,
                            dob="4/1/20167", member_id="")
    assert wb["Sheet1"]["H3"].value == "4/1/20167"


def test_activity_header_rows(built):
    ws = built["Sheet1"]
    assert ws["C6"].value == "Activity 1"
    assert ws["C7"].value == "活动1"
    assert ws["H6"].value == "Dance"
    assert ws["H7"].value == "舞蹈"
    assert ws["P6"].value == "Poker"
    assert ws["P7"].value == "打牌"


def test_missing_activity_id_blanks_header():
    activities = dict(ACTIVITIES)
    del activities["A3"]
    rows = make_rows(2026, 6)
    ws = build_activity_log(MEMBER, rows, activities, 2026, 6)["Sheet1"]
    assert ws["E6"].value is None or ws["E6"].value == ""
    assert ws["E7"].value is None or ws["E7"].value == ""


def test_dates_rewritten_for_month(built):
    ws = built["Sheet1"]
    assert ws["A8"].value == dt.datetime(2026, 6, 1)
    assert ws["A37"].value == dt.datetime(2026, 6, 30)
    assert ws["A8"].number_format == "m/d/yyyy;@"
    assert ws["B8"].value == '=TEXT(A8,"ddd")'
    assert ws["B37"].value == '=TEXT(A37,"ddd")'


def test_attended_day_has_two_to_four_wingdings_checks(built):
    ws = built["Sheet1"]
    # 2026-06-01 is a Monday -> attended -> row 8.
    checks = [ws.cell(row=8, column=c) for c in range(3, 17)
              if ws.cell(row=8, column=c).value == CHECK_CHAR]
    assert 2 <= len(checks) <= 4
    for cell in checks:
        assert cell.font.name == "Wingdings"
        assert cell.font.size == 11
        assert cell.alignment.horizontal == "center"
        assert cell.alignment.vertical == "center"


def test_checks_centered_even_where_template_is_not():
    # The template's C37 cell carries no alignment; a check written
    # there (or in a 31-day month's cloned row 38) must still be
    # centered — the generator sets alignment itself.
    only_a1 = {"A1": {"name": "News", "c_name": "电视",
                      "frequency": "1.2.3.4.5.6.7"}}
    rows = make_rows(2026, 6, attended_weekdays=(1, 2, 3, 4, 5, 6, 7),
                     absent_days=())
    ws = build_activity_log(MEMBER, rows, only_a1, 2026, 6)["Sheet1"]
    for r in range(8, 38):  # every day attended -> C always checked
        cell = ws.cell(row=r, column=3)
        assert cell.value == CHECK_CHAR
        assert cell.alignment.horizontal == "center", cell.coordinate
        assert cell.alignment.vertical == "center", cell.coordinate


def test_checks_only_in_frequency_allowed_columns(built):
    ws = built["Sheet1"]
    for r in range(8, 38):
        day = ws.cell(row=r, column=1).value
        for c in (8, 10, 16):  # weekend-only / never-offered columns
            if day.isoweekday() <= 5:
                assert ws.cell(row=r, column=c).value != CHECK_CHAR


def test_absent_day_merged_label(built):
    ws = built["Sheet1"]
    # 2026-06-10 -> row 17.
    assert ws["C17"].value == ABSENT_TEXT
    assert "C17:P17" in {str(r) for r in ws.merged_cells.ranges}
    assert ws["C17"].font.name != "Wingdings"
    assert ws["C17"].alignment.horizontal == "center"
    assert ws["C17"].fill.fill_type != "solid"


def test_ineligible_day_gray_filled_full_row(built):
    ws = built["Sheet1"]
    # 2026-06-05 is a Friday -> ineligible -> row 12. The gray covers
    # the FULL row (date/week included), like the template's original
    # weekend look.
    for c in range(1, 17):
        cell = ws.cell(row=12, column=c)
        if c >= 3:
            assert cell.value in (None, "")
        assert cell.fill.fill_type == "solid"
        assert cell.fill.start_color.rgb == GRAY_RGB


def test_attended_day_not_gray(built):
    ws = built["Sheet1"]
    # 2026-06-01 (Monday, attended) -> row 8: no gray anywhere.
    for c in range(1, 17):
        assert ws.cell(row=8, column=c).fill.start_color.rgb != GRAY_RGB


def test_conditional_formatting_stripped(built):
    # The shipped template carried leftover weekend conditional-
    # formatting rules that fought the generator's explicit fills; the
    # build must remove every CF rule.
    assert len(list(built["Sheet1"].conditional_formatting)) == 0


def test_template_sample_check_cleared(built):
    # The shipped template has a sample "ü" in C8; 2026-06-01 row 8 is
    # attended, so C8 may only hold a freshly-drawn check.
    ws = built["Sheet1"]
    rows = make_rows(2026, 6, attended_weekdays=(), absent_days=())
    wb = build_activity_log(MEMBER, rows, ACTIVITIES, 2026, 6)
    assert wb["Sheet1"]["C8"].value in (None, "")


def test_day_missing_from_rows_gray_filled():
    # Partial-range run: rows cover only June 1-5.
    rows = make_rows(2026, 6)[:5]
    wb = build_activity_log(MEMBER, rows, ACTIVITIES, 2026, 6)
    ws = wb["Sheet1"]
    for c in (1, 3):  # June 30, full row
        cell = ws.cell(row=37, column=c)
        assert cell.fill.fill_type == "solid"
        assert cell.fill.start_color.rgb == GRAY_RGB


# --- month lengths ----------------------------------------------------


def test_28_day_month_trims_rows():
    rows = make_rows(2026, 2)
    wb = build_activity_log(MEMBER, rows, ACTIVITIES, 2026, 2)
    ws = wb["Sheet1"]
    assert ws["A35"].value == dt.datetime(2026, 2, 28)
    assert ws["A36"].value is None
    assert ws["A37"].value is None


def test_29_day_month_trims_one_row():
    rows = make_rows(2028, 2)
    wb = build_activity_log(MEMBER, rows, ACTIVITIES, 2028, 2)
    ws = wb["Sheet1"]
    assert ws["A36"].value == dt.datetime(2028, 2, 29)
    assert ws["A37"].value is None


def test_31_day_month_adds_styled_row():
    rows = make_rows(2026, 7)
    wb = build_activity_log(MEMBER, rows, ACTIVITIES, 2026, 7)
    ws = wb["Sheet1"]
    assert ws["A38"].value == dt.datetime(2026, 7, 31)
    assert ws["B38"].value == '=TEXT(A38,"ddd")'
    assert ws["A38"].number_format == ws["A37"].number_format
    # Style cloned from row 37 (borders survive).
    assert ws["A38"].border.left.style == ws["A37"].border.left.style
    assert ws["P38"].border.right.style == ws["P37"].border.right.style


# --- reproducibility --------------------------------------------------


def test_identical_inputs_identical_checks():
    rows = make_rows(2026, 6)
    a = build_activity_log(MEMBER, rows, ACTIVITIES, 2026, 6)["Sheet1"]
    b = build_activity_log(MEMBER, rows, ACTIVITIES, 2026, 6)["Sheet1"]
    coords_a = {(r, c) for r in range(8, 38) for c in range(3, 17)
                if a.cell(row=r, column=c).value == CHECK_CHAR}
    coords_b = {(r, c) for r in range(8, 38) for c in range(3, 17)
                if b.cell(row=r, column=c).value == CHECK_CHAR}
    assert coords_a == coords_b
    assert coords_a


def test_day_picks_independent_of_other_days():
    # Flipping June 2 to absent must not reshuffle June 1's picks.
    base = make_rows(2026, 6)
    changed = make_rows(2026, 6, absent_days=(2, 10))
    a = build_activity_log(MEMBER, base, ACTIVITIES, 2026, 6)["Sheet1"]
    b = build_activity_log(MEMBER, changed, ACTIVITIES, 2026, 6)["Sheet1"]
    row8_a = [a.cell(row=8, column=c).value for c in range(3, 17)]
    row8_b = [b.cell(row=8, column=c).value for c in range(3, 17)]
    assert row8_a == row8_b


# --- save fallback ----------------------------------------------------


def test_save_activity_log_primary(tmp_path):
    rows = make_rows(2026, 6)
    wb = build_activity_log(MEMBER, rows, ACTIVITIES, 2026, 6)
    path = save_activity_log(wb, str(tmp_path), 25347, 2026, 6)
    assert os.path.basename(path) == "(25347) Jun 2026 Activity log.xlsx"
    assert os.path.exists(path)


def test_save_activity_log_locked_falls_back(tmp_path):
    rows = make_rows(2026, 6)
    wb = build_activity_log(MEMBER, rows, ACTIVITIES, 2026, 6)
    # A directory at the primary path makes wb.save raise PermissionError.
    (tmp_path / "(25347) Jun 2026 Activity log.xlsx").mkdir()
    calls = []
    path = save_activity_log(wb, str(tmp_path), 25347, 2026, 6,
                             on_fallback=lambda p, a: calls.append((p, a)))
    assert path.endswith("_1.xlsx")
    assert len(calls) == 1
