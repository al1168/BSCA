import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


def test_package_imports():
    import monthly_schedule  # noqa: F401


def _odbc_available() -> bool:
    try:
        import pyodbc
    except ImportError:
        return False
    return any(
        "Microsoft Access Driver" in name for name in pyodbc.drivers()
    )


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(
    not _odbc_available(),
    reason="Microsoft Access ODBC driver not available in this environment",
)
def test_one_off_conflict_writes_skipped_csv(tmp_path):
    """End-to-end: seed the one_off_conflict scenario, run the CLI,
    confirm `skipped_members_<DATE>.csv` lands in the output dir
    with the conflict row recorded."""
    test_db = tmp_path / "test.accdb"
    # The repository's reference template — adjust if your local
    # workflow uses a different source.
    src = Path(os.environ.get(
        "BSCA_TEST_DB_SRC",
        REPO_ROOT / "scripts" / "test_dbs" / "populate_real_members.accdb",
    ))
    if not src.exists():
        pytest.skip(f"Source DB template not found: {src}")
    shutil.copy(src, test_db)

    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "create_supporting_tables.py"),
         "--db", str(test_db), "--quiet"],
        check=False,  # may report "already exists" — that's fine
    )

    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "make_test_db.py"),
         "--scenario", "one_off_conflict", "--output", str(test_db)],
        check=True,
    )

    # Cache schema is defined by monthly_schedule/travel.py. The "route"
    # key uses 5-decimal rounding via resolve_travel_minutes; the "ts" entry
    # must be unexpired so _purge_expired (called in load_cache) does not
    # evict the pre-seeded entry before the route lookup occurs.
    # Pre-seed the geo cache so the CLI never calls the Google APIs.
    # The test member is seeded with Long Lat "-74.00600,40.71280"
    # (column-name order: long,lat); parser returns (lat, lng) so the
    # route cache key is round(lat,5),round(lng,5) = "40.7128,-74.006".
    geo_cache_path = tmp_path / "geo_cache.json"
    _far_future = time.time() + 7 * 24 * 3600  # within the 1-week TTL
    geo_cache_path.write_text(
        json.dumps({
            "route": {"40.7128,-74.006": 15},
            "ts": {"route:40.7128,-74.006": _far_future},
        }),
        encoding="utf-8",
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "new_monthly_schedule.py"),
         "--center-id", "100100",
         "--year", "2026", "--month", "6",
         "--db-path", str(test_db),
         "--output-path", str(out_dir),
         "--api-key", "TEST_KEY_NOT_USED",
         "--geo-cache", str(tmp_path / "geo_cache.json"),
        ],
        capture_output=True, text=True,
    )

    # The CLI returns 2 when there are any failures — the conflict counts.
    assert result.returncode == 2, result.stderr

    csv_files = list(out_dir.glob("skipped_members_*.csv"))
    assert len(csv_files) == 1, (
        f"Expected exactly one skipped-members CSV, got: {csv_files}\n"
        f"stderr: {result.stderr}"
    )
    body = csv_files[0].read_text(encoding="utf-8")
    assert "100100" in body
    assert "conflicts with absence" in body
