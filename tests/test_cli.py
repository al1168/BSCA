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
    """Neutralize travel + new DB lookups for legacy tests."""
    monkeypatch.setattr(cli, "load_api_key", lambda path: "K")
    monkeypatch.setattr(cli, "load_cache", lambda path: {})
    monkeypatch.setattr(cli, "save_cache", lambda path, cache: None)
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


def test_missing_api_key_config_aborts(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)

    def no_key(path):
        raise RuntimeError(
            "Google API key config not found: google_maps.config"
        )
    monkeypatch.setattr(cli, "load_api_key", no_key)
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--preview-data"]
    )
    assert rc == 1
    assert "Google API key config not found" in capsys.readouterr().err


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
# write_one_off_conflict_csv
# ---------------------------------------------------------------------------

from new_monthly_schedule import write_one_off_conflict_csv, Failure


def test_write_one_off_conflict_csv_no_conflicts_returns_none(tmp_path):
    """Returns None and writes no file when no conflict failures are present."""
    failures = [
        cli.Failure(24010, "Cheng, Lizhu", "lookup", "not found", None),
    ]
    result = write_one_off_conflict_csv(
        failures, str(tmp_path), today=date(2026, 6, 4)
    )
    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_write_one_off_conflict_csv_single_conflict(tmp_path):
    """Writes a single-row CSV with correct filename, header, and row."""
    failures = [
        Failure(24010, "Cheng, Lizhu", "one_off_conflict",
                "one-off on auth day", date(2026, 6, 4)),
    ]
    result = write_one_off_conflict_csv(
        failures, str(tmp_path), today=date(2026, 6, 4)
    )
    expected_path = tmp_path / "one_off_conflicts_2026-06-04.csv"
    assert result == str(expected_path)
    assert expected_path.exists()
    content = expected_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[0] == "center_id,name,date,reason"
    assert lines[1] == '24010,"Cheng, Lizhu",2026-06-04,one-off on auth day'
    assert len(lines) == 2


def test_write_one_off_conflict_csv_multiple_conflicts_preserves_order(tmp_path):
    """Writes one row per conflict in input order."""
    failures = [
        Failure(24010, "Cheng, Lizhu", "one_off_conflict",
                "conflict A", date(2026, 6, 1)),
        Failure(24011, "Smith, John", "one_off_conflict",
                "conflict B", date(2026, 6, 3)),
        Failure(24012, "Jones, Mary", "one_off_conflict",
                "conflict C", date(2026, 6, 5)),
    ]
    result = write_one_off_conflict_csv(
        failures, str(tmp_path), today=date(2026, 6, 4)
    )
    expected_path = tmp_path / "one_off_conflicts_2026-06-04.csv"
    assert result == str(expected_path)
    content = expected_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[0] == "center_id,name,date,reason"
    assert lines[1] == '24010,"Cheng, Lizhu",2026-06-01,conflict A'
    assert lines[2] == '24011,"Smith, John",2026-06-03,conflict B'
    assert lines[3] == '24012,"Jones, Mary",2026-06-05,conflict C'
    assert len(lines) == 4
