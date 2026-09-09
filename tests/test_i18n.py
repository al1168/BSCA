import json

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch, tmp_path):
    """Redirect bsca_settings.json to a per-test tmp file so that
    i18n.set_language() does not write to the real settings file."""
    settings_file = tmp_path / "bsca_settings.json"
    settings_file.write_text(json.dumps({"language": "en"}))
    monkeypatch.setattr(
        "gui.app_settings._SETTINGS_FILE", str(settings_file)
    )
    monkeypatch.setattr("gui.i18n._current_lang", "en")
    return settings_file


def test_key_parity():
    from gui.i18n import STRINGS
    en_keys = set(STRINGS["en"].keys())
    zh_keys = set(STRINGS["zh"].keys())
    assert en_keys == zh_keys, (
        f"missing in zh: {en_keys - zh_keys}; "
        f"missing in en: {zh_keys - en_keys}"
    )


def test_missing_key_returns_key():
    from gui import i18n
    i18n.set_language("en")
    assert i18n.tr("nope.nada") == "nope.nada"


def test_tr_basic_lookup():
    from gui import i18n
    i18n.set_language("en")
    assert i18n.tr("opts.generate") == "Generate Schedule"
    i18n.set_language("zh")
    assert i18n.tr("opts.generate") == "生成日程表"


def test_format_interpolation():
    from gui import i18n
    i18n.set_language("en")
    result = i18n.tr("worker.wrote", filename="Schedule_24010_2026-05.xlsx")
    assert result == "Wrote Schedule_24010_2026-05.xlsx"


def test_missing_format_arg_raises():
    from gui import i18n
    i18n.set_language("en")
    with pytest.raises(KeyError):
        i18n.tr("worker.wrote")  # missing 'filename'


def test_no_eligible_days_reason_key_present_in_both_languages():
    from gui.i18n import STRINGS
    assert "summary.reason.no_eligible_days" in STRINGS["en"]
    assert "summary.reason.no_eligible_days" in STRINGS["zh"]


def test_center_closed_month_reason_key_present_in_both_languages():
    from gui.i18n import STRINGS
    assert "summary.reason.center_closed_month" in STRINGS["en"]
    assert "summary.reason.center_closed_month" in STRINGS["zh"]


def test_translate_reason_center_closed_month():
    from gui import i18n
    from gui.main_window import _translate_reason
    from monthly_schedule.per_day import REASON_CENTER_CLOSED_MONTH
    i18n.set_language("zh")
    assert _translate_reason(REASON_CENTER_CLOSED_MONTH) == (
        i18n.STRINGS["zh"]["summary.reason.center_closed_month"]
    )


def test_translate_reason_no_eligible_days():
    from gui import i18n
    from gui.main_window import _translate_reason
    from monthly_schedule.per_day import REASON_NO_ELIGIBLE_DAYS
    i18n.set_language("zh")
    assert _translate_reason(REASON_NO_ELIGIBLE_DAYS) == (
        i18n.STRINGS["zh"]["summary.reason.no_eligible_days"]
    )


ONE_OFF_ABSENCE_DETAIL = {
    "kind": "absence",
    "day": "2026-08-04",
    "one_offs": [{"id": 4, "avail_start": "09:00", "avail_end": "12:00"}],
    "absence": {
        "id": 14, "leave_type": "Vacation",
        "start_date": "2026-08-04", "end_date": "2026-08-05",
    },
}

ONE_OFF_DUPLICATE_DETAIL = {
    "kind": "duplicate",
    "day": "2026-08-04",
    "one_offs": [
        {"id": 4, "avail_start": "09:00", "avail_end": "12:00"},
        {"id": 7, "avail_start": "10:00", "avail_end": "13:00"},
    ],
    "absence": None,
}


def test_one_off_reason_keys_present_in_both_languages():
    from gui.i18n import STRINGS
    for key in (
        "summary.reason.one_off_absence",
        "summary.reason.one_off_absence_untyped",
        "summary.reason.one_off_duplicate",
        "summary.reason.one_off_row",
        "summary.reason.one_off_join",
        "summary.reason.one_off_join_last",
    ):
        assert key in STRINGS["en"], key
        assert key in STRINGS["zh"], key


def test_translate_reason_one_off_absence_zh():
    from gui import i18n
    from gui.main_window import _translate_reason
    i18n.set_language("zh")
    assert _translate_reason("ignored English text", ONE_OFF_ABSENCE_DETAIL) == (
        "2026-08-04 的一次性可用时段 09:00-12:00"
        "（OneOffAvailability 第 4 行）"
        "与 Vacation 缺席记录 2026-08-04 至 2026-08-05"
        "（Absences 第 14 行）冲突"
    )


def test_translate_reason_one_off_absence_untyped_zh():
    from gui import i18n
    from gui.main_window import _translate_reason
    i18n.set_language("zh")
    detail = dict(ONE_OFF_ABSENCE_DETAIL)
    detail["absence"] = dict(detail["absence"], leave_type="")
    assert _translate_reason("ignored", detail) == (
        "2026-08-04 的一次性可用时段 09:00-12:00"
        "（OneOffAvailability 第 4 行）"
        "与缺席记录 2026-08-04 至 2026-08-05"
        "（Absences 第 14 行）冲突"
    )


def test_translate_reason_one_off_duplicate_zh():
    from gui import i18n
    from gui.main_window import _translate_reason
    i18n.set_language("zh")
    assert _translate_reason("ignored", ONE_OFF_DUPLICATE_DETAIL) == (
        "2026-08-04 有 2 条一次性记录："
        "09:00-12:00（第 4 行）、10:00-13:00（第 7 行）"
    )


def test_translate_reason_one_off_absence_en_matches_core_sentence():
    """English GUI text and the CSV's English sentence must not drift."""
    from datetime import date
    from gui import i18n
    from gui.main_window import _translate_reason
    from monthly_schedule.per_day import (
        OneOffConflictDetail, format_one_off_conflict,
    )
    i18n.set_language("en")
    detail = OneOffConflictDetail(
        kind="absence",
        day=date(2026, 8, 4),
        one_offs=({"id": 4, "avail_start": "09:00", "avail_end": "12:00"},),
        absence={"id": 14, "leave_type": "Vacation",
                 "start_date": date(2026, 8, 4),
                 "end_date": date(2026, 8, 5)},
    )
    assert _translate_reason("ignored", detail.as_dict()) == (
        format_one_off_conflict(detail)
    )


def test_translate_reason_one_off_duplicate_en_matches_core_sentence():
    """Three rows exercise the serial join, where English and Chinese
    punctuation differ most."""
    from datetime import date
    from gui import i18n
    from gui.main_window import _translate_reason
    from monthly_schedule.per_day import (
        OneOffConflictDetail, format_one_off_conflict,
    )
    i18n.set_language("en")
    detail = OneOffConflictDetail(
        kind="duplicate",
        day=date(2026, 8, 4),
        one_offs=(
            {"id": 4, "avail_start": "09:00", "avail_end": "12:00"},
            {"id": 7, "avail_start": "10:00", "avail_end": "13:00"},
            {"id": 9, "avail_start": "11:00", "avail_end": "14:00"},
        ),
    )
    assert _translate_reason("ignored", detail.as_dict()) == (
        format_one_off_conflict(detail)
    )


def test_translate_reason_without_detail_is_unchanged():
    """Failures that carry no structured detail still pass through."""
    from gui import i18n
    from gui.main_window import _translate_reason
    i18n.set_language("zh")
    assert _translate_reason("some unmapped reason") == "some unmapped reason"


def test_billing_name_setting_keys_present_in_both_languages():
    from gui.i18n import STRINGS
    for key in (
        "settings.billing_name_label",
        "settings.billing_name_missing.title",
        "settings.billing_name_missing.body",
        "settings.billing_name_invalid.title",
        "settings.billing_name_invalid.body",
        "msg.billing_name_missing.title",
        "msg.billing_name_missing.body",
    ):
        assert key in STRINGS["en"], key
        assert key in STRINGS["zh"], key


def test_set_language_persists(_isolate_settings):
    from gui import i18n
    i18n.set_language("zh")

    data = json.loads(_isolate_settings.read_text())
    assert data["language"] == "zh"


def test_unknown_language_falls_back_to_missing():
    from gui import i18n
    i18n.set_language("fr")  # unsupported
    # _current_lang is "fr"; tr() falls through to the missing-key path
    assert i18n.tr("opts.generate") == "opts.generate"
