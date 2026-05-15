from monthly_schedule.health_plan import display_plan, PLAN_NAMES


def test_known_code_maps_to_name():
    assert display_plan("HOF") == "Elderplan Homefirst"


def test_unknown_code_falls_back_to_raw():
    assert display_plan("BCBS") == "BCBS"
    assert display_plan("HF") == "HF"


def test_blank_or_none():
    assert display_plan("") == ""
    assert display_plan(None) == ""


def test_plan_names_contains_hof():
    assert PLAN_NAMES["HOF"] == "Elderplan Homefirst"
