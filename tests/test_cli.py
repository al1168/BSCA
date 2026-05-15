import new_monthly_schedule as cli

FAKE_MEMBER = {
    "center_id": 24010,
    "last_name": "Cheng",
    "first_name": "Lizhu",
    "health_plan": "HOF",
    "auth_days": "1.3.4.5",
}

FAKE_MEMBER_2 = {
    "center_id": 24011,
    "last_name": "Smith",
    "first_name": "John",
    "health_plan": "HOF",
    "auth_days": "1.3.4.5",
}


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


import pytest


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
        cli.Failure(24099, "", "lookup", "not found in database"),
        cli.Failure(24100, "Smith, John", "write",
                    "PermissionError — denied"),
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
