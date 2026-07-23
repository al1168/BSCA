from gui.settings_dialog import parse_member_ids, _format_member_ids


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
