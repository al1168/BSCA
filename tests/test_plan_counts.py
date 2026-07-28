from gui.plan_counts import PLAN_CODES, plan_table_rows, scope_caption


def _counts():
    return {
        "plans": {
            "HF": {"total": 100, "active": 96},
            "BCBS": {"total": 50, "active": 44},
            "": {"total": 9, "active": 5},       # unknown-plan bucket
        },
        "total_active": 145,
    }


def test_rows_cover_all_eight_plans_in_order():
    rows, total = plan_table_rows(_counts())
    assert [r[0] for r in rows] == PLAN_CODES
    assert len(rows) == 8


def test_rows_math_and_missing_plans_zero():
    rows, total = plan_table_rows(_counts())
    by_code = {code: (active, inactive) for code, active, inactive in rows}
    assert by_code["HF"] == ("96", "4")
    assert by_code["BCBS"] == ("44", "6")
    assert by_code["VCM"] == ("0", "0")          # not in counts -> 0/0
    # Total spans ALL plans, including the unknown bucket.
    assert total == "145"


def test_rows_loading_state_shows_dashes():
    rows, total = plan_table_rows(None)
    assert all(active == "—" and inactive == "—" for _c, active, inactive in rows)
    assert total == "—"


def test_scope_caption_plan_mode():
    text = scope_caption(_counts(), "plan", "HF", "July", 2026)
    assert "96" in text and "HF" in text and "July" in text and "2026" in text


def test_scope_caption_all_mode():
    text = scope_caption(_counts(), "all", "HF", "July", 2026)
    assert "145" in text and "July" in text


def test_scope_caption_loading_and_other_modes():
    assert "—" in scope_caption(None, "plan", "HF", "July", 2026)
    assert scope_caption(_counts(), "single", "HF", "July", 2026) == ""
    assert scope_caption(_counts(), "multiple", "HF", "July", 2026) == ""
