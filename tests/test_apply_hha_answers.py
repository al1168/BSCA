import csv
import datetime
import sys
from pathlib import Path

import pytest

# Ensure the script is importable as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import apply_hha_answers as apply_mod


def _t(hour, minute=0):
    """Time-of-day as Access/pyodbc returns it: a datetime with the
    1899-12-30 placeholder date."""
    return datetime.datetime(1899, 12, 30, hour, minute)


class _FakeCursor:
    """Answers the three queries the script issues.

    contacts_ids: set[int] — Center IDs that exist in Contacts.
    open_rows: {(center_id_str, day_int): (row_id, start_dt, end_dt)}

    Models read-your-own-writes inside the transaction: UPDATEs mutate
    the matching _open_rows entry, INSERTs add a new entry with a
    synthetic row_id, so later SELECTs see uncommitted writes.
    """

    def __init__(self, contacts_ids, open_rows):
        self._contacts_ids = contacts_ids
        self._open_rows = open_rows
        self.executed = []      # every (sql, params)
        self.updates = []       # (start_time, end_time, row_id)
        self.inserts = []       # (cid, eff_start, day, start_time, end_time)
        self._pending = None    # next fetchone() result
        self._next_row_id = 9000    # synthetic ids for INSERTed rows

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        if "FROM [Contacts]" in sql:
            cid = params[0]
            self._pending = (cid,) if cid in self._contacts_ids else None
        elif sql.startswith("SELECT") and "FROM [Availability]" in sql:
            self._pending = self._open_rows.get((params[0], params[1]))
        elif sql.startswith("UPDATE [Availability]"):
            self.updates.append(params)
            start_t, end_t, row_id = params
            for key, (rid, _s, _e) in self._open_rows.items():
                if rid == row_id:
                    # The script's _time_to_minutes accepts plain
                    # datetime.time, so store the times as written.
                    self._open_rows[key] = (rid, start_t, end_t)
                    break
            self._pending = None
        elif sql.startswith("INSERT INTO [Availability]"):
            self.inserts.append(params)
            cid, _eff_start, day, start_t, end_t = params
            self._open_rows[(cid, day)] = (
                self._next_row_id, start_t, end_t,
            )
            self._next_row_id += 1
            self._pending = None
        else:  # pragma: no cover - unexpected SQL is a test failure
            raise AssertionError(f"unexpected SQL: {sql}")
        return self

    def fetchone(self):
        return self._pending


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
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


_CSV_HEADER = [
    "center_id", "last_name", "first_name", "answer",
    "raw_hha", "reason", "attempted_parse",
]


def _write_answers_csv(path, rows):
    """rows: list of (center_id, last, first, answer)."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(_CSV_HEADER)
        for cid, last, first, answer in rows:
            w.writerow([cid, last, first, answer, "raw", "reason", "parse"])


def _run(tmp_path, monkeypatch, csv_rows, cursor, extra_argv=()):
    """Write the answers CSV, patch pyodbc.connect, run main()."""
    csv_path = tmp_path / "answers.csv"
    _write_answers_csv(csv_path, csv_rows)
    db_path = tmp_path / "members.accdb"
    db_path.touch()
    conn = _FakeConn(cursor)
    monkeypatch.setattr("pyodbc.connect", lambda cs: conn)
    rc = apply_mod.main(
        ["--csv", str(csv_path), "--db", str(db_path), *extra_argv]
    )
    return rc, conn


def _read_review_csv(tmp_path):
    matches = list(tmp_path.glob("hha_answers_review_*.csv"))
    assert len(matches) == 1, matches
    with open(matches[0], encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Environment errors
# ---------------------------------------------------------------------------

def test_missing_csv_returns_2(tmp_path, capsys):
    db = tmp_path / "m.accdb"
    db.touch()
    rc = apply_mod.main(
        ["--csv", str(tmp_path / "nope.csv"), "--db", str(db)]
    )
    assert rc == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_missing_db_returns_2(tmp_path, capsys):
    csv_path = tmp_path / "answers.csv"
    _write_answers_csv(csv_path, [])
    rc = apply_mod.main(
        ["--csv", str(csv_path), "--db", str(tmp_path / "nope.accdb")]
    )
    assert rc == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_csv_without_required_columns_returns_2(tmp_path, monkeypatch, capsys):
    csv_path = tmp_path / "answers.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerow(["something", "else"])
    db = tmp_path / "m.accdb"
    db.touch()
    monkeypatch.setattr(
        "pyodbc.connect", lambda cs: _FakeConn(_FakeCursor(set(), {}))
    )
    rc = apply_mod.main(["--csv", str(csv_path), "--db", str(db)])
    assert rc == 2
    assert "missing columns" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# Core behavior
# ---------------------------------------------------------------------------

def test_back_overlap_updates_open_row(tmp_path, monkeypatch, capsys):
    """25023 day 7 `12 PM - 4 PM` vs open 08:00-13:00 -> end 12:00."""
    cursor = _FakeCursor(
        contacts_ids={25023},
        open_rows={("25023", 7): (41, _t(8), _t(13))},
    )
    rc, conn = _run(
        tmp_path, monkeypatch,
        [("25023", "Lin", "Zi C", "7 (12 PM - 4 PM)")],
        cursor,
    )
    assert rc == 0
    assert conn.committed and not conn.rolled_back
    assert cursor.updates == [
        (datetime.time(8, 0), datetime.time(12, 0), 41),
    ]
    assert cursor.inserts == []
    out = capsys.readouterr().out
    assert "Days updated:                   1" in out
    assert _read_review_csv(tmp_path) == []   # nothing flagged


def test_front_overlap_pushes_start(tmp_path, monkeypatch):
    """25035 `4.5 (6 AM - 12 PM)` -> start pushed to 12:00 on both days."""
    cursor = _FakeCursor(
        contacts_ids={25035},
        open_rows={
            ("25035", 4): (10, _t(8), _t(13)),
            ("25035", 5): (11, _t(8), _t(13)),
        },
    )
    rc, conn = _run(
        tmp_path, monkeypatch,
        [("25035", "Chen", "QiRui", "4.5 (6 AM - 12 PM)")],
        cursor,
    )
    assert rc == 0
    assert sorted(cursor.updates, key=lambda u: u[2]) == [
        (datetime.time(12, 0), datetime.time(13, 0), 10),
        (datetime.time(12, 0), datetime.time(13, 0), 11),
    ]


def test_no_overlap_writes_nothing(tmp_path, monkeypatch, capsys):
    """After-close care (5 PM - 9 PM) changes nothing, counted unchanged."""
    cursor = _FakeCursor(
        contacts_ids={2528900},
        open_rows={("2528900", d): (50 + d, _t(8), _t(13))
                   for d in (1, 5, 6, 7)},
    )
    rc, conn = _run(
        tmp_path, monkeypatch,
        [("2528900", "Tao", "YanEr", "1.5.6.7 (5 PM - 9 PM)")],
        cursor,
    )
    assert rc == 0
    assert cursor.updates == []
    assert cursor.inserts == []
    assert "Days unchanged (no overlap):    4" in capsys.readouterr().out


def test_split_keeps_longer_piece_and_flags(tmp_path, monkeypatch):
    """25249 `6.7 (8:30 AM - 12 PM)` vs 08:00-13:00 -> keep 12:00-13:00,
    flag `split` with the dropped piece in the note."""
    cursor = _FakeCursor(
        contacts_ids={25249},
        open_rows={
            ("25249", 6): (60, _t(8), _t(13)),
            ("25249", 7): (61, _t(8), _t(13)),
        },
    )
    rc, _ = _run(
        tmp_path, monkeypatch,
        [("25249", "Zheng", "Shui Guo", "6.7 (8:30 AM - 12 PM)")],
        cursor,
    )
    assert rc == 0
    assert sorted(cursor.updates, key=lambda u: u[2]) == [
        (datetime.time(12, 0), datetime.time(13, 0), 60),
        (datetime.time(12, 0), datetime.time(13, 0), 61),
    ]
    review = _read_review_csv(tmp_path)
    assert [r["flag"] for r in review] == ["split", "split"]
    assert review[0]["day"] == "6"
    assert review[0]["old_window"] == "08:00-13:00"
    assert review[0]["new_window"] == "12:00-13:00"
    assert "08:00-08:30" in review[0]["note"]


def test_blocked_day_not_written_but_flagged(tmp_path, monkeypatch):
    """Care 6:30 AM - 1:30 PM swallows 08:00-13:00: no write, flag."""
    cursor = _FakeCursor(
        contacts_ids={2509500},
        open_rows={("2509500", 4): (70, _t(8), _t(13))},
    )
    rc, _ = _run(
        tmp_path, monkeypatch,
        [("2509500", "Xie", "Gui Ying", "4 (6:30 AM - 1:30 PM)")],
        cursor,
    )
    assert rc == 0
    assert cursor.updates == []
    review = _read_review_csv(tmp_path)
    assert [r["flag"] for r in review] == ["blocked"]
    assert review[0]["new_window"] == ""
    assert review[0]["old_window"] == "08:00-13:00"


def test_no_open_row_inserts_against_default(tmp_path, monkeypatch):
    """No open Availability row: subtract against the 08:00-13:00
    default and INSERT the result with today's effective_start_date."""
    cursor = _FakeCursor(contacts_ids={25023}, open_rows={})
    rc, _ = _run(
        tmp_path, monkeypatch,
        [("25023", "Lin", "Zi C", "7 (12 PM - 4 PM)")],
        cursor,
    )
    assert rc == 0
    assert cursor.updates == []
    assert len(cursor.inserts) == 1
    cid, eff_start, day, start_t, end_t = cursor.inserts[0]
    assert cid == "25023"
    assert eff_start == datetime.date.today()
    assert day == 7
    assert (start_t, end_t) == (datetime.time(8, 0), datetime.time(12, 0))


def test_no_open_row_no_overlap_still_inserts_default(tmp_path, monkeypatch):
    """A day named in the answer with no open row gets the default
    window inserted even when care doesn't overlap it (spec: every
    named day ends up with a row)."""
    cursor = _FakeCursor(contacts_ids={2528900}, open_rows={})
    rc, _ = _run(
        tmp_path, monkeypatch,
        [("2528900", "Tao", "YanEr", "1 (5 PM - 9 PM)")],
        cursor,
    )
    assert rc == 0
    assert len(cursor.inserts) == 1
    cid, eff_start, day, start_t, end_t = cursor.inserts[0]
    assert (cid, day) == ("2528900", 1)
    assert (start_t, end_t) == (datetime.time(8, 0), datetime.time(13, 0))


def test_blank_answer_skipped_without_db_access(tmp_path, monkeypatch, capsys):
    cursor = _FakeCursor(contacts_ids=set(), open_rows={})
    rc, _ = _run(
        tmp_path, monkeypatch,
        [("24109", "Chen", "Wusong", "")],
        cursor,
    )
    assert rc == 0
    assert cursor.executed == []    # never touched the DB
    assert "Blank answers skipped:          1" in capsys.readouterr().out


def test_parse_error_flags_row_and_isolates_it(tmp_path, monkeypatch):
    """A malformed answer flags that row; the next row still applies."""
    cursor = _FakeCursor(
        contacts_ids={25023},
        open_rows={("25023", 7): (41, _t(8), _t(13))},
    )
    rc, _ = _run(
        tmp_path, monkeypatch,
        [
            ("99999", "Bad", "Row", "1 (3 PM - 1 PM)"),
            ("25023", "Lin", "Zi C", "7 (12 PM - 4 PM)"),
        ],
        cursor,
    )
    assert rc == 0
    assert len(cursor.updates) == 1
    review = _read_review_csv(tmp_path)
    assert [r["flag"] for r in review] == ["parse_error"]
    assert review[0]["center_id"] == "99999"
    assert review[0]["day"] == ""


def test_unknown_member_flagged(tmp_path, monkeypatch):
    cursor = _FakeCursor(contacts_ids=set(), open_rows={})
    rc, _ = _run(
        tmp_path, monkeypatch,
        [("11111", "Ghost", "Member", "1 (12 PM - 4 PM)")],
        cursor,
    )
    assert rc == 0
    assert cursor.updates == [] and cursor.inserts == []
    review = _read_review_csv(tmp_path)
    assert [r["flag"] for r in review] == ["member_not_found"]


def test_dry_run_rolls_back_but_writes_review_csv(
    tmp_path, monkeypatch, capsys,
):
    cursor = _FakeCursor(
        contacts_ids={25249},
        open_rows={("25249", 6): (60, _t(8), _t(13))},
    )
    rc, conn = _run(
        tmp_path, monkeypatch,
        [("25249", "Zheng", "Shui Guo", "6 (8:30 AM - 12 PM)")],
        cursor,
        extra_argv=["--dry-run"],
    )
    assert rc == 0
    assert conn.rolled_back and not conn.committed
    assert len(_read_review_csv(tmp_path)) == 1   # still written
    assert "DRY-RUN" in capsys.readouterr().out


def test_duplicate_csv_rows_same_day_subtract_cumulatively(
    tmp_path, monkeypatch,
):
    """The same member appearing twice narrows sequentially: the second
    row's SELECT sees the first row's uncommitted UPDATE."""
    cursor = _FakeCursor(
        contacts_ids={25023},
        open_rows={("25023", 7): (41, _t(8), _t(13))},
    )
    rc, _ = _run(
        tmp_path, monkeypatch,
        [
            ("25023", "Lin", "Zi C", "7 (12 PM - 4 PM)"),
            ("25023", "Lin", "Zi C", "7 (8 AM - 9 AM)"),
        ],
        cursor,
    )
    assert rc == 0
    assert cursor.updates == [
        (datetime.time(8, 0), datetime.time(12, 0), 41),
        (datetime.time(9, 0), datetime.time(12, 0), 41),
    ]


def test_multi_group_same_day_subtracts_sequentially(tmp_path, monkeypatch):
    """Two groups hitting day 1 (morning 8-9 AM and afternoon 12-4 PM
    care) leave 09:00-12:00."""
    cursor = _FakeCursor(
        contacts_ids={25361},
        open_rows={("25361", 1): (80, _t(8), _t(13))},
    )
    rc, _ = _run(
        tmp_path, monkeypatch,
        [("25361", "Lin", "Zhu Ying", "1 (8 AM - 9 AM) | 1 (12 PM - 4 PM)")],
        cursor,
    )
    assert rc == 0
    assert cursor.updates == [
        (datetime.time(9, 0), datetime.time(12, 0), 80),
    ]
