import datetime
import re
import sys
from pathlib import Path

import pytest

# Ensure the script is importable as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import shorten_double_zero_ids as sh


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_tables_list():
    """The seven [Center ID] tables, Contacts first."""
    assert sh._TABLES == [
        "Contacts",
        "Enrollment",
        "Authorization",
        "Absences",
        "Availability",
        "OneOffAvailability",
        "EmergencyContact",
    ]


def test_csv_columns():
    assert sh._CSV_COLUMNS == ["old_id", "new_id", "reason"]


def test_scan_template_shape():
    q = sh._SCAN_TEMPLATE.format(table="Enrollment")
    assert q == "SELECT [Center ID] FROM [Enrollment]"


def test_rename_template_shape():
    q = sh._RENAME_TEMPLATE.format(table="Enrollment")
    assert "UPDATE [Enrollment]" in q
    assert "SET [Center ID] = ?" in q
    assert "WHERE [Center ID] = ?" in q
    assert q.count("?") == 2


# ---------------------------------------------------------------------------
# _build_connection_string
# ---------------------------------------------------------------------------

def test_build_connection_string():
    cs = sh._build_connection_string(r"C:\data\file.accdb")
    assert "Microsoft Access Driver (*.mdb, *.accdb)" in cs
    assert r"DBQ=C:\data\file.accdb" in cs


# ---------------------------------------------------------------------------
# _qualifies / _new_id
# ---------------------------------------------------------------------------

def test_qualifies_true_cases():
    assert sh._qualifies(2213400) is True       # 7 digits, ends 00
    assert sh._qualifies(2213400.0) is True     # DOUBLE form
    assert sh._qualifies(100000) is True        # 6 digits, ends 00
    assert sh._qualifies(99999900) is True      # 8 digits, ends 00


def test_qualifies_false_cases():
    assert sh._qualifies(24010) is False        # 5 digits
    assert sh._qualifies(99900) is False        # 5 digits, ends 00
    assert sh._qualifies(2400601) is False      # long, doesn't end 00
    assert sh._qualifies(2400601.0) is False    # DOUBLE form
    assert sh._qualifies(None) is False         # NULL Center ID


def test_new_id():
    assert sh._new_id(2213400) == 22134
    assert sh._new_id(2213400.0) == 22134       # DOUBLE form
    assert sh._new_id(123400) == 1234           # result < 5 digits is fine
    assert sh._new_id(221340000) == 2213400     # caller must skip: still >5


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------

def test_parse_args_requires_db():
    with pytest.raises(SystemExit):
        sh._parse_args([])


def test_parse_args_defaults():
    args = sh._parse_args(["--db", "C:/x.accdb"])
    assert args.db == "C:/x.accdb"
    assert args.csv_out == "."
    assert args.dry_run is False
    assert args.quiet is False


def test_parse_args_all_flags():
    args = sh._parse_args([
        "--db", "C:/x.accdb",
        "--csv-out", "/tmp/out",
        "--dry-run",
        "--quiet",
    ])
    assert args.csv_out == "/tmp/out"
    assert args.dry_run is True
    assert args.quiet is True


# ---------------------------------------------------------------------------
# _write_skipped_csv
# ---------------------------------------------------------------------------

def test_write_skipped_csv_empty_writes_header(tmp_path):
    """Even with no rows, the CSV is written with just the header —
    file presence signals 'a run happened on this date'."""
    today = datetime.date(2026, 7, 17)
    path = sh._write_skipped_csv([], str(tmp_path), today)
    assert path == str(tmp_path / "shorten_ids_skipped_2026-07-17.csv")
    body = Path(path).read_text(encoding="utf-8-sig")
    assert body.splitlines() == ["old_id,new_id,reason"]


def test_write_skipped_csv_rows(tmp_path):
    today = datetime.date(2026, 7, 17)
    rows = [
        {"old_id": 2213400, "new_id": 22134,
         "reason": "target ID already exists in: Contacts"},
        {"old_id": 221340000, "new_id": 2213400,
         "reason": "still longer than 5 digits after stripping 00"},
    ]
    path = sh._write_skipped_csv(rows, str(tmp_path), today)
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "old_id,new_id,reason"
    assert lines[1] == "2213400,22134,target ID already exists in: Contacts"
    assert lines[2].startswith("221340000,2213400,still longer")


# ---------------------------------------------------------------------------
# FakeCursor / FakeConn (mirrors tests/test_terminate_long_id_enrollments.py)
# ---------------------------------------------------------------------------

class FakeCursor:
    """Records execute() calls; returns canned fetchall results. The
    `rowcount` attribute defaults to 1 (single affected row) so
    happy-path tests don't need to set it explicitly."""
    def __init__(self):
        self.executed = []        # list of (sql, params_tuple)
        self._fetchall_queue = []
        self.rowcount = 1

    def queue_fetchall(self, rows):
        self._fetchall_queue.append(rows)

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self

    def fetchall(self):
        return self._fetchall_queue.pop(0)


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


def _make_fake_conn(scan_by_table):
    """Build a FakeConn whose cursor answers the seven per-table scans
    in sh._TABLES order. `scan_by_table` maps table name -> list of
    Center ID values (missing tables scan as empty). Values are
    wrapped as 1-tuples, matching `SELECT [Center ID]` rows."""
    cur = FakeCursor()
    for table in sh._TABLES:
        rows = [(cid,) for cid in scan_by_table.get(table, [])]
        cur.queue_fetchall(rows)
    return FakeConn(cur), cur


def _updates(cur):
    """The recorded UPDATE executions as (table, params) pairs."""
    out = []
    for sql, params in cur.executed:
        if sql.startswith("UPDATE ["):
            table = sql.split("[")[1].split("]")[0]
            out.append((table, params))
    return out


def _run_main(tmp_path, monkeypatch, conn, extra_flags=("--quiet",)):
    """Patch pyodbc.connect, touch a fake .accdb, run main()."""
    import pyodbc as _pyodbc
    monkeypatch.setattr(_pyodbc, "connect", lambda cs: conn)
    db_path = tmp_path / "test.accdb"
    db_path.touch()
    return sh.main([
        "--db", str(db_path),
        "--csv-out", str(tmp_path),
        *extra_flags,
    ])


def _skipped_csv_lines(tmp_path):
    csv_path = tmp_path / (
        f"shorten_ids_skipped_{datetime.date.today().isoformat()}.csv"
    )
    assert csv_path.exists()
    return csv_path.read_text(encoding="utf-8-sig").splitlines()


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_missing_db_returns_2(tmp_path, capsys):
    missing = tmp_path / "nope.accdb"
    rc = sh.main(["--db", str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "database not found" in err.lower()


def test_main_renames_across_all_tables(tmp_path, monkeypatch):
    """Happy path: one qualifying ID in several tables triggers ONE
    UPDATE per table (all seven, unconditionally) with params
    (new_id, old_id), and the run commits."""
    conn, cur = _make_fake_conn({
        "Contacts": [2213400],
        "Enrollment": [2213400],
        "Availability": [2213400],
    })
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0

    updates = _updates(cur)
    assert [t for t, _ in updates] == sh._TABLES
    for _, params in updates:
        assert params == (22134, 2213400)
    assert conn.committed is True

    # Nothing skipped: CSV is header-only.
    assert _skipped_csv_lines(tmp_path) == ["old_id,new_id,reason"]


def test_main_renames_orphaned_child_rows(tmp_path, monkeypatch):
    """A qualifying ID present only in a child table (no Contacts row)
    is still renamed — candidates come from the union of all tables."""
    conn, cur = _make_fake_conn({"Enrollment": [2213400]})
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0
    updates = _updates(cur)
    assert len(updates) == len(sh._TABLES)
    for _, params in updates:
        assert params == (22134, 2213400)


def test_main_skips_collision(tmp_path, monkeypatch):
    """If the shortened ID already exists anywhere, the member is
    fully skipped and the CSV names the colliding tables."""
    conn, cur = _make_fake_conn({
        "Contacts": [2213400, 22134],
        "Absences": [22134],
    })
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0
    assert _updates(cur) == []
    assert conn.committed is True

    lines = _skipped_csv_lines(tmp_path)
    assert len(lines) == 2
    # Exact-field prefix (avoids '2213400' matching '22134' substrings).
    assert lines[1].startswith("2213400,22134,")
    assert "target ID already exists in: Contacts, Absences" in lines[1]


def test_main_skips_still_too_long(tmp_path, monkeypatch):
    """221340000 strips to 2213400 — still 7 digits, so skip+report
    instead of a half-fix."""
    conn, cur = _make_fake_conn({"Contacts": [221340000]})
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0
    assert _updates(cur) == []

    lines = _skipped_csv_lines(tmp_path)
    assert len(lines) == 2
    assert lines[1].startswith("221340000,2213400,")
    assert "still longer than 5 digits" in lines[1]


def test_main_ignores_non_qualifying_ids(tmp_path, monkeypatch):
    """5-digit IDs, long IDs not ending 00, and NULLs never rename."""
    conn, cur = _make_fake_conn({
        "Contacts": [24010, 99900, 2400601, None],
        "Enrollment": [24010, 2400601],
    })
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0
    assert _updates(cur) == []
    assert _skipped_csv_lines(tmp_path) == ["old_id,new_id,reason"]


def test_dry_run_calls_rollback_not_commit(tmp_path, monkeypatch):
    conn, cur = _make_fake_conn({"Contacts": [2213400]})
    rc = _run_main(tmp_path, monkeypatch, conn,
                   extra_flags=("--quiet", "--dry-run"))
    assert rc == 0
    assert conn.rolled_back is True
    assert conn.committed is False
    # Dry-run still executes the UPDATEs (they roll back).
    assert len(_updates(cur)) == len(sh._TABLES)


def test_summary_counts(tmp_path, monkeypatch, capsys):
    """One renamed member, one collision skip: summary reflects both.
    FakeCursor.rowcount defaults to 1, so every table reports 1 row."""
    conn, cur = _make_fake_conn({
        "Contacts": [2213400, 2400600, 24006],
    })
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0

    out = capsys.readouterr().out
    assert "Shorten-double-zero-ID summary" in out
    # Whitespace-insensitive: the summary aligns numbers with space
    # runs; asserting exact spacing would couple the test to layout.
    assert re.search(r"Candidate IDs found \(>5 digits, ends 00\):\s+2\b", out)
    assert re.search(r"Members renamed:\s+1\b", out)
    assert re.search(r"Members skipped \(collision\):\s+1\b", out)
    assert re.search(r"Members skipped \(still too long\):\s+0\b", out)
    assert "Mode: APPLIED" in out


def test_quiet_suppresses_per_member_output(tmp_path, monkeypatch, capsys):
    conn, cur = _make_fake_conn({"Contacts": [2213400, 2400600, 24006]})
    rc = _run_main(tmp_path, monkeypatch, conn)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Shorten-double-zero-ID summary" in out
    assert "renamed 2213400" not in out
    assert "skipped 2400600" not in out


def test_non_quiet_prints_per_member_lines(tmp_path, monkeypatch, capsys):
    conn, cur = _make_fake_conn({"Contacts": [2213400, 2400600, 24006]})
    rc = _run_main(tmp_path, monkeypatch, conn, extra_flags=())
    assert rc == 0
    out = capsys.readouterr().out
    assert "renamed 2213400 -> 22134" in out
    assert "skipped 2400600 -> 24006" in out
    assert "target ID already exists in: Contacts" in out
