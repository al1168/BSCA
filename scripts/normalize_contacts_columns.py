"""Rename legacy DBM-style Contacts columns to the names BSCA expects.

Databases exported from DBM.accdb name their Contacts columns with
underscores (`Center_ID`, `Admission`, `AuthBGN`, …) while every BSCA
query uses the spaced legacy names (`[Center ID]`, `[Admission Date]`,
`[Auth BGN]`, …). Running the setup chain against an un-renamed export
fails with ODBC "Too few parameters" errors, because Access reports
unknown column names as query parameters.

The map also covers columns only the Care Manager app reads
(`[Chinese Name]`, `[Case Manager]`, `[Home Tell]` — the double-L is
the app's and the historical databases' spelling), and the step adds
the `[alt_id]` column Care Manager requires when it's absent, so one
normalized database serves both tools.

This step renames the known legacy columns in place and then verifies
that every Contacts column the rest of the chain (and the scheduler)
relies on actually exists, so a schema surprise stops the chain here
with a readable message instead of a cryptic ODBC error five steps
later.

Why DAO instead of ODBC: Access SQL has no RENAME COLUMN. A DAO
TableDef field rename (`Fields(old).Name = new`) preserves the
column's data, type, and indexes.

Idempotent: columns already carrying the BSCA name are skipped. Safe
to run repeatedly, including on half-renamed databases.
"""
import argparse
import os
import sys


# (legacy DBM name, BSCA name). Order matters only for readability.
RENAME_MAP = [
    ("Center_ID", "Center ID"),
    ("Last_Name", "Last Name"),
    ("First_Name", "First Name"),
    ("Health_Plan", "Health Plan"),
    ("Admission", "Admission Date"),
    ("AuthBGN", "Auth BGN"),
    ("AuthEXP", "Auth EXP"),
    ("Member_ID", "Member ID"),
    ("Authorization", "SADC Auth"),
    ("TransportationAuth", "TRANS Auth"),
    ("Chinese_Name", "Chinese Name"),
    ("Case_Manager", "Case Manager"),
    ("Home_Tel", "Home Tell"),
]

# Every Contacts column some part of BSCA reads. Verified after the
# renames; a miss is a hard error (rc 2) that stops the setup chain.
REQUIRED_COLUMNS = [
    "Center ID", "Last Name", "First Name", "Health Plan",
    "Admission Date", "SADC", "HHA", "Emergency",
    "Auth BGN", "Auth EXP", "Member ID", "SADC Auth", "TRANS Auth",
    "Gender", "DOB", "Medicaid", "Address",
]

# Rename targets only the Care Manager app queries — normalized here
# too so one database serves both tools, but not REQUIRED for the
# BSCA chain itself.
CARE_MANAGER_COLUMNS = ["Chinese Name", "Case Manager", "Home Tell",
                        "alt_id"]

DAO_LONG = 4  # DAO DataTypeEnum.dbLong — for the added [alt_id]


def plan_renames(existing_names):
    """Decide what to do for each RENAME_MAP pair given the Contacts
    column names that exist right now.

    Returns (renames, already_ok, missing):
      renames    — [(old, new)] pairs to apply (old exists, new doesn't)
      already_ok — [new] names already present (nothing to do)
      missing    — [(old, new)] pairs where NEITHER name exists

    Comparison is case-insensitive, matching Access's treatment of
    identifiers; the returned names keep RENAME_MAP's casing."""
    lower = {n.lower() for n in existing_names}
    renames, already_ok, missing = [], [], []
    for old, new in RENAME_MAP:
        if new.lower() in lower:
            already_ok.append(new)
        elif old.lower() in lower:
            renames.append((old, new))
        else:
            missing.append((old, new))
    return renames, already_ok, missing


def missing_required(existing_names):
    """REQUIRED_COLUMNS entries absent from `existing_names`
    (case-insensitive)."""
    lower = {n.lower() for n in existing_names}
    return [c for c in REQUIRED_COLUMNS if c.lower() not in lower]


def needs_alt_id(existing_names):
    """True when Contacts lacks the [alt_id] column Care Manager's
    member list query selects (case-insensitive)."""
    return "alt_id" not in {n.lower() for n in existing_names}


def _dao_engine():
    """DAO engine authenticating through Access's workgroup file.

    Some source databases carry legacy workgroup ACEs that deny reads
    to a bare DAO session ("no read permission"); pointing DAO at
    Access's own System.mdw makes them readable and changes nothing
    for unsecured databases. Raises RuntimeError with a friendly
    message if pywin32 or the DAO engine isn't available."""
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError(
            "pywin32 is not installed. Install it with "
            "`pip install pywin32` or rebuild this exe with pywin32 "
            f"bundled. Original error: {exc}"
        )
    try:
        engine = win32com.client.Dispatch("DAO.DBEngine.120")
    except Exception as exc:
        raise RuntimeError(
            "Could not create DAO.DBEngine.120. The Microsoft Access "
            "Database Engine must be installed (it comes with Access). "
            f"Original error: {exc}"
        )
    mdw = os.path.join(os.environ.get("APPDATA", ""),
                       "Microsoft", "Access", "System.mdw")
    try:
        if os.path.isfile(mdw):
            engine.SystemDB = mdw
    except Exception:
        pass
    return engine


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Rename legacy DBM-style Contacts columns (Center_ID, "
            "Admission, AuthBGN, …) to the names the BSCA scripts "
            "expect (Center ID, Admission Date, Auth BGN, …)."
        ),
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-column stdout; print only the summary.")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if not os.path.exists(args.db):
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)
        return 2

    import pythoncom
    pythoncom.CoInitialize()
    try:
        try:
            engine = _dao_engine()
            db = engine.OpenDatabase(args.db)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"ERROR: could not open the database: {exc}",
                  file=sys.stderr)
            return 2

        try:
            try:
                table_def = db.TableDefs("Contacts")
            except Exception:
                print("ERROR: this database has no [Contacts] table.",
                      file=sys.stderr)
                return 2
            existing = [str(f.Name) for f in table_def.Fields]

            renames, already_ok, missing = plan_renames(existing)
            try:
                for old, new in renames:
                    table_def.Fields(old).Name = new
                    if not args.quiet:
                        print(f"  RENAMED  Contacts.[{old}] -> [{new}]")

                added_alt_id = False
                if needs_alt_id(existing):
                    field = table_def.CreateField("alt_id", DAO_LONG)
                    field.Required = False
                    table_def.Fields.Append(field)
                    added_alt_id = True
                    if not args.quiet:
                        print("  ADDED    Contacts.[alt_id]  LONG")
            except Exception as exc:
                # Most common cause: the database is open in Access or
                # another tool, which blocks schema changes.
                detail = getattr(exc, "excepinfo", None)
                msg = (detail[2] if detail and detail[2] else str(exc))
                print(
                    "ERROR: could not change the Contacts columns: "
                    f"{msg} Close the database in Access / other tools "
                    "and run setup again.",
                    file=sys.stderr,
                )
                return 2
            db.TableDefs.Refresh()

            table_def = db.TableDefs("Contacts")
            final_names = [str(f.Name) for f in table_def.Fields]
            absent = missing_required(final_names)
            if absent:
                print(
                    "ERROR: Contacts is missing column(s) the BSCA "
                    "setup needs: " + ", ".join(f"[{c}]" for c in absent),
                    file=sys.stderr,
                )
                return 2

            print(
                f"Renamed {len(renames)} column(s); "
                f"{len(already_ok)} already had normalized names; "
                + ("added [alt_id]; " if added_alt_id else "")
                + "all required columns present."
            )
        finally:
            db.Close()
    finally:
        pythoncom.CoUninitialize()
    return 0


if __name__ == "__main__":
    sys.exit(main())
