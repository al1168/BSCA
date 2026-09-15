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
