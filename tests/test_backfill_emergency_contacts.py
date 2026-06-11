import datetime
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import backfill_emergency_contacts_from_contacts as backfill


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_csv_columns():
    assert backfill._CSV_COLUMNS == [
        "center_id",
        "raw_emergency",
        "parsed_name",
        "parsed_phone",
        "parsed_relationship",
        "reason",
    ]


def test_contacts_query_shape():
    q = backfill._CONTACTS_QUERY
    assert "[Center ID]" in q
    assert "[Emergency]" in q
    assert "FROM [Contacts]" in q
    assert "ORDER BY [Center ID]" in q


def test_emergency_insert_query_shape():
    q = backfill._EMERGENCY_INSERT
    for col in ("[Center ID]", "[Full Name]", "[Phone Number]", "[Relationship]"):
        assert col in q
    assert q.count("?") == 4


def test_emergency_count_query_shape():
    q = backfill._EMERGENCY_COUNT_FOR_MEMBER
    assert "COUNT(*)" in q
    assert "[EmergencyContact]" in q
    assert q.count("?") == 1


# ---------------------------------------------------------------------------
# _extract_phones — covers the formats seen in production data
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("(917) 628-0459",   "(917) 628-0459"),
    ("(917)402-9866",    "(917) 402-9866"),
    ("917-530-5185",     "(917) 530-5185"),
    ("9175305185",       "(917) 530-5185"),
    ("(309) 716-9957",   "(309) 716-9957"),
    ("917.530.5185",     "(917) 530-5185"),
])
def test_extract_phones_formats(raw, expected):
    phones, _ = backfill._extract_phones(raw)
    assert phones == [expected]


def test_extract_phones_none_found():
    phones, leftover = backfill._extract_phones("Daughter")
    assert phones == []
    assert leftover == "Daughter"


def test_extract_phones_multiple():
    phones, leftover = backfill._extract_phones(
        "Daughter, (917) 555-1111 or (646) 555-2222"
    )
    assert phones == ["(917) 555-1111", "(646) 555-2222"]
    # Both phones should be removed from the leftover.
    assert "917" not in leftover and "646" not in leftover


def test_extract_phones_strips_only_phone_not_other_digits():
    phones, leftover = backfill._extract_phones(
        "Daughter, Apt 4B, (917) 555-1111"
    )
    assert phones == ["(917) 555-1111"]
    assert "4B" in leftover  # apartment number untouched


# ---------------------------------------------------------------------------
# _extract_relationships — vocab + case + typo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Son, Andy Lau",                          ["Son"]),
    ("daughter: 917-530-5185",                 ["Daughter"]),
    ("Daugther, Xu, Ling Jun",                 ["Daughter"]),  # typo → canonical
    ("(son)",                                  ["Son"]),
    ("Son-in-law, Tong",                       ["Son-in-law"]),
    ("SPOUSE",                                 ["Spouse"]),
    ("Wang Mary",                              []),
    ("Mom",                                    ["Mother"]),
    ("daugther",                               ["Daughter"]),
])
def test_extract_relationships_canonical(raw, expected):
    rels, _ = backfill._extract_relationships(raw)
    assert rels == expected


def test_extract_relationships_in_law_beats_son():
    """The 'in law' compounds must match before bare 'son' so the
    longer form wins."""
    rels, _ = backfill._extract_relationships("Son-in-law, Tom")
    assert rels == ["Son-in-law"]


def test_extract_relationships_multiple_distinct():
    rels, _ = backfill._extract_relationships("Son or Daughter")
    assert rels == ["Daughter", "Son"]  # order = vocab order


# ---------------------------------------------------------------------------
# _parse_emergency — full pipeline against real-world strings
# ---------------------------------------------------------------------------

def test_parse_full_three_part_comma():
    """`Relationship, Name, Phone` — the most common format."""
    p = backfill._parse_emergency("Son, Andy Lau, (917) 628-0459")
    assert p == {
        "name": "Andy Lau",
        "phone": "(917) 628-0459",
        "relationship": "Son",
        "reason": "",
    }


def test_parse_relationship_and_phone_no_name():
    """`Relationship, Phone` — no name, still a clean parse."""
    p = backfill._parse_emergency("Son, (347) 398-8708")
    assert p == {
        "name": "",
        "phone": "(347) 398-8708",
        "relationship": "Son",
        "reason": "",
    }


def test_parse_colon_separator():
    p = backfill._parse_emergency("Daughter: 917-530-5185")
    assert p == {
        "name": "",
        "phone": "(917) 530-5185",
        "relationship": "Daughter",
        "reason": "",
    }


def test_parse_name_and_phone_no_relationship():
    """`Name, Phone` without a relationship word is fine — inserts
    with empty Relationship."""
    p = backfill._parse_emergency("Wang Mary, (917) 337-2918")
    assert p == {
        "name": "Wang Mary",
        "phone": "(917) 337-2918",
        "relationship": "",
        "reason": "",
    }


def test_parse_trailing_paren_relationship():
    """`Name, Phone(relationship)` — e.g. 'Wang, Zhi Ming, (917) 299-2254(son)'."""
    p = backfill._parse_emergency("Wang, Zhi Ming, (917) 299-2254(son)")
    assert p == {
        "name": "Wang Zhi Ming",
        "phone": "(917) 299-2254",
        "relationship": "Son",
        "reason": "",
    }


def test_parse_typo_daugther():
    p = backfill._parse_emergency("Daugther, Xu, Ling Jun, (646) 727-5587")
    assert p["relationship"] == "Daughter"
    assert p["phone"] == "(646) 727-5587"
    assert p["name"] == "Xu Ling Jun"
    assert p["reason"] == ""


def test_parse_no_phone_flagged():
    p = backfill._parse_emergency("Daughter, no number on file")
    assert p["reason"] == "no_phone"
    assert p["phone"] == ""
    assert p["relationship"] == "Daughter"


def test_parse_multiple_phones_flagged():
    p = backfill._parse_emergency("Daughter, (917) 555-1111 or (646) 555-2222")
    assert p["reason"] == "multiple_phones"
    assert "(917) 555-1111" in p["phone"]
    assert "(646) 555-2222" in p["phone"]


def test_parse_multiple_relationships_flagged():
    p = backfill._parse_emergency("Son or Daughter, (917) 555-1111")
    assert p["reason"] == "multiple_relationships"
    assert p["phone"] == "(917) 555-1111"


def test_parse_name_too_long_flagged():
    name_filler = "X " * 60  # 120 chars
    p = backfill._parse_emergency(f"Daughter, {name_filler}, (917) 555-1111")
    assert p["reason"] == "name_too_long"


def test_parse_just_phone():
    """Phone only, no relationship, no name. Clean parse."""
    p = backfill._parse_emergency("(646) 338-7433")
    assert p == {
        "name": "",
        "phone": "(646) 338-7433",
        "relationship": "",
        "reason": "",
    }


# ---------------------------------------------------------------------------
# FakeCursor / FakeConn — mirrors the pattern used in test_backfill_enrollment.
# ---------------------------------------------------------------------------

class FakeCursor:
    def __init__(self):
        self.executed = []
        self._fetchall_queue = []
        self._fetchone_queue = []

    def queue_fetchall(self, rows):
        self._fetchall_queue.append(rows)

    def queue_fetchone(self, row):
        self._fetchone_queue.append(row)

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self

    def fetchall(self):
        return self._fetchall_queue.pop(0)

    def fetchone(self):
        return self._fetchone_queue.pop(0)


class FakeConn:
    def __init__(self, fake_cursor):
        self._cursor = fake_cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def _make_fake_conn(contacts_rows, contact_total, count_values):
    """Build a FakeConn with the queries the script issues, in order:
      1. SELECT COUNT(*) FROM Contacts WHERE Center ID IS NOT NULL → contact_total
      2. _CONTACTS_QUERY                                            → contacts_rows
      3. _EMERGENCY_COUNT_FOR_MEMBER (per non-empty-Emergency row)  → count_values
    """
    cur = FakeCursor()
    cur.queue_fetchone((contact_total,))      # initial count
    cur.queue_fetchall(contacts_rows)         # contacts scan
    for val in count_values:
        cur.queue_fetchone((val,))            # per-member idempotency check
    return FakeConn(cur), cur


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------

def test_main_missing_db_returns_2(tmp_path, capsys):
    missing = tmp_path / "nope.accdb"
    rc = backfill.main(["--db", str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "database not found" in err.lower()


def test_main_inserts_clean_rows(tmp_path, monkeypatch):
    contacts = [
        (24001, "Son, Andy Lau, (917) 628-0459"),
        (24010, "Daughter, Yang, Qin, (212) 393-1193"),
    ]
    conn, cur = _make_fake_conn(contacts, 2, count_values=[0, 0])

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)
    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = backfill.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    inserts = [p for s, p in cur.executed if s == backfill._EMERGENCY_INSERT]
    assert len(inserts) == 2
    assert inserts[0] == ("24001", "Andy Lau", "(917) 628-0459", "Son")
    assert inserts[1] == ("24010", "Yang Qin", "(212) 393-1193", "Daughter")
    assert conn.committed is True


def test_main_skips_already_present_members(tmp_path, monkeypatch):
    contacts = [(24001, "Son, Andy Lau, (917) 628-0459")]
    conn, cur = _make_fake_conn(contacts, 1, count_values=[1])  # already present

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)
    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = backfill.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0
    inserts = [p for s, p in cur.executed if s == backfill._EMERGENCY_INSERT]
    assert inserts == []


def test_main_ambiguous_rows_logged_to_csv_not_inserted(tmp_path, monkeypatch):
    contacts = [
        (24001, "Daughter, no number on file"),                  # no_phone
        (24002, "Daughter, (917) 555-1111 or (646) 555-2222"),   # multiple_phones
    ]
    conn, cur = _make_fake_conn(contacts, 2, count_values=[0, 0])

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)
    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = backfill.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    inserts = [p for s, p in cur.executed if s == backfill._EMERGENCY_INSERT]
    assert inserts == []

    csv_path = tmp_path / f"emergency_contact_ambiguous_{datetime.date.today().isoformat()}.csv"
    assert csv_path.exists()
    body = csv_path.read_text(encoding="utf-8-sig")
    assert "no_phone" in body
    assert "multiple_phones" in body
    assert "24001" in body and "24002" in body


def test_main_empty_emergency_silently_skipped(tmp_path, monkeypatch):
    """Contacts with NULL/empty Emergency are silently skipped — they
    don't run an idempotency check, don't insert, don't log to CSV."""
    contacts = [
        (24001, None),
        (24002, ""),
        (24003, "   "),
        (24010, "Son, Andy Lau, (917) 628-0459"),  # one real row
    ]
    conn, cur = _make_fake_conn(contacts, 4, count_values=[0])

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)
    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = backfill.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--quiet",
    ])
    assert rc == 0

    # Only one insert, for the only contact with non-empty emergency.
    inserts = [p for s, p in cur.executed if s == backfill._EMERGENCY_INSERT]
    assert len(inserts) == 1
    assert inserts[0][0] == "24010"

    # Idempotency check only fires for that one row.
    count_calls = [p for s, p in cur.executed
                   if s == backfill._EMERGENCY_COUNT_FOR_MEMBER]
    assert len(count_calls) == 1


def test_dry_run_rolls_back(tmp_path, monkeypatch):
    contacts = [(24001, "Son, Andy Lau, (917) 628-0459")]
    conn, cur = _make_fake_conn(contacts, 1, count_values=[0])

    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)
    db_path = tmp_path / "test.accdb"
    db_path.touch()

    rc = backfill.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        "--dry-run",
        "--quiet",
    ])
    assert rc == 0
    assert conn.rolled_back is True
    assert conn.committed is False
