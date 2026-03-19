"""
Account Hub — Initial Setup Script
Run this once to seed your accounts into the database.

Usage:
  python setup_accounts.py           # interactive mode
  python setup_accounts.py --demo    # load sample Haemonetics accounts
  python setup_accounts.py --list    # show all accounts currently in DB
"""

import sys
import database as db

DEMO_ACCOUNTS = [
    {
        "system": "Baptist Health System",
        "system_aliases": ["Baptist Health", "Baptist"],
        "hospitals": [
            {"name": "Baptist Hospital", "aliases": ["Baptist Hospital Miami", "Baptist Hospital Total", "Baptist Hosp"]},
            {"name": "Baptist Hospital South", "aliases": ["Baptist South", "South Baptist"]},
            {"name": "Baptist Hospital Homestead", "aliases": ["Baptist Homestead", "Homestead Baptist"]},
            {"name": "Doctors Hospital", "aliases": ["Doctors Hosp"]},
        ],
    },
    {
        "system": "Jackson Health System",
        "system_aliases": ["Jackson Health", "Jackson"],
        "hospitals": [
            {"name": "Jackson Memorial Hospital", "aliases": ["Jackson Memorial", "Jackson Mem"]},
            {"name": "Jackson South Medical Center", "aliases": ["Jackson South"]},
            {"name": "Jackson North Medical Center", "aliases": ["Jackson North"]},
        ],
    },
    {
        "system": "HCA Florida",
        "system_aliases": ["HCA"],
        "hospitals": [
            {"name": "HCA Florida JFK Hospital", "aliases": ["HCA Florida JFK", "JFK Medical Center", "HCA JFK", "HCA Florida JFK Hospital (FKA JFK Medical Center)"]},
            {"name": "HCA Florida Kendall Hospital", "aliases": ["HCA Kendall", "Kendall Medical"]},
            {"name": "HCA Florida Mercy Hospital", "aliases": ["HCA Mercy", "Mercy Hospital"]},
        ],
    },
    {
        "system": "Cleveland Clinic",
        "system_aliases": ["Cleveland Clinic Florida"],
        "hospitals": [
            {"name": "Cleveland Clinic Weston", "aliases": ["Cleveland Clinic", "Cleveland Clinic FL"]},
            {"name": "Cleveland Clinic Indian River", "aliases": ["Cleveland Clinic IR"]},
        ],
    },
    {
        "system": None,
        "hospitals": [
            {"name": "Delray Medical Center", "aliases": ["Delray Medical", "Delray Med Ctr"]},
            {"name": "Boca Raton Regional Hospital", "aliases": ["Boca Regional", "BRRH"]},
            {"name": "Bethesda Hospital East", "aliases": ["Bethesda East", "Bethesda"]},
            {"name": "Good Samaritan Medical Center", "aliases": ["Good Samaritan", "Good Sam"]},
            {"name": "Palm Beach Gardens Medical Center", "aliases": ["PBG Medical", "PBGMC"]},
            {"name": "St. Mary's Medical Center", "aliases": ["St Marys", "Saint Marys"]},
        ],
    },
]


def load_demo():
    db.init_db()
    count = 0
    for group in DEMO_ACCOUNTS:
        system_id = None
        if group.get("system"):
            system_id = db.upsert_system(group["system"], aliases=group.get("system_aliases", []))
            print(f"  System: {group['system']}")

        for hosp in group["hospitals"]:
            db.upsert_account(
                name=hosp["name"],
                system_id=system_id,
                aliases=hosp.get("aliases", []),
            )
            prefix = "    └ " if system_id else "  "
            print(f"{prefix}{hosp['name']}")
            count += 1

    print(f"\n✓ Loaded {count} accounts into database.\n")


def list_accounts():
    db.init_db()
    accounts = db.get_all_accounts()
    if not accounts:
        print("No accounts yet. Run: python setup_accounts.py --demo")
        return

    current_system = None
    for a in accounts:
        sys_name = a.get("system_name") or "Ungrouped"
        if sys_name != current_system:
            print(f"\n{sys_name}")
            print("─" * len(sys_name))
            current_system = sys_name
        aliases = a.get("aliases", [])
        alias_str = f"  [{', '.join(aliases[:3])}]" if aliases else ""
        print(f"  • {a['name']}{alias_str}")
    print()


def interactive_mode():
    db.init_db()
    print("\n" + "="*55)
    print("  Account Hub — Account Setup")
    print("="*55)
    print("\nThis will add your accounts to the database.")
    print("The system uses fuzzy matching, so aliases help")
    print("map report names automatically.\n")
    print("Options:")
    print("  1) Add accounts grouped by hospital system")
    print("  2) Paste a flat list of account names")
    print("  3) Load demo Haemonetics accounts (good starting point)")
    print("  4) Exit")

    choice = input("\nChoice [1-4]: ").strip()

    if choice == "1":
        _add_grouped()
    elif choice == "2":
        _add_flat()
    elif choice == "3":
        load_demo()
    else:
        print("Exiting.")


def _add_grouped():
    print("\nEnter hospital system name (or press Enter to skip system grouping):")
    while True:
        system_name = input("System name (Enter to finish): ").strip()
        if not system_name:
            break

        aliases_raw = input(f"  Aliases for '{system_name}' (comma-separated, or Enter to skip): ").strip()
        aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()] if aliases_raw else []
        system_id = db.upsert_system(system_name, aliases=aliases)

        print(f"  Now enter hospitals in {system_name} (one per line, blank line when done):")
        while True:
            hosp_name = input("    Hospital name: ").strip()
            if not hosp_name:
                break
            hosp_aliases_raw = input(f"      Aliases for '{hosp_name}': ").strip()
            hosp_aliases = [a.strip() for a in hosp_aliases_raw.split(",") if a.strip()] if hosp_aliases_raw else []
            db.upsert_account(hosp_name, system_id=system_id, aliases=hosp_aliases)
            print(f"      ✓ Added {hosp_name}")

    print("\n✓ Done. Run 'python setup_accounts.py --list' to verify.\n")


def _add_flat():
    print("\nPaste your account names below (one per line).")
    print("Press Enter twice when done:\n")
    lines = []
    while True:
        line = input()
        if not line:
            break
        lines.append(line.strip())

    added = 0
    for name in lines:
        if name:
            db.upsert_account(name)
            print(f"  ✓ {name}")
            added += 1

    print(f"\n✓ Added {added} accounts.\n")
    print("Tip: run with --demo to also load sample accounts,")
    print("or re-run to group them into hospital systems.\n")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        print("\nLoading demo Haemonetics accounts...\n")
        load_demo()
    elif "--list" in sys.argv:
        list_accounts()
    else:
        interactive_mode()
