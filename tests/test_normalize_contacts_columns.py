"""Unit tests for the pure decision logic in
scripts/normalize_contacts_columns.py (no COM / no database)."""
from scripts.normalize_contacts_columns import (
    CARE_MANAGER_COLUMNS,
    RENAME_MAP,
    REQUIRED_COLUMNS,
    missing_required,
    needs_alt_id,
    plan_renames,
)

# Column names as they come out of a fresh DBM.accdb export.
DBM_EXPORT_NAMES = [
    "Center_ID", "Last_Name", "First_Name", "Chinese_Name", "DOB",
    "Health_Plan", "Member_ID", "Medicaid", "Medicare", "SSN",
    "Language", "Case_Manager", "Home_Tel", "Cell", "Address",
    "Emergency", "PCP", "Hospital", "Admission", "SADC", "HHA",
    "Transportation", "Notes", "Photo", "Gender", "Authorization",
    "AuthBGN", "AuthEXP", "ICD10", "TransportationAuth", "MealAuth",
]

# The same table after every rename has been applied.
NORMALIZED_NAMES = [dict(RENAME_MAP).get(n, n) for n in DBM_EXPORT_NAMES]


def test_fresh_dbm_export_plans_all_ten_renames():
    renames, already_ok, missing = plan_renames(DBM_EXPORT_NAMES)
    assert renames == RENAME_MAP
    assert already_ok == []
    assert missing == []


def test_normalized_table_is_a_noop():
    renames, already_ok, missing = plan_renames(NORMALIZED_NAMES)
    assert renames == []
    assert already_ok == [new for _old, new in RENAME_MAP]
    assert missing == []


def test_half_renamed_table_plans_only_the_remainder():
    """A database where the first five renames were done by hand (the
    real 2026-08-11 situation) plans exactly the other five."""
    done = {"Center_ID": "Center ID", "Last_Name": "Last Name",
            "First_Name": "First Name", "Health_Plan": "Health Plan",
            "Admission": "Admission Date"}
    names = [done.get(n, n) for n in DBM_EXPORT_NAMES]
    renames, already_ok, missing = plan_renames(names)
    assert renames == [
        ("AuthBGN", "Auth BGN"),
        ("AuthEXP", "Auth EXP"),
        ("Member_ID", "Member ID"),
        ("Authorization", "SADC Auth"),
        ("TransportationAuth", "TRANS Auth"),
        ("Chinese_Name", "Chinese Name"),
        ("Case_Manager", "Case Manager"),
        ("Home_Tel", "Home Tell"),
    ]
    assert set(already_ok) == set(done.values())
    assert missing == []


def test_matching_is_case_insensitive():
    names = [n.upper() for n in NORMALIZED_NAMES]
    renames, already_ok, missing = plan_renames(names)
    assert renames == []
    assert missing == []


def test_column_absent_under_both_names_is_reported_missing():
    names = [n for n in DBM_EXPORT_NAMES if n != "AuthBGN"]
    renames, _already_ok, missing = plan_renames(names)
    assert ("AuthBGN", "Auth BGN") in missing
    assert ("AuthBGN", "Auth BGN") not in renames


def test_missing_required_flags_absent_columns():
    assert missing_required(NORMALIZED_NAMES) == []
    without_hha = [n for n in NORMALIZED_NAMES if n != "HHA"]
    assert missing_required(without_hha) == ["HHA"]


def test_every_rename_target_is_load_bearing():
    """Each rename target is queried by BSCA (REQUIRED_COLUMNS) or by
    Care Manager (CARE_MANAGER_COLUMNS) — keep the constants in sync
    so no rename exists without a consumer."""
    known = {c.lower() for c in REQUIRED_COLUMNS + CARE_MANAGER_COLUMNS}
    for _old, new in RENAME_MAP:
        assert new.lower() in known


def test_needs_alt_id():
    assert needs_alt_id(DBM_EXPORT_NAMES)          # fresh export lacks it
    assert not needs_alt_id(NORMALIZED_NAMES + ["alt_id"])
    assert not needs_alt_id(["ALT_ID"])            # case-insensitive
