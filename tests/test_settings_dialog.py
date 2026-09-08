import os

_APP = None

from gui.settings_dialog import (
    billing_name_error,
    parse_member_ids,
    _format_member_ids,
)


def test_parse_member_ids_basic():
    assert parse_member_ids("24010, 24011,24012") == [24010, 24011, 24012]


def test_parse_member_ids_blank_is_empty():
    assert parse_member_ids("") == []
    assert parse_member_ids("   ") == []


def test_parse_member_ids_rejects_junk():
    assert parse_member_ids("24010, abc") is None
    assert parse_member_ids("12.5") is None


def test_format_member_ids_round_trip():
    ids = [24010, 24011]
    assert parse_member_ids(_format_member_ids(ids)) == ids
    assert _format_member_ids([]) == ""


def test_billing_name_error_blank_is_missing():
    assert billing_name_error("") == "missing"
    assert billing_name_error("   ") == "missing"


def test_billing_name_error_rejects_forbidden_filename_chars():
    for ch in '\\/:*?"<>|':
        assert billing_name_error(f"Jane{ch}Doe") == "invalid", ch


def test_billing_name_error_accepts_valid_name():
    assert billing_name_error("Jane Doe") is None
    assert billing_name_error("  Jane  ") is None


def test_dialog_has_no_day_bound_fields():
    """Opening/closing hours come from the database's OperatingDays
    table, so Settings must not offer day-bound time pickers."""
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    # Held in a module global: an unreferenced QApplication is garbage
    # collected and the next widget built on it crashes the process.
    _APP = QApplication.instance() or QApplication([])
    from gui.settings_dialog import SettingsDialog
    from gui import app_settings
    settings = dict(app_settings.DEFAULTS)        # not the user's live file
    settings["schedule_rules"] = dict(app_settings.DEFAULTS["schedule_rules"])
    dlg = SettingsDialog(settings)                # (settings, parent=None, first_run=False)
    assert not hasattr(dlg, "_earliest_in_edit")
    assert not hasattr(dlg, "_latest_out_edit")
