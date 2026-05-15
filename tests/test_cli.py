import new_monthly_schedule as cli

FAKE_MEMBER = {
    "center_id": 24010,
    "last_name": "Cheng",
    "first_name": "Lizhu",
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


def test_no_member_returns_2(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: None)
    rc = cli.main(
        ["--center-id", "999", "--year", "2026", "--month", "5",
         "--preview-data"]
    )
    assert rc == 2
    assert "No member found" in capsys.readouterr().err


def test_writes_workbook(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_member", lambda cid, db: FAKE_MEMBER)
    out = tmp_path / "out.xlsx"
    rc = cli.main(
        ["--center-id", "24010", "--year", "2026", "--month", "5",
         "--output-path", str(out)]
    )
    assert rc == 0
    assert out.exists()


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
