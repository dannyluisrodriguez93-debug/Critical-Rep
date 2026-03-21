#!/usr/bin/env python3
"""
Import Q1 2026 sales data from Excel into AccountHub database.

Reads the "Clean Master" sheet, upserts products, maps hospitals to accounts
(fuzzy + manual fallback), inserts sales rows, and logs the import.
"""

import sys
from pathlib import Path
from datetime import datetime

# Add project root to path so we can import database module
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import openpyxl
from rapidfuzz import process, fuzz

import database

# ── Configuration ────────────────────────────────────────────────────────────

EXCEL_PATH = Path.home() / "Desktop" / "Q1_2026_Sales_Data.xlsx"
SHEET_NAME = "Clean Master"

# Manual hospital → account_id mapping for names that don't match exactly
MANUAL_MAP = {
    "Baptist Hospital":            4,   # Baptist Hospital of Miami
    "Memorial Healthcare System":  1,   # Memorial
}

# Hospitals to skip entirely (no matching account)
SKIP_HOSPITALS = {"Comprehensive Care Services"}

# Fuzzy matching threshold (0-100)
FUZZY_THRESHOLD = 80


def parse_date(date_str: str) -> str:
    """Convert 'M/D/YYYY' to 'YYYY-MM-DD' ISO format."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%m/%d/%Y")
    except ValueError:
        # Try single-digit month/day
        dt = datetime.strptime(date_str.strip(), "%m/%d/%Y")
    return dt.strftime("%Y-%m-%d")


def build_account_lookup() -> tuple[dict, list[tuple[str, int]]]:
    """Build exact-match dict and name list for fuzzy matching from DB accounts."""
    all_names = database.get_all_account_names_and_aliases()
    exact = {name.lower(): acct_id for name, acct_id in all_names}
    return exact, all_names


def match_hospital(name: str, exact_map: dict, fuzzy_choices: list[tuple[str, int]]) -> int | None:
    """Return account_id for a hospital name, or None if unmatched."""
    if not name:
        return None

    # Skip list
    if name in SKIP_HOSPITALS:
        return None

    # Manual override
    if name in MANUAL_MAP:
        return MANUAL_MAP[name]

    # Exact match (case-insensitive)
    if name.lower() in exact_map:
        return exact_map[name.lower()]

    # Fuzzy match against all account names + aliases
    choices = [n for n, _ in fuzzy_choices]
    result = process.extractOne(name, choices, scorer=fuzz.token_sort_ratio)
    if result and result[1] >= FUZZY_THRESHOLD:
        matched_name = result[0]
        # Find the account_id for this matched name
        for n, aid in fuzzy_choices:
            if n == matched_name:
                return aid

    return None


def main():
    print(f"Loading Excel: {EXCEL_PATH}")
    wb = openpyxl.load_workbook(str(EXCEL_PATH), data_only=True)
    ws = wb[SHEET_NAME]

    # Build account lookup
    exact_map, fuzzy_choices = build_account_lookup()

    # Column indices (1-based)
    COL = {
        "num": 1, "email_date": 2, "data_date": 3, "hospital": 4,
        "prod_line": 5, "item_number": 6, "description": 7,
        "units": 8, "revenue": 9, "tracking": 10, "source": 11, "notes": 12,
    }

    # ── Pass 1: Collect rows, skip totals ────────────────────────────────────
    rows = []
    for r in range(2, ws.max_row + 1):
        row_num = ws.cell(r, COL["num"]).value
        if row_num is None:
            # Totals row or blank — skip
            continue
        rows.append({
            "row_num":     row_num,
            "email_date":  ws.cell(r, COL["email_date"]).value,
            "data_date":   ws.cell(r, COL["data_date"]).value,
            "hospital":    ws.cell(r, COL["hospital"]).value,
            "prod_line":   ws.cell(r, COL["prod_line"]).value,
            "item_number": str(ws.cell(r, COL["item_number"]).value or "").strip(),
            "description": str(ws.cell(r, COL["description"]).value or "").strip(),
            "units":       ws.cell(r, COL["units"]).value or 0,
            "revenue":     ws.cell(r, COL["revenue"]).value or 0.0,
            "tracking":    str(ws.cell(r, COL["tracking"]).value or "").strip(),
            "source":      ws.cell(r, COL["source"]).value,
            "notes":       ws.cell(r, COL["notes"]).value,
        })

    print(f"Found {len(rows)} data rows (excluding totals)")

    # ── Pass 2: Upsert products ──────────────────────────────────────────────
    product_cache = {}  # item_number → product_id
    unique_items = {(r["item_number"], r["description"], r["prod_line"]) for r in rows}
    for item_num, desc, prod_line in unique_items:
        if not item_num:
            continue
        pid = database.upsert_product(
            item_number=item_num,
            description=desc,
            prod_line=prod_line,
        )
        product_cache[item_num] = pid
    print(f"Upserted {len(product_cache)} unique products")

    # ── Pass 3: Map hospitals and insert sales ───────────────────────────────
    inserted = 0
    skipped_dup = 0
    skipped_no_account = 0
    unmatched_hospitals = set()
    alias_additions = {}  # hospital_name → account_id (for aliases to add)

    for r in rows:
        hospital = r["hospital"]
        account_id = match_hospital(hospital, exact_map, fuzzy_choices)

        if account_id is None:
            if hospital and hospital not in SKIP_HOSPITALS:
                unmatched_hospitals.add(hospital)
            skipped_no_account += 1
            continue

        # Track alias additions for non-exact matches
        if hospital and hospital.lower() not in exact_map:
            alias_additions[hospital] = account_id

        product_id = product_cache.get(r["item_number"])
        if not product_id:
            print(f"  WARNING: No product for item {r['item_number']}, skipping row {r['row_num']}")
            continue

        report_date = parse_date(r["data_date"])
        if not report_date:
            print(f"  WARNING: No data date for row {r['row_num']}, skipping")
            continue

        ok = database.insert_sale(
            account_id=account_id,
            product_id=product_id,
            prod_line=r["prod_line"],
            units=int(r["units"]) if r["units"] else 0,
            revenue=float(r["revenue"]) if r["revenue"] else 0.0,
            report_date=report_date,
            tracking=r["tracking"] or None,
        )

        if ok:
            inserted += 1
        else:
            skipped_dup += 1

    # ── Pass 4: Add aliases for fuzzy-matched names ──────────────────────────
    for alias_name, acct_id in alias_additions.items():
        database.add_alias_to_account(acct_id, alias_name)
        print(f"  Added alias: '{alias_name}' -> account {acct_id}")

    # ── Pass 5: Flag unmatched hospitals ─────────────────────────────────────
    for name in unmatched_hospitals:
        database.flag_unmatched(name)
        print(f"  Flagged unmatched: '{name}'")

    # ── Pass 6: Log the import in email_log ──────────────────────────────────
    now_iso = datetime.now().isoformat()
    database.log_email(
        subject="Q1 2026 Excel Import",
        sender="manual-import",
        received_at=now_iso,
        message_id=f"manual-import-q1-2026-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        rows_inserted=inserted,
        status="ok",
    )

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("IMPORT SUMMARY")
    print("=" * 60)
    print(f"  Total data rows:      {len(rows)}")
    print(f"  Sales inserted:       {inserted}")
    print(f"  Duplicates skipped:   {skipped_dup}")
    print(f"  No account (skipped): {skipped_no_account}")
    print(f"  Products upserted:    {len(product_cache)}")
    print(f"  Aliases added:        {len(alias_additions)}")
    if unmatched_hospitals:
        print(f"  Unmatched hospitals:  {', '.join(sorted(unmatched_hospitals))}")
    if SKIP_HOSPITALS:
        print(f"  Skipped hospitals:    {', '.join(sorted(SKIP_HOSPITALS))}")
    print("=" * 60)


if __name__ == "__main__":
    main()
