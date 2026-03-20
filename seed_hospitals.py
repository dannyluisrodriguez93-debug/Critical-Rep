#!/usr/bin/env python3
"""
Bulk hospital seed script — imports all territory hospitals into account_hub.db.

Usage:
    python3 seed_hospitals.py

Safe to re-run: uses upsert semantics, so existing records are updated not duplicated.
"""

import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

import database as db


def seed():
    db.init_db()

    # ── Hospital Systems ───────────────────────────────────────────────────────
    systems = {
        "Jackson Health System":          db.upsert_system("Jackson Health System"),
        "Baptist Health South Florida":   db.upsert_system("Baptist Health South Florida"),
        "Memorial Healthcare System":     db.upsert_system("Memorial Healthcare System"),
        "Broward Health":                 db.upsert_system("Broward Health"),
        "Holy Cross Health":              db.upsert_system("Holy Cross Health"),
        "Cleveland Clinic":               db.upsert_system("Cleveland Clinic"),
        "HCA Healthcare":                 db.upsert_system("HCA Healthcare"),
        "Tenet Healthcare":               db.upsert_system("Tenet Healthcare"),
        "Independent":                    db.upsert_system("Independent"),
    }

    # ── Hospital definitions ───────────────────────────────────────────────────
    # Each entry:  (name, system_key, address, city, state, territory, teg_list)
    # teg_list: list of (location, department, model, [cartridge_types])
    hospitals = [
        # ── Jackson Health System ──────────────────────────────────────────────
        (
            "Jackson Memorial Hospital",
            "Jackson Health System",
            "1611 NW 12th Ave", "Miami", "FL", "South FL",
            [
                ("Lab",            "Lab",      "TEG 5000", ["Kaolin", "Rapid TEG"]),
                ("Lab",            "Lab",      "TEG 5000", ["Kaolin", "Rapid TEG"]),
                ("OR Room 33",     "OR",       "TEG 5000", ["Kaolin", "Rapid TEG"]),
                ("OR Room 33",     "OR",       "TEG 5000", ["Kaolin", "Rapid TEG"]),
                ("OR Room 33",     "OR",       "TEG 5000", ["Kaolin", "Rapid TEG"]),
                ("OR Room 33",     "OR",       "TEG 5000", ["Kaolin", "Rapid TEG"]),
                ("Resus",          "ED",       "TEG 6s",   ["Kaolin", "Rapid TEG"]),
                ("Trauma OR",      "OR",       "TEG 6s",   ["Kaolin", "Rapid TEG"]),
            ],
        ),
        (
            "Jackson South Community Hospital",
            "Jackson Health System",
            "9333 SW 152 Street", "South Miami", "FL", "South FL",
            [
                ("Lab",    "Lab",    "TEG 5000", ["Rapid TEG", "Kaolin"]),
                ("Trauma", "Trauma", "TEG 5000", ["Rapid TEG", "Kaolin"]),
            ],
        ),
        # ── Baptist Health South Florida ───────────────────────────────────────
        (
            "Baptist Hospital of Miami",
            "Baptist Health South Florida",
            "8900 N Kendall Dr", "Kendall", "FL", "South FL",
            [
                ("Lab", "Lab", "TEG 5000", ["PLM", "Kaolin"]),
                ("Lab", "Lab", "TEG 5000", ["PLM", "Kaolin"]),
                ("Lab", "Lab", "TEG 5000", ["PLM", "Kaolin"]),
                ("Lab", "Lab", "TEG 5000", ["PLM", "Kaolin"]),
            ],
        ),
        (
            "South Miami Hospital",
            "Baptist Health South Florida",
            "6200 SW 73 Street", "South Miami", "FL", "South FL",
            [
                ("Lab",     "Lab", "TEG 5000", ["PLM", "Kaolin"]),
                ("CVOR",    "OR",  "TEG 5000", ["PLM"]),
            ],
        ),
        (
            "Boca Raton Regional Hospital",
            "Baptist Health South Florida",
            None, "Boca Raton", "FL", "South FL",
            [],  # TEG present; L&D TEG PO requested — no detailed breakdown yet
        ),
        (
            "Baptist Bethesda Hospital",
            "Baptist Health South Florida",
            None, "Boynton Beach", "FL", "South FL",
            [],  # Demo done; pending install
        ),
        # ── Memorial Healthcare System ─────────────────────────────────────────
        (
            "Memorial Regional Medical Center",
            "Memorial Healthcare System",
            None, "Hollywood", "FL", "South FL",
            [
                ("Main Lab",  "Lab",  "TEG 5000", ["Kaolin", "Kaolin+Heparinase", "Rapid TEG"]),
                ("Main Lab",  "Lab",  "TEG 5000", ["Kaolin", "Kaolin+Heparinase", "Rapid TEG"]),
                ("Main Lab",  "Lab",  "TEG 5000", ["Kaolin", "Kaolin+Heparinase", "Rapid TEG"]),
                ("Main Lab",  "Lab",  "TEG 5000", ["Kaolin", "Kaolin+Heparinase", "Rapid TEG"]),
                ("Main Lab",  "Lab",  "TEG 5000", ["Kaolin", "Kaolin+Heparinase", "Rapid TEG"]),
                ("Main Lab",  "Lab",  "TEG 5000", ["Kaolin", "Kaolin+Heparinase", "Rapid TEG"]),
                ("CVOR",      "OR",   "TEG 5000", ["Kaolin", "Rapid TEG"]),
                ("CVOR",      "OR",   "TEG 5000", ["Kaolin", "Rapid TEG"]),
                ("CVOR",      "OR",   "TEG 5000", ["Kaolin", "Rapid TEG"]),
                ("Lab 6s #1", "Lab",  "TEG 6s",   ["PLM"]),
                ("Lab 6s #2", "Lab",  "TEG 6s",   ["PLM"]),
                ("Lab 6s #3", "Lab",  "TEG 6s",   ["PLM"]),
            ],
        ),
        # ── Broward Health ─────────────────────────────────────────────────────
        (
            "Broward General Hospital",
            "Broward Health",
            "1600 S Andrews Ave", "Fort Lauderdale", "FL", "South FL",
            [
                ("CVOR",        "OR",   "TEG 5000", ["Kaolin"]),
                ("Blood Bank",  "Lab",  "TEG 5000", ["Kaolin"]),
            ],
        ),
        (
            "Broward Health North",
            "Broward Health",
            "201 E Sample Road", "Deerfield Beach", "FL", "South FL",
            [
                ("Lab", "Lab", "TEG 6s", ["Kaolin+Heparinase"]),
            ],
        ),
        # ── Holy Cross Health ──────────────────────────────────────────────────
        (
            "Holy Cross Hospital",
            "Holy Cross Health",
            "4725 N Federal Hwy", "Fort Lauderdale", "FL", "South FL",
            [
                ("Lab", "Lab", "TEG 6s", ["Global Hemostasis", "ADP"]),
                ("Lab", "Lab", "TEG 6s", ["Global Hemostasis", "ADP"]),
                ("Lab", "Lab", "TEG 6s", ["Global Hemostasis", "ADP"]),
            ],
        ),
        # ── Cleveland Clinic ───────────────────────────────────────────────────
        (
            "Cleveland Clinic Florida",
            "Cleveland Clinic",
            "2950 Cleveland Clinic Blvd", "Weston", "FL", "South FL",
            [
                ("Lab",     "Lab", "TEG 5000", ["Kaolin", "Kaolin+Heparinase"]),
                ("Lab",     "Lab", "TEG 5000", ["Kaolin", "Kaolin+Heparinase"]),
                ("OR POC",  "OR",  "TEG 5000", ["Kaolin", "Kaolin+Heparinase"]),
                ("OR POC",  "OR",  "TEG 5000", ["Kaolin", "Kaolin+Heparinase"]),
                ("Lab 6s",  "Lab", "TEG 6s",   ["Kaolin+Heparinase"]),
                ("Lab 6s",  "Lab", "TEG 6s",   ["Kaolin+Heparinase"]),
                ("Lab 6s",  "Lab", "TEG 6s",   ["Kaolin+Heparinase"]),
                ("Lab 6s",  "Lab", "TEG 6s",   ["Kaolin+Heparinase"]),
            ],
        ),
        # ── HCA Healthcare ─────────────────────────────────────────────────────
        (
            "Northwest Medical Center",
            "HCA Healthcare",
            None, "Margate", "FL", "South FL",
            [
                ("Pump Room", "OR", "TEG 5000", ["Kaolin", "Kaolin+Citrated", "PLM"]),
            ],
        ),
        (
            "Westside Regional Medical Center",
            "HCA Healthcare",
            None, "Plantation", "FL", "South FL",
            [
                ("Pump Room", "OR", "TEG 5000", ["Kaolin", "Kaolin+Citrated", "PLM"]),
            ],
        ),
        (
            "JFK Medical Center",
            "HCA Healthcare",
            "5301 S Congress Ave", "Atlantis", "FL", "South FL",
            [
                ("Lab",    "Lab", "TEG 5000", ["Kaolin", "PLM"]),
                ("Lab",    "Lab", "TEG 5000", ["Kaolin", "PLM"]),
                ("Lab 6s", "Lab", "TEG 6s",   ["Kaolin", "PLM"]),
                ("Lab 6s", "Lab", "TEG 6s",   ["Kaolin", "PLM"]),
            ],
        ),
        (
            "Lawnwood Regional Medical Center",
            "HCA Healthcare",
            None, "Fort Pierce", "FL", "South FL",
            [],  # Existing TEGs; ongoing support
        ),
        # ── Tenet Healthcare ───────────────────────────────────────────────────
        (
            "Delray Medical Center",
            "Tenet Healthcare",
            "5352 Linton Blvd", "Delray Beach", "FL", "South FL",
            [
                ("Lab", "Lab", "TEG 5000", ["Kaolin", "Rapid TEG", "PLM"]),
                ("Lab", "Lab", "TEG 5000", ["Kaolin", "Rapid TEG", "PLM"]),
                ("Lab", "Lab", "TEG 5000", ["Kaolin", "Rapid TEG", "PLM"]),
                ("Lab", "Lab", "TEG 5000", ["Kaolin", "Rapid TEG", "PLM"]),
            ],
        ),
        (
            "St. Mary's Medical Center",
            "Tenet Healthcare",
            None, "West Palm Beach", "FL", "South FL",
            [],  # Hybrid 5000 + 6s planned
        ),
        # ── Independent ────────────────────────────────────────────────────────
        (
            "Jupiter Medical Center",
            "Independent",
            None, "Jupiter", "FL", "South FL",
            [],  # HN validated; tube station pending
        ),
        (
            "Mercy Hospital",
            "Independent",
            None, "Miami", "FL", "South FL",
            [],
        ),
    ]

    # ── Insert / upsert everything ─────────────────────────────────────────────
    accounts_created = 0
    tegs_created = 0

    for (name, sys_key, address, city, state, territory, teg_list) in hospitals:
        system_id = systems[sys_key]
        account_id = db.upsert_account(
            name=name,
            system_id=system_id,
            address=address,
            city=city,
            state=state,
            territory=territory,
        )
        accounts_created += 1

        # Clear existing TEGs for this account so we don't duplicate on re-run
        # (We insert fresh; add_teg always creates a new row, so we guard with a check)
        conn = db.get_conn()
        existing_teg_count = conn.execute(
            "SELECT COUNT(*) FROM teg_machines WHERE account_id=? AND is_active=1",
            (account_id,)
        ).fetchone()[0]
        conn.close()

        if existing_teg_count == 0:
            for (location, department, model, cartridges) in teg_list:
                teg_id = db.add_teg(
                    account_id=account_id,
                    location=location,
                    department=department,
                    model=model,
                )
                if cartridges:
                    db.set_teg_cartridges(teg_id, cartridges)
                tegs_created += 1

        print(f"  ✓ {name} (system: {sys_key}, TEGs: {len(teg_list)})")

    print(f"\nDone. {accounts_created} accounts upserted, {tegs_created} TEG machines inserted.")


if __name__ == "__main__":
    seed()
