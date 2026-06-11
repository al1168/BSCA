"""Backfill the EmergencyContact table from Contacts.Emergency.

The Contacts.[Emergency] column is free-text with no standardized
format. This script applies best-effort heuristics to extract:

  - Full Name
  - Phone Number (canonicalized to "(NNN) NNN-NNNN")
  - Relationship to member (matched against a known vocab)

Common observed formats:
  "Son, Andy Lau, (917) 628-0459"      → name + relationship + phone
  "Son, (347) 398-8708"                → relationship + phone (no name)
  "Daughter: 917-530-5185"             → colon separator
  "Wang Mary, (917) 337-2918"          → name + phone (no relationship)
  "Wang, Zhi Ming, (917) 299-2254(son)" → relationship in trailing parens

Rows we can confidently parse → INSERT into EmergencyContact.
Rows that are ambiguous (no phone, multiple phones, multiple
relationship keywords, suspiciously long name) → logged to an
`emergency_contact_ambiguous_<DATE>.csv` for manual review.
Empty Emergency cells → silently skipped (no error).

Idempotent: re-running skips members that already have at least one
row in EmergencyContact.

Designed to be run from the CLI or chained from the Setup GUI.
"""
import argparse
import csv
import datetime
import os
import re
import sys
from pathlib import Path

# Make `from monthly_schedule import ...` work when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_CONTACTS_QUERY = (
    "SELECT [Center ID], [Emergency] "
    "FROM [Contacts] "
    "ORDER BY [Center ID]"
)

_EMERGENCY_COUNT_FOR_MEMBER = (
    "SELECT COUNT(*) FROM [EmergencyContact] WHERE [Center ID] = ?"
)

_EMERGENCY_INSERT = (
    "INSERT INTO [EmergencyContact] "
    "([Center ID], [Full Name], [Phone Number], [Relationship]) "
    "VALUES (?, ?, ?, ?)"
)

_CSV_COLUMNS = [
    "center_id",
    "raw_emergency",
    "parsed_name",
    "parsed_phone",
    "parsed_relationship",
    "reason",
]


# Phone matcher — covers (NNN) NNN-NNNN, NNN-NNN-NNNN, (NNN)NNN-NNNN,
# NNN NNN NNNN, NNNNNNNNNN. Captures area / prefix / line so we can
# canonicalize the output.
_PHONE_RE = re.compile(
    r"\(?\s*(\d{3})\s*\)?[\s\-\.]*(\d{3})[\s\-\.]*(\d{4})"
)


# Relationship vocabulary. Each key is a canonical label; the value is
# a tuple of regex word-boundary patterns matched case-insensitively.
# Order matters: longer multi-word terms first so they match before
# their substrings (e.g. "son-in-law" before "son").
_RELATIONSHIPS: list[tuple[str, list[str]]] = [
    ("Son-in-law",      [r"son[\s\-]?in[\s\-]?law"]),
    ("Daughter-in-law", [r"daughter[\s\-]?in[\s\-]?law"]),
    ("Sister-in-law",   [r"sister[\s\-]?in[\s\-]?law"]),
    ("Brother-in-law",  [r"brother[\s\-]?in[\s\-]?law"]),
    ("Mother-in-law",   [r"mother[\s\-]?in[\s\-]?law"]),
    ("Father-in-law",   [r"father[\s\-]?in[\s\-]?law"]),
    # Direct relations — include "daugther" typo seen in real data.
    ("Daughter",        [r"daughter", r"daugther"]),
    ("Son",             [r"son"]),
    ("Spouse",          [r"spouse"]),
    ("Wife",            [r"wife"]),
    ("Husband",         [r"husband"]),
    ("Mother",          [r"mother", r"mom"]),
    ("Father",          [r"father", r"dad"]),
    ("Sister",          [r"sister"]),
    ("Brother",         [r"brother"]),
    ("Niece",           [r"niece"]),
    ("Nephew",          [r"nephew"]),
    ("Cousin",          [r"cousin"]),
    ("Aunt",            [r"aunt"]),
    ("Uncle",           [r"uncle"]),
    ("Friend",          [r"friend"]),
    ("Neighbor",        [r"neighbor"]),
    ("Caregiver",       [r"care[\s\-]?giver"]),
]


# Max acceptable length of the parsed name before flagging as suspicious.
_NAME_MAX_LEN = 100


def _build_connection_string(db_path):
    return (
        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};"
    )


def _extract_phones(text: str) -> tuple[list[str], str]:
    """Return (canonical_phones, text_with_phones_removed).

    Canonical form is "(NNN) NNN-NNNN". Multiple matches preserve
    order. The remaining text has each matched phone replaced with a
    single space so downstream parsing doesn't trip on the digits."""
    phones = []
    spans = []
    for m in _PHONE_RE.finditer(text):
        area, prefix, line = m.group(1), m.group(2), m.group(3)
        phones.append(f"({area}) {prefix}-{line}")
        spans.append(m.span())
    # Rebuild text without phones, preserving the rest.
    if not spans:
        return [], text
    out = []
    cursor = 0
    for s, e in spans:
        out.append(text[cursor:s])
        out.append(" ")
        cursor = e
    out.append(text[cursor:])
    return phones, "".join(out)


def _extract_relationships(text: str) -> tuple[list[str], str]:
    """Return (canonical_relationships, text_with_relationships_removed).

    Matches the relationship vocab case-insensitively. A given canonical
    label is only counted once even if multiple synonyms match (so
    "mom" and "mother" together → one ["Mother"], not two)."""
    found = []
    for canonical, patterns in _RELATIONSHIPS:
        pattern = r"\b(?:" + "|".join(patterns) + r")\b"
        regex = re.compile(pattern, re.IGNORECASE)
        if regex.search(text):
            found.append(canonical)
            text = regex.sub(" ", text)
    return found, text


def _clean_name(text: str) -> str:
    """Strip leftover separators and whitespace from the parsed name."""
    # Remove leftover parens and surrounding separators.
    text = re.sub(r"[(),:;\-/|]+", " ", text)
    # Collapse internal whitespace, strip ends.
    return " ".join(text.split())


def _parse_emergency(raw: str) -> dict:
    """Parse one Emergency cell. Returns a dict with keys
    'name', 'phone', 'relationship', 'reason'. `reason` is empty
    on success or one of: 'no_phone', 'multiple_phones',
    'multiple_relationships', 'name_too_long'."""
    text = raw or ""
    phones, after_phone = _extract_phones(text)
    relationships, after_rel = _extract_relationships(after_phone)

    if not phones:
        return {
            "name": _clean_name(after_rel),
            "phone": "",
            "relationship": ", ".join(relationships),
            "reason": "no_phone",
        }
    if len(phones) > 1:
        return {
            "name": _clean_name(after_rel),
            "phone": "; ".join(phones),
            "relationship": ", ".join(relationships),
            "reason": "multiple_phones",
        }
    if len(relationships) > 1:
        return {
            "name": _clean_name(after_rel),
            "phone": phones[0],
            "relationship": ", ".join(relationships),
            "reason": "multiple_relationships",
        }

    name = _clean_name(after_rel)
    if len(name) > _NAME_MAX_LEN:
        return {
            "name": name,
            "phone": phones[0],
            "relationship": relationships[0] if relationships else "",
            "reason": "name_too_long",
        }
    return {
        "name": name,
        "phone": phones[0],
        "relationship": relationships[0] if relationships else "",
        "reason": "",
    }


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Backfill EmergencyContact from Contacts.Emergency."
    )
    p.add_argument("--db", required=True,
                   help="Path to the Access .accdb file.")
    p.add_argument("--csv-out", default=".",
                   help="Directory for the ambiguous CSV. Default: cwd.")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse + write CSV, do NOT commit DB changes.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-row stdout; print only the summary.")
    return p.parse_args(argv)


def _read_emergency_rows(conn):
    """Yield (cid, emergency_text) tuples. Skips rows whose Center ID
    is NULL or whose Emergency cell is None / empty / whitespace."""
    cur = conn.cursor()
    cur.execute(_CONTACTS_QUERY)
    for row in cur.fetchall():
        cid, emergency = row
        if cid is None:
            continue
        if emergency is None:
            continue
        text = str(emergency).strip()
        if not text:
            continue
        yield int(cid), text


def _write_ambiguous_csv(rows, out_dir, today):
    """Write the ambiguous-row CSV to
    `<out_dir>/emergency_contact_ambiguous_<YYYY-MM-DD>.csv`. Returns
    the path. The header is written even if `rows` is empty so the
    file's presence signals 'a backfill ran on this date'."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir,
        f"emergency_contact_ambiguous_{today.isoformat()}.csv",
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def main(argv=None):
    args = _parse_args(argv)
    if not os.path.exists(args.db):
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)
        return 2
    import pyodbc
    try:
        conn = pyodbc.connect(_build_connection_string(args.db))
    except pyodbc.Error as exc:
        print(
            "ERROR: could not open the Access database. Verify the "
            "Microsoft Access ODBC driver is installed and its "
            "bitness matches this Python interpreter. "
            f"Original error: {exc}",
            file=sys.stderr,
        )
        return 2
    try:
        cur = conn.cursor()
        today = datetime.date.today()
        stats = {
            "scanned": 0,
            "empty_skipped": 0,
            "already_present_skipped": 0,
            "inserted": 0,
            "ambiguous": 0,
        }
        ambiguous_rows = []

        # Pre-count: total Contacts row count, including those we
        # silently skip for empty Emergency. Use a separate scan that
        # filters on Center ID NOT NULL only.
        cur.execute("SELECT COUNT(*) FROM [Contacts] WHERE [Center ID] IS NOT NULL")
        contacts_total = cur.fetchone()[0]
        stats["scanned"] = contacts_total

        for cid, raw in _read_emergency_rows(conn):
            # Idempotency: skip if already populated.
            cur.execute(_EMERGENCY_COUNT_FOR_MEMBER, str(cid))
            count = cur.fetchone()[0]
            if count > 0:
                stats["already_present_skipped"] += 1
                continue

            parsed = _parse_emergency(raw)
            if parsed["reason"]:
                stats["ambiguous"] += 1
                ambiguous_rows.append({
                    "center_id": cid,
                    "raw_emergency": raw,
                    "parsed_name": parsed["name"],
                    "parsed_phone": parsed["phone"],
                    "parsed_relationship": parsed["relationship"],
                    "reason": parsed["reason"],
                })
                if not args.quiet:
                    print(f"  AMBIGUOUS {cid}  ({parsed['reason']})  "
                          f"raw={raw!r}")
                continue

            cur.execute(
                _EMERGENCY_INSERT,
                str(cid),
                parsed["name"],
                parsed["phone"],
                parsed["relationship"],
            )
            stats["inserted"] += 1
            if not args.quiet:
                rel = parsed["relationship"] or "(no relationship)"
                name = parsed["name"] or "(no name)"
                print(f"  INSERTED  {cid}  name={name!r}  "
                      f"phone={parsed['phone']}  rel={rel}")

        # Empty/None Emergency cells: everything we did NOT yield from
        # _read_emergency_rows minus the already-present and ambiguous.
        # Computed as: contacts_total - (rows we touched).
        touched = (
            stats["already_present_skipped"]
            + stats["inserted"]
            + stats["ambiguous"]
        )
        stats["empty_skipped"] = max(0, contacts_total - touched)

        if args.dry_run:
            conn.rollback()
            mode = "DRY-RUN (no changes committed)"
        else:
            conn.commit()
            mode = "APPLIED"

        csv_path = _write_ambiguous_csv(ambiguous_rows, args.csv_out, today)

        print()
        print("Emergency contact backfill summary")
        print(f"  Contacts scanned:                       "
              f"{stats['scanned']}")
        print(f"  Empty emergency (skipped silently):     "
              f"{stats['empty_skipped']}")
        print(f"  Already in EmergencyContact (skipped):  "
              f"{stats['already_present_skipped']}")
        print(f"  Successfully parsed and inserted:       "
              f"{stats['inserted']}")
        print(f"  Ambiguous (logged to CSV):              "
              f"{stats['ambiguous']}")
        print(f"  Ambiguous CSV: {csv_path}")
        print(f"  Mode: {mode}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
