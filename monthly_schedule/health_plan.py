"""Map Access `Health Plan` codes to display MLTC names.

Extensible: add code->name pairs to PLAN_NAMES. Unknown or blank
codes fall back to the raw code string (spec section 3).
"""

PLAN_NAMES = {
    "HOF": "Elderplan Homefirst",
}


def display_plan(code):
    """Return the friendly MLTC name for a Health Plan code, or the
    raw code if it is not in PLAN_NAMES (None/blank -> '')."""
    if not code:
        return ""
    return PLAN_NAMES.get(code, code)
