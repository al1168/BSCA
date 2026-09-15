import calendar
import csv
import datetime
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import backfill_availability_from_attendance as mod


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _t(hour, minute=0):
    """Time-of-day as Access/pyodbc returns it."""
    return datetime.datetime(1899, 12, 30, hour, minute)


def _write_attendance_sheet(folder, center_id, name, month, days):
    """Create '<folder>/(id).Name Attendance YYYY-MM.xlsm' with one row per
    calendar day; `days` maps day-number -> (time_in, time_out) as
    datetime.time (12-hour, no AM/PM, like the real sheets)."""
    folder.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    wb.active.title = "Template"
    ws = wb.create_sheet("Attendance")
    ws["A1"] = f"Name: {name}(1.2.3)   Month, 2026  ID: {center_id}  MLTC: X"
    ws.append(["Date", "Day", "Time-In", "Time-Out"])
    year, mon = (int(p) for p in month.split("-"))
    for d in range(1, calendar.monthrange(year, mon)[1] + 1):
        dow = datetime.date(year, mon, d).strftime("%a")
        ti, to = days.get(d, (None, None))
        ws.append([d, dow, ti, to])
    path = folder / f"({center_id}).{name} Attendance {month}.xlsm"
    wb.save(path)   # xlsx bytes under an .xlsm name; the reader keys on the name
    return path


# ---------------------------------------------------------------------------
# _default_months / _parse_months
# ---------------------------------------------------------------------------

def test_default_months_three_ending_this_month():
    assert mod._default_months(datetime.date(2026, 9, 15)) == [
        "2026-07", "2026-08", "2026-09"]


def test_default_months_wraps_year():
    assert mod._default_months(datetime.date(2026, 1, 3)) == [
        "2025-11", "2025-12", "2026-01"]


def test_parse_months_flag():
    assert mod._parse_months("2026-07, 2026-08,2026-09") == [
        "2026-07", "2026-08", "2026-09"]
    with pytest.raises(ValueError):
        mod._parse_months("July 2026")


# ---------------------------------------------------------------------------
# read_month_sheets — yields (center_id, iso_weekday, in_min, out_min)
# ---------------------------------------------------------------------------

def test_read_month_sheets_yields_normalized_rows(tmp_path):
    att = tmp_path / "2026" / "08" / "Attendance"
    _write_attendance_sheet(att, 1001, "Zhang, Mingli", "2026-08", {
        3: (datetime.time(8, 21), datetime.time(12, 23)),   # Mon
        4: (datetime.time(9, 41), datetime.time(2, 0)),     # Tue, 02:00 -> 14:00
    })
    (att / "Daily Sign-in-out 2026-08.xlsm").write_bytes(b"")  # ignored by name
    errors = []
    rows = [r for r in mod.read_month_sheets(tmp_path, "2026-08", errors.append)
            if r[2] is not None or r[3] is not None]
    assert rows == [
        (1001, 1, 8 * 60 + 21, 12 * 60 + 23),
        (1001, 2, 9 * 60 + 41, 14 * 60),
    ]
    assert errors == []


def test_read_month_sheets_reports_unreadable_file(tmp_path):
    att = tmp_path / "2026" / "07" / "Attendance"
    att.mkdir(parents=True)
    (att / "(5).Bad, File Attendance 2026-07.xlsm").write_bytes(b"not a workbook")
    errors = []
    rows = list(mod.read_month_sheets(tmp_path, "2026-07", errors.append))
    assert rows == []
    assert len(errors) == 1 and "(5).Bad, File" in errors[0]


def test_read_month_sheets_missing_folder_is_an_error(tmp_path):
    errors = []
    rows = list(mod.read_month_sheets(tmp_path, "2026-06", errors.append))
    assert rows == []
    assert len(errors) == 1 and "2026-06" in errors[0]


# ---------------------------------------------------------------------------
# fake DB
# ---------------------------------------------------------------------------

class _FakeCursor:
    """Answers the queries the script issues.

    members: list of (cid_float, last, first, plan, hha) for active members.
    operating_days: list of (dow_int, closing_dt).
    open_rows: {(cid_str, day_int): (row_id, start_dt, end_dt)}
    """

    def __init__(self, members, open_rows, operating_days=None):
        self._members = members
        self._open_rows = open_rows
        self._operating_days = operating_days if operating_days is not None \
            else [(d, _t(14, 0)) for d in range(1, 8)]
        self.executed = []
        self.updates = []    # (start_time, end_time, notes, row_id)
        self.inserts = []    # (cid, eff_start, day, start_time, end_time, notes)
        self._pending_all = []
        self._pending = None
        self._next_row_id = 9000

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        if "FROM [Contacts]" in sql:
            self._pending_all = list(self._members)
        elif "FROM [OperatingDays]" in sql:
            self._pending_all = list(self._operating_days)
        elif sql.startswith("SELECT") and "FROM [Availability]" in sql:
            self._pending = self._open_rows.get((params[0], params[1]))
        elif sql.startswith("UPDATE [Availability]"):
            self.updates.append(params)
            start_t, end_t, notes, row_id = params
            for key, (rid, _s, _e) in self._open_rows.items():
                if rid == row_id:
                    self._open_rows[key] = (rid, start_t, end_t)
                    break
        elif sql.startswith("INSERT INTO [Availability]"):
            self.inserts.append(params)
            cid, _eff, day, start_t, end_t, _notes = params
            self._open_rows[(cid, day)] = (self._next_row_id, start_t, end_t)
            self._next_row_id += 1
        else:  # pragma: no cover
            raise AssertionError(f"unexpected SQL: {sql}")
        return self

    def fetchone(self):
        return self._pending

    def fetchall(self):
        rows, self._pending_all = self._pending_all, []
        return rows


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def test_fetch_active_members_normalizes_ids_and_blanks():
    cur = _FakeCursor(
        members=[(1001.0, "Zhang", "Mingli", "VCM", None),
                 (25.0, "Lin", "Bo Hua", None, "BetterChoice 7AM-11AM")],
        open_rows={})
    assert mod._fetch_active_members(cur) == [
        {"center_id": 1001, "last_name": "Zhang", "first_name": "Mingli",
         "health_plan": "VCM", "hha": ""},
        {"center_id": 25, "last_name": "Lin", "first_name": "Bo Hua",
         "health_plan": "", "hha": "BetterChoice 7AM-11AM"},
    ]


def test_fetch_closing_times_defaults_missing_days_to_16():
    cur = _FakeCursor(members=[], open_rows={},
                      operating_days=[(1, _t(14, 0)), (2, _t(14, 30))])
    closing = mod._fetch_closing_times(cur)
    assert closing[1] == 14 * 60
    assert closing[2] == 14 * 60 + 30
    assert closing[7] == 16 * 60


def test_fetch_open_window_present_and_absent():
    cur = _FakeCursor(members=[], open_rows={
        ("1001", 1): (42, _t(8, 0), _t(13, 0))})
    assert mod._fetch_open_window(cur, 1001, 1) == (42, (8 * 60, 13 * 60))
    assert mod._fetch_open_window(cur, 1001, 2) is None


def test_upsert_updates_existing_row_with_notes():
    cur = _FakeCursor(members=[], open_rows={
        ("1001", 1): (42, _t(8, 0), _t(13, 0))})
    old = mod._upsert_window(cur, 1001, 1, 8 * 60 + 20, 12 * 60 + 25,
                             "Attendance envelope 2026-07..09, n=13",
                             datetime.date(2026, 9, 15))
    assert old == (8 * 60, 13 * 60)
    assert cur.updates == [(datetime.time(8, 20), datetime.time(12, 25),
                            "Attendance envelope 2026-07..09, n=13", 42)]
    assert cur.inserts == []


def test_upsert_inserts_when_no_open_row():
    cur = _FakeCursor(members=[], open_rows={})
    old = mod._upsert_window(cur, 1001, 3, 8 * 60 + 20, 12 * 60 + 25, "note",
                             datetime.date(2026, 9, 15))
    assert old is None
    assert cur.inserts == [("1001", datetime.date(2026, 9, 15), 3,
                            datetime.time(8, 20), datetime.time(12, 25), "note")]


# ---------------------------------------------------------------------------
# main — end to end with fake DB + temp sheets
# ---------------------------------------------------------------------------

def _month_days(lo_in, lo_out):
    """Days 1..28 filled with (in, out) datetime.time pairs in 12-hour form.
    The drift is i % 13 minutes, so the envelope is lo..lo+12 and every
    weekday gets 4 samples per month (8 over two months, above min_samples)."""
    out = {}
    for i in range(28):
        drift = datetime.timedelta(minutes=i % 13)
        ti = (datetime.datetime(2000, 1, 1, *lo_in) + drift).time()
        to = (datetime.datetime(2000, 1, 1, *lo_out) + drift).time()
        out[i + 1] = (ti, to)
    return out


def _sheets(tmp_path):
    """Two months of sheets for member 1001 (morning) and 1500 (afternoon);
    member 777 has no sheets."""
    for month in ("2026-08", "2026-09"):
        att = tmp_path / month[:4] / month[5:] / "Attendance"
        _write_attendance_sheet(att, 1001, "Zhang, Mingli", month,
                                _month_days((8, 21), (12, 23)))
        # afternoon: 12:32 in, 04:50 (= 16:50) out
        _write_attendance_sheet(att, 1500, "Yuan, XiaoFen", month,
                                _month_days((12, 32), (4, 50)))
    return tmp_path


def _run(tmp_path, monkeypatch, extra_args=(), members=None, open_rows=None):
    db = tmp_path / "test.accdb"
    db.write_bytes(b"fake")
    members = members if members is not None else [
        (1001.0, "Zhang", "Mingli", "VCM", ""),
        (1500.0, "Yuan", "XiaoFen", "EMPIRE-BCBS", "ABI 1-7 8am-12pm"),
        (777.0, "New", "Member", "HF", None),
    ]
    open_rows = open_rows if open_rows is not None else {
        (str(cid), d): (cid * 10 + d, _t(8, 0), _t(13, 0))
        for cid in (1001, 1500, 777) for d in range(1, 8)
    }
    cursor = _FakeCursor(members=members, open_rows=open_rows)
    conn = _FakeConn(cursor)
    monkeypatch.setattr("pyodbc.connect", lambda cs: conn)
    monkeypatch.setattr(mod, "_today", lambda: datetime.date(2026, 9, 15))
    rc = mod.main([
        "--db", str(db), "--sheets-root", str(_sheets(tmp_path)),
        "--months", "2026-08,2026-09", "--quiet", *extra_args,
    ])
    return rc, cursor, conn, db


def _report_rows(db):
    path = db.parent / "attendance_availability_2026-09-15.csv"
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_main_writes_all_seven_weekdays_for_covered_members(tmp_path, monkeypatch):
    rc, cursor, conn, db = _run(tmp_path, monkeypatch)
    assert rc == 0
    assert conn.committed and not conn.rolled_back
    # 2 covered members x 7 weekdays, member 777 untouched
    assert len(cursor.updates) == 14
    assert cursor.inserts == []
    updated_ids = {u[3] for u in cursor.updates}
    assert all(rid // 10 in (1001, 1500) for rid in updated_ids)


def test_main_envelope_values_and_notes(tmp_path, monkeypatch):
    _, cursor, _, _ = _run(tmp_path, monkeypatch)
    by_row = {u[3]: u for u in cursor.updates}
    # 1001 Monday, 8 samples over Aug+Sep with drift 0..12 min:
    # 08:21..08:33 -> 08:20; 12:23..12:35 -> 12:35
    start, end, notes, _ = by_row[1001 * 10 + 1]
    assert (start, end) == (datetime.time(8, 20), datetime.time(12, 35))
    assert notes.startswith("Attendance envelope 2026-08..09, n=")
    # 1500 afternoon Monday: Mondays fall on drifts {2,9,3,10} in Aug and
    # {6,0,7,1} in Sep, so the max drift is 10: 12:32 -> 12:30;
    # 16:50+10 = 17:00 -> 17:00
    start, end, _, _ = by_row[1500 * 10 + 1]
    assert (start, end) == (datetime.time(12, 30), datetime.time(17, 0))


def test_main_report_rows_and_flags(tmp_path, monkeypatch):
    _, _, _, db = _run(tmp_path, monkeypatch)
    rows = _report_rows(db)
    assert len(rows) == 14 + 1        # 7 per covered member + one no_data row
    r1001 = [r for r in rows if r["center_id"] == "1001" and r["day"] == "1"][0]
    assert r1001["old_window"] == "08:00-13:00"
    assert r1001["new_window"] == "08:20-12:35"
    assert r1001["flags"] == ""
    r1500 = [r for r in rows if r["center_id"] == "1500" and r["day"] == "1"][0]
    assert r1500["flags"] == "past_close;afternoon_only"
    assert r1500["hha"] == "ABI 1-7 8am-12pm"
    r777 = [r for r in rows if r["center_id"] == "777"][0]
    assert r777["flags"] == "no_data" and r777["day"] == "" and r777["new_window"] == ""


def test_main_flags_hand_edit_replaced(tmp_path, monkeypatch):
    open_rows = {(str(cid), d): (cid * 10 + d, _t(8, 0), _t(13, 0))
                 for cid in (1001, 1500, 777) for d in range(1, 8)}
    open_rows[("1001", 2)] = (10012, _t(8, 0), _t(14, 0))   # hand edit
    _, _, _, db = _run(tmp_path, monkeypatch, open_rows=open_rows)
    r = [r for r in _report_rows(db) if r["center_id"] == "1001" and r["day"] == "2"][0]
    assert r["old_window"] == "08:00-14:00"
    assert "hand_edit_replaced" in r["flags"].split(";")


def test_main_inserts_when_member_has_no_open_rows(tmp_path, monkeypatch):
    _, cursor, _, _ = _run(tmp_path, monkeypatch, open_rows={})
    assert cursor.updates == []
    assert len(cursor.inserts) == 14
    assert cursor.inserts[0][1] == datetime.date(2026, 9, 15)


def test_main_dry_run_rolls_back_no_backup_but_reports(tmp_path, monkeypatch):
    rc, cursor, conn, db = _run(tmp_path, monkeypatch, extra_args=["--dry-run"])
    assert rc == 0
    assert conn.rolled_back and not conn.committed
    assert len(cursor.updates) == 14           # writes issued, then rolled back
    assert not list(tmp_path.glob("*.backup_*.accdb"))
    assert len(_report_rows(db)) == 15


def test_main_apply_takes_backup_copy(tmp_path, monkeypatch):
    _, _, _, db = _run(tmp_path, monkeypatch)
    backups = list(tmp_path.glob("test.backup_*.accdb"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"fake"


def test_main_missing_db_returns_2(tmp_path, capsys):
    rc = mod.main(["--db", str(tmp_path / "nope.accdb"),
                   "--sheets-root", str(tmp_path)])
    assert rc == 2
    assert "database not found" in capsys.readouterr().err


def test_main_bad_months_returns_2(tmp_path, capsys):
    db = tmp_path / "x.accdb"
    db.write_bytes(b"")
    rc = mod.main(["--db", str(db), "--months", "August"])
    assert rc == 2
    assert "YYYY-MM" in capsys.readouterr().err


def test_main_no_sheets_returns_2_without_backup(tmp_path, capsys):
    db = tmp_path / "x.accdb"
    db.write_bytes(b"")
    rc = mod.main(["--db", str(db), "--sheets-root", str(tmp_path),
                   "--months", "2026-01"])
    assert rc == 2
    assert "no Attendance samples" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.backup_*.accdb"))


def test_main_summary_mentions_reserve_checkboxes(tmp_path, monkeypatch, capsys):
    _run(tmp_path, monkeypatch, extra_args=["--dry-run"])
    out = capsys.readouterr().out
    assert "Drop-off by availability end" in out
    assert "Pick-up by availability start" in out
    assert "DRY-RUN" in out
