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


def test_translate_reason_no_eligible_days():
    from gui import i18n
    from gui.main_window import _translate_reason
    from monthly_schedule.per_day import REASON_NO_ELIGIBLE_DAYS
    i18n.set_language("zh")
    assert _translate_reason(REASON_NO_ELIGIBLE_DAYS) == (
        i18n.STRINGS["zh"]["summary.reason.no_eligible_days"]
    )


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
