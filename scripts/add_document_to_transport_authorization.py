"""Add the [Document] field to the existing TransportAuthorization
table as a native Access ATTACHMENT field (paperclip icon in Access UI).

Mirrors scripts/add_document_to_authorization.py — see that script for
the full rationale. In short: the ATTACHMENT data type is a DAO-only
feature (ODBC / ACE OLEDB reject `ALTER TABLE … ADD COLUMN [Document]
ATTACHMENT`), so we use the DAO.DBEngine.120 COM component and
TableDef.CreateField(name, dbAttachment) → Fields.Append.

Idempotent: if `[Document]` already exists on TransportAuthorization,
the script prints "already exists" and exits 0. Safe to run repeatedly.

Requires: `pywin32` (for `win32com.client.Dispatch`) and the Microsoft
Access Database Engine on the host.
"""
import argparse
import os
import sys


# DAO Field Type constant for the ATTACHMENT type. From the Access
# DAO enum DataTypeEnum.dbAttachment.
DAO_ATTACHMENT = 101


def _open_database(db_path: str):
    """Open `db_path` via DAO.DBEngine.120 and return the Database
    COM object. Raises RuntimeError with a friendly message if
    pywin32 or the DAO engine isn't available."""
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
            "Database Engine must be installed (it comes with Access; "
            "the Microsoft Access Database Engine Redistributable can "
            f"install it standalone). Original error: {exc}"
        )
    return engine.OpenDatabase(db_path)


def _field_exists(table_def, field_name: str) -> bool:
    """Case-insensitive check for a field by name on a DAO TableDef."""
    target = field_name.lower()
    for fld in table_def.Fields:
        if fld.Name.lower() == target:
            return True
    return False


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Add the [Document] field to TransportAuthorization as a "
            "native Access ATTACHMENT (paperclip) field. Uses DAO via "
            "pywin32 because ODBC can't create ATTACHMENT fields."
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
    try:
        db = _open_database(args.db)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        table_def = db.TableDefs("TransportAuthorization")
        if _field_exists(table_def, "Document"):
            print(
                "[Document] already exists on TransportAuthorization; "
                "nothing to do."
            )
            return 0
        field = table_def.CreateField("Document", DAO_ATTACHMENT)
        table_def.Fields.Append(field)
        if not args.quiet:
            print("  ADDED    TransportAuthorization.[Document]  ATTACHMENT")
        print("Added: TransportAuthorization.[Document]")
    finally:
        db.Close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
