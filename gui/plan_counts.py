"""Pure view-model for the plan-counts table (spec 2026-07-28).

No Qt, no ODBC — main_window renders what these helpers return, so the
row math, loading states, and captions stay unit-testable."""

from gui.i18n import tr

# Single source of truth for the GUI's plan list (moved from main_window).
PLAN_CODES = ["HF", "HOF", "VCM", "BCBS", "ES", "AE", "HC", "BCSB"]

LOADING = "—"


def plan_table_rows(counts):
    """Rows for the fixed 8-plan table.

    `counts` is get_plan_member_counts() output, or None while loading /
    after a failure. Returns (rows, total_active_str) where each row is
    (plan_code, active_str, inactive_str). Unknown-plan members appear
    only in the total (the table lists the 8 known codes)."""
    rows = []
    for code in PLAN_CODES:
        if counts is None:
            rows.append((code, LOADING, LOADING))
            continue
        entry = counts["plans"].get(code, {"total": 0, "active": 0})
        active = entry["active"]
        inactive = max(0, entry["total"] - active)
        rows.append((code, str(active), str(inactive)))
    total = LOADING if counts is None else str(counts["total_active"])
    return rows, total


def scope_caption(counts, mode, plan_code, month_name, year):
    """Caption under the Generate button ('' outside plan/all modes)."""
    if mode not in ("plan", "all"):
        return ""
    if counts is None:
        n = LOADING
    elif mode == "plan":
        entry = counts["plans"].get(plan_code)
        n = str(entry["active"]) if entry else "0"
    else:
        n = str(counts["total_active"])
    # Note: named plan_table.scope.* (not scope.plan/scope.all) because
    # those keys already exist in gui/i18n.py for the run-summary builder
    # (gui/main_window.py._build_summary, different placeholders) —
    # reusing them here would silently clobber that dict entry.
    key = "plan_table.scope.plan" if mode == "plan" else "plan_table.scope.all"
    return tr(key, count=n, plan=plan_code, month=month_name, year=year)
