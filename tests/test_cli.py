import new_monthly_schedule as cli

from datetime import date


def _fake_enrollments(cid=24010):
    return [{"id": 1, "center_id": cid,
             "start_date": date(2026, 1, 1), "end_date": None}]


def _fake_authorizations(cid=24010, auth_days="1.3.4.5"):
    return [{"id": 1, "center_id": cid,
             "auth_start": date(2026, 1, 1),
             "auth_end": date(2026, 12, 31),
             "effective_start": date(2026, 1, 1),
             "effective_end": date(2026, 12, 31),
             "auth_days": auth_days}]


FAKE_MEMBER = {
    "center_id": 24010,
    "last_name": "Cheng",
    "first_name": "Lizhu",
    "health_plan": "HOF",
    "address": "1 Main St, NY",
    "long_lat": None,
}

FAKE_MEMBER_2 = {
    "center_id": 24011,
    "last_name": "Smith",
    "first_name": "John",
    "health_plan": "HOF",
    "address": "2 Main St, NY",
    "long_lat": None,
}


import pytest


@pytest.fixture(autouse=True)
def _stub_travel(monkeypatch):
    """Neutralize travel + new DB lookups for legacy tests.

    Injects --api-key K into every parse_args call so individual tests
    don't have to thread the flag through every cli.main() invocation.
    """
    _real_parse_args = cli.parse_args

    def _parse_args_with_key(argv):
        if "--api-key" not in argv:
            argv = list(argv) + ["--api-key", "K"]
        return _real_parse_args(argv)

    monkeypatch.setattr(cli, "parse_args", _parse_args_with_key)
    monkeypatch.setattr(cli, "load_cache", lambda path: {})
    monkeypatch.setattr(cli, "save_cache", lambda path, cache: None)
    monkeypatch.setattr(cli, "load_time_cache", lambda path: {})
    monkeypatch.setattr(cli, "save_time_cache", lambda path, cache: None)
    monkeypatch.setattr(
        cli, "resolve_travel_minutes",
        lambda member, api_key, cache: 10,
    )
    monkeypatch.setattr(
        cli, "get_enrollments",
        lambda cid, db: _fake_enrollments(cid),
    )
    monkeypatch.setattr(
        cli, "get_authorizations",
        lambda cid, db: _fake_authorizations(cid),
    )
    monkeypatch.setattr(cli, "get_absences", lambda cid, db: [])
    monkeypatch.setattr(cli, "get_availability", lambda cid, db: [])
    monkeypatch.setattr(cli, "get_one_offs", lambda cid, db: [])


def test_preview_data_returns_zero_and_prints(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--preview-data"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "2026-05-01" in out
    assert out.count("\n") >= 31  # one line per day
    assert "=== ID 24010 (Cheng, Lizhu) ===" in out


def test_no_member_returns_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: None)
    rc = cli.main(
        ["--center-id", "999", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "ID 999: lookup — not found in database" in err


def test_writes_workbook(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 0
    assert (tmp_path / "Schedule_24010_2026-05.xlsx").exists()


def test_invalid_month_rejected(monkeypatch):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    import pytest
    with pytest.raises(SystemExit):
        cli.main(
            ["--center-id", "24010", "--year", "2026", "--month", "13",
             "--preview-data"]
        )


def test_missing_db_returns_1(monkeypatch, capsys):
    def _raise(cid, db):
        raise FileNotFoundError("Database not found: X")
    monkeypatch.setattr(cli, "get_member", _raise)
    rc = cli.main(["--center-id", "24010", "--year", "2026", "--month", "5",
                   "--preview-data"])
    assert rc == 1
    assert "Database not found" in capsys.readouterr().err


def test_driver_error_returns_1(monkeypatch, capsys):
    def _raise(cid, db):
        raise RuntimeError("Could not open the Access database. ...")
    monkeypatch.setattr(cli, "get_member", _raise)
    rc = cli.main(["--center-id", "24010", "--year", "2026", "--month", "5",
                   "--preview-data"])
    assert rc == 1
    assert "Could not open the Access database" in capsys.readouterr().err


def test_main_reads_sys_argv_when_argv_none(monkeypatch):
    """Exercises the argv is None branch (real CLI invocation path)."""
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    monkeypatch.setattr(
        cli.sys, "argv",
        ["new_monthly_schedule.py", "--center-id", "24010",
         "--year", "2026", "--month", "5", "--preview-data"],
    )
    assert cli.main() == 0


def test_parse_center_ids_basic():
    assert cli.parse_center_ids("24010,24011") == [24010, 24011]


def test_parse_center_ids_trims_dedupes_drops_blanks_keeps_order():
    assert cli.parse_center_ids("24011, 24010 ,,24011") == [24011, 24010]


def test_parse_center_ids_empty():
    assert cli.parse_center_ids("") == []
    assert cli.parse_center_ids(" , , ") == []


def test_parse_center_ids_non_int_raises():
    with pytest.raises(ValueError):
        cli.parse_center_ids("24010,abc")


import os


def test_schedule_filename():
    assert cli.schedule_filename(24010, 2026, 5) == \
        "Schedule_24010_2026-05.xlsx"


def test_resolve_output_dir_non_plan_is_base():
    assert cli.resolve_output_dir(".", None, 2026, 5) == "."
    assert cli.resolve_output_dir("out", None, 2026, 5) == "out"


def test_resolve_output_dir_plan_nests_uppercased_subdir():
    assert cli.resolve_output_dir("out", "hof", 2026, 5) == \
        os.path.join("out", "HOF_2026-05")


def test_format_summary_all_success_headline_only():
    s = cli.format_summary("Wrote", 2, 2, "2026-05", "out", [])
    assert s == "Wrote 2 of 2 member(s) for 2026-05 into out; 0 failed."
    assert "Failures:" not in s


def test_format_summary_preview_no_outdir():
    s = cli.format_summary("Previewed", 1, 1, "2026-05", None, [])
    assert s == "Previewed 1 of 1 member(s) for 2026-05; 0 failed."


def test_format_summary_with_failures_lists_them():
    failures = [
        cli.Failure(24099, "", "lookup", "not found in database", None),
        cli.Failure(24100, "Smith, John", "write",
                    "PermissionError — denied", None),
    ]
    s = cli.format_summary(
        "Wrote", 18, 20, "plan HOF 2026-05", "out/HOF_2026-05", failures
    )
    lines = s.split("\n")
    assert lines[0] == (
        "Wrote 18 of 20 member(s) for plan HOF 2026-05 "
        "into out/HOF_2026-05; 2 failed."
    )
    assert lines[1] == "Failures:"
    assert lines[2] == "  - ID 24099: lookup — not found in database"
    assert lines[3] == (
        "  - ID 24100 (Smith, John): write — "
        "PermissionError — denied"
    )


def test_parse_args_requires_a_selector():
    with pytest.raises(SystemExit):
        cli.parse_args(["--year", "2026", "--month", "5"])


def test_parse_args_rejects_two_selectors():
    with pytest.raises(SystemExit):
        cli.parse_args(
            ["--center-id", "1", "--plan", "HOF",
             "--year", "2026", "--month", "5"]
        )


def test_parse_args_accepts_each_selector():
    a = cli.parse_args(
        ["--center-ids", "1,2", "--year", "2026", "--month", "5"]
    )
    assert a.center_ids == "1,2"
    assert a.center_id is None and a.plan is None
    b = cli.parse_args(
        ["--plan", "HOF", "--year", "2026", "--month", "5"]
    )
    assert b.plan == "HOF"
    assert b.output_path == "."  # new default: base directory


def test_single_writes_into_output_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 0
    assert (tmp_path / "Schedule_24010_2026-05.xlsx").exists()


def test_center_ids_batch_one_not_found(monkeypatch, tmp_path, capsys):
    def fake_get_member(cid, db):
        return FAKE_MEMBER if cid == 24010 else None
    monkeypatch.setattr(cli, "get_member", fake_get_member)
    rc = cli.main(
        ["--center-ids", "24010,24099", "--year", "2026",
         "--month", "5", "--output-path", str(tmp_path)]
    )
    assert rc == 2
    assert (tmp_path / "Schedule_24010_2026-05.xlsx").exists()
    err = capsys.readouterr().err
    assert "Wrote 1 of 2 member(s) for 2026-05" in err
    assert "Failures:" in err
    assert "ID 24099: lookup — not found in database" in err


def test_plan_writes_into_subdir(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli, "get_members_by_plan",
        lambda code, db: [FAKE_MEMBER, FAKE_MEMBER_2],
    )
    rc = cli.main(
        ["--plan", "hof", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 0
    sub = tmp_path / "HOF_2026-05"
    assert (sub / "Schedule_24010_2026-05.xlsx").exists()
    assert (sub / "Schedule_24011_2026-05.xlsx").exists()
    assert "for plan HOF 2026-05" in capsys.readouterr().err


def test_plan_no_members(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli, "get_members_by_plan", lambda code, db: []
    )
    rc = cli.main(
        ["--plan", "HOF", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 2
    assert "No members found for plan HOF" in capsys.readouterr().err
    assert not (tmp_path / "HOF_2026-05").exists()


def test_preview_batch_prints_headers_no_files(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli, "get_members_by_plan",
        lambda code, db: [FAKE_MEMBER, FAKE_MEMBER_2],
    )
    rc = cli.main(
        ["--plan", "hof", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path), "--preview-data"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "=== ID 24010 (Cheng, Lizhu) ===" in out
    assert "=== ID 24011 (Smith, John) ===" in out
    assert not (tmp_path / "HOF_2026-05").exists()


def test_write_failure_reported_in_summary(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)

    def boom(member, rows, path):
        raise PermissionError("denied")
    monkeypatch.setattr(cli, "build_workbook", boom)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "Failures:" in err
    assert "ID 24010 (Cheng, Lizhu): write — PermissionError — denied" \
        in err


def test_travel_minutes_applied_to_pickup_and_dropoff(
        monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    monkeypatch.setattr(
        cli, "resolve_travel_minutes",
        lambda member, api_key, cache: 7,
    )
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--preview-data"]
    )
    assert rc == 0
    out = capsys.readouterr().out

    def to_min(hhmm):
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    from monthly_schedule.rules import SCHEDULE_RULES
    buf_lo, buf_hi = SCHEDULE_RULES["Default"]["travel_buffer_min"]
    travel_minutes = 7

    seen = False
    for line in out.splitlines():
        if not line.startswith("{"):
            continue
        row = eval(line)  # printed dict literal
        if row["arrival"] == "":
            continue
        lead = to_min(row["arrival"]) - to_min(row["pickup"])
        trail = to_min(row["dropoff"]) - to_min(row["departure"])
        assert travel_minutes + buf_lo <= lead <= travel_minutes + buf_hi
        assert travel_minutes + buf_lo <= trail <= travel_minutes + buf_hi
        seen = True
    assert seen  # at least one eligible day was checked


def test_travel_failure_skips_member_in_summary(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)

    def boom(member, api_key, cache):
        raise cli.TravelError("geocode", "ZERO_RESULTS for 'x'")
    monkeypatch.setattr(cli, "resolve_travel_minutes", boom)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "Failures:" in err
    assert ("ID 24010 (Cheng, Lizhu): geocode — "
            "ZERO_RESULTS for 'x'") in err
    assert not (tmp_path / "Schedule_24010_2026-05.xlsx").exists()


def test_no_enrollment_yields_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    monkeypatch.setattr(cli, "get_enrollments", lambda cid, db: [])
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "eligibility — not enrolled during this month" in err


def test_no_authorization_yields_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    monkeypatch.setattr(cli, "get_authorizations", lambda cid, db: [])
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "eligibility — no active authorization for this month" in err


# ---------------------------------------------------------------------------
# write_skipped_members_csv
# ---------------------------------------------------------------------------

from new_monthly_schedule import write_skipped_members_csv, Failure


def test_write_skipped_members_csv_empty_returns_none(tmp_path):
    """Empty failures list returns None and writes nothing."""
    result = write_skipped_members_csv(
        [], str(tmp_path), today=date(2026, 6, 4)
    )
    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_write_skipped_members_csv_filename_uses_today(tmp_path):
    """The returned path is `skipped_members_<today>.csv` in out_dir."""
    failures = [
        Failure(24010, "Cheng, Lizhu", "lookup", "not found", None),
    ]
    result = write_skipped_members_csv(
        failures, str(tmp_path), today=date(2026, 6, 4)
    )
    expected_path = tmp_path / "skipped_members_2026-06-04.csv"
    assert result == str(expected_path)
    assert expected_path.exists()
    lines = expected_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "center_id,name,stage,reason,day"


def test_write_skipped_members_csv_includes_all_stages(tmp_path):
    """All failure stages appear in the CSV. The `day` column is the ISO
    date only for one_off_conflict rows and empty for everything else."""
    failures = [
        Failure(24010, "Cheng, Lizhu", "lookup", "not found in database", None),
        Failure(24011, "Smith, John", "eligibility", "not enrolled", None),
        Failure(24012, "Jones, Mary", "geocode", "ZERO_RESULTS for 'x'", None),
        Failure(24013, "Park, Eun", "one_off_conflict",
                "one-off on auth day", date(2026, 6, 5)),
    ]
    result = write_skipped_members_csv(
        failures, str(tmp_path), today=date(2026, 6, 4)
    )
    expected_path = tmp_path / "skipped_members_2026-06-04.csv"
    assert result == str(expected_path)
    content = expected_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[0] == "center_id,name,stage,reason,day"
    assert len(lines) == 5  # header + 4 failures
    assert lines[1] == '24010,"Cheng, Lizhu",lookup,not found in database,'
    assert lines[2] == '24011,"Smith, John",eligibility,not enrolled,'
    assert lines[3] == '24012,"Jones, Mary",geocode,ZERO_RESULTS for \'x\','
    assert lines[4] == (
        '24013,"Park, Eun",one_off_conflict,one-off on auth day,2026-06-05'
    )


# ---------------------------------------------------------------------------
# Custom day range
# ---------------------------------------------------------------------------


def test_range_suffix_added_to_schedule_filename():
    assert cli.schedule_filename(24010, 2026, 5, 1, 19) == \
        "Schedule_24010_2026-05_01-19.xlsx"


def test_no_range_omits_filename_suffix():
    assert cli.schedule_filename(24010, 2026, 5) == \
        "Schedule_24010_2026-05.xlsx"


def test_debug_filename_with_range():
    assert cli.debug_filename(2026, 5, 1, 19) == "Debug_2026-05_01-19.csv"


def test_debug_filename_without_range():
    assert cli.debug_filename(2026, 5) == "Debug_2026-05.csv"


def test_cli_range_writes_to_range_suffixed_file(monkeypatch, tmp_path):
    """--start-day/--end-day produce a schedule with the suffixed name."""
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path),
         "--start-day", "1", "--end-day", "19"]
    )
    assert rc == 0
    assert (tmp_path / "Schedule_24010_2026-05_01-19.xlsx").exists()
    assert not (tmp_path / "Schedule_24010_2026-05.xlsx").exists()


def test_cli_range_invalid_returns_2(monkeypatch, tmp_path, capsys):
    """end-day past the last day of the month exits cleanly with rc=2."""
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "4",
         "--output-path", str(tmp_path),
         "--end-day", "31"]  # April has 30 days
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "end_day 31 exceeds last day of 2026-04" in err


def test_partial_then_full_run_reuses_cached_times(
        monkeypatch, tmp_path):
    """Run May 1-19 with --time-cache, then May 1-31 with the SAME
    cache. Days 1-19 must come back with the exact times they had on
    the partial run; days 20-31 are freshly generated."""
    import openpyxl

    # The fixture stubs load_time_cache/save_time_cache. This test
    # specifically needs the real disk persistence to verify cache
    # round-trip, so put the real implementations back.
    from monthly_schedule.time_cache import (
        load_time_cache as _real_load,
        save_time_cache as _real_save,
    )
    monkeypatch.setattr(cli, "load_time_cache", _real_load)
    monkeypatch.setattr(cli, "save_time_cache", _real_save)
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    cache_path = tmp_path / "tc.json"
    partial_dir = tmp_path / "partial"
    partial_dir.mkdir()
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(partial_dir),
         "--start-day", "1", "--end-day", "19",
         "--time-cache", str(cache_path)]
    )
    assert rc == 0
    partial_wb = openpyxl.load_workbook(
        str(partial_dir / "Schedule_24010_2026-05_01-19.xlsx")
    )
    partial_sheet = partial_wb.active

    # Capture each Date → arrival cell from the Attendance/Trans table.
    # The Pickup time is in the transportation table starting at col F.
    from monthly_schedule.workbook import (
        RIGHT_FIRST_COL, HEADER_ROWS,
    )
    table_header_row = 1 + HEADER_ROWS
    partial_times = {}
    for r in range(table_header_row + 1, partial_sheet.max_row + 1):
        date_cell = partial_sheet.cell(row=r, column=RIGHT_FIRST_COL).value
        pickup = partial_sheet.cell(row=r, column=RIGHT_FIRST_COL + 2).value
        if not isinstance(date_cell, date) or not pickup:
            continue
        partial_times[date_cell] = pickup

    # Re-run for the full month; days 1-19 should match.
    full_dir = tmp_path / "full"
    full_dir.mkdir()
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(full_dir),
         "--time-cache", str(cache_path)]
    )
    assert rc == 0
    full_wb = openpyxl.load_workbook(
        str(full_dir / "Schedule_24010_2026-05.xlsx")
    )
    full_sheet = full_wb.active

    matched = 0
    for r in range(table_header_row + 1, full_sheet.max_row + 1):
        date_cell = full_sheet.cell(row=r, column=RIGHT_FIRST_COL).value
        pickup = full_sheet.cell(row=r, column=RIGHT_FIRST_COL + 2).value
        if not isinstance(date_cell, date):
            continue
        if date_cell in partial_times:
            assert pickup == partial_times[date_cell], (
                f"{date_cell}: full-run pickup {pickup} "
                f"differs from partial-run {partial_times[date_cell]}"
            )
            matched += 1
    assert matched == len(partial_times) > 0


def test_cli_range_feb_29_non_leap_year_returns_2(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "2",
         "--output-path", str(tmp_path),
         "--end-day", "29"]
    )
    assert rc == 2
    assert "exceeds last day" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --debug flag writes a per-member diagnostic CSV
# ---------------------------------------------------------------------------


def test_debug_flag_writes_combined_debug_csv(monkeypatch, tmp_path):
    """--debug produces ONE combined Debug_<YYYY-MM>.csv with rows for
    every scheduled member, not a separate file per member."""
    monkeypatch.setattr(
        cli, "get_members_by_plan",
        lambda code, db: [FAKE_MEMBER, FAKE_MEMBER_2],
    )
    rc = cli.main(
        ["--plan", "hof", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path), "--debug"]
    )
    assert rc == 0
    sub = tmp_path / "HOF_2026-05"
    debug_path = sub / "Debug_2026-05.csv"
    assert debug_path.exists()
    # No per-member Debug_<id>_*.csv files.
    assert not list(sub.glob("Debug_24010_*.csv"))
    assert not list(sub.glob("Debug_24011_*.csv"))
    lines = debug_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "center_id,name,date,day,scheduled,reason"
    # auth_days "1.3.4.5" → Mon/Wed/Thu/Fri in May 2026 = 17 days × 2 members
    assert len(lines) - 1 == 34
    # Each row should be tagged with one of the two member IDs.
    ids = {line.split(",", 1)[0] for line in lines[1:]}
    assert ids == {"24010", "24011"}


def test_debug_flag_off_does_not_write_debug_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path)]
    )
    assert rc == 0
    assert not (tmp_path / "Debug_2026-05.csv").exists()


def test_debug_flag_with_preview_writes_no_files(monkeypatch, tmp_path):
    """--debug + --preview-data: still no files written (preview wins)."""
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(tmp_path), "--debug", "--preview-data"]
    )
    assert rc == 0
    assert not (tmp_path / "Debug_2026-05.csv").exists()
    assert not (tmp_path / "Schedule_24010_2026-05.xlsx").exists()


def test_write_skipped_members_csv_preserves_input_order(tmp_path):
    """Multiple failures appear in input order."""
    from pathlib import Path

    failures = [
        Failure(24010, "Cheng, Lizhu", "eligibility", "A", None),
        Failure(24011, "Smith, John", "lookup", "B", None),
        Failure(24012, "Jones, Mary", "geocode", "C", None),
    ]
    result = write_skipped_members_csv(
        failures, str(tmp_path), today=date(2026, 6, 4)
    )
    lines = Path(result).read_text(encoding="utf-8").splitlines()
    assert [row.split(",", 1)[0] for row in lines[1:]] == [
        "24010", "24011", "24012",
    ]
