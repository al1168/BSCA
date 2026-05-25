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
