import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import seed_operating_days as seed


class _FakeCursor:
    """Records every execute; `existing` is what COUNT(*) returns."""

    def __init__(self, existing: int):
        self._existing = existing
        self.executed = []

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self

    def fetchone(self):
        return (self._existing,)


def test_build_connection_string():
    cs = seed._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


def test_parse_args():
    ns = seed._parse_args(["--db", "x"])
    assert ns.db == "x"


def test_main_missing_db_returns_2(tmp_path, capsys):
    rc = seed.main(["--db", str(tmp_path / "nope.accdb")])
    assert rc == 2
    assert "database not found" in capsys.readouterr().err.lower()


def test_seed_inserts_seven_defaults_when_empty():
    cur = _FakeCursor(existing=0)
    existing, inserted = seed.seed_if_empty(cur)
    assert (existing, inserted) == (0, 7)
    inserts = [e for e in cur.executed if e[0].startswith("INSERT")]
    assert len(inserts) == 7
    assert [p[0] for _sql, p in inserts] == list(seed.DAY_NAMES)
    assert [p[1] for _sql, p in inserts] == [1, 2, 3, 4, 5, 6, 7]
    for _sql, p in inserts:
        assert p[2] == datetime(1899, 12, 30, 8, 0)
        assert p[3] == datetime(1899, 12, 30, 16, 0)


def test_seed_is_noop_when_rows_exist():
    cur = _FakeCursor(existing=5)
    assert seed.seed_if_empty(cur) == (5, 0)
    assert not any(e[0].startswith("INSERT") for e in cur.executed)


def test_insert_statement_shape():
    q = seed._INSERT_ROW
    assert q.startswith("INSERT INTO [OperatingDays]")
    for col in ("[day_name]", "[Day Of Week]", "[opening_time]",
                "[closing_time]"):
        assert col in q
