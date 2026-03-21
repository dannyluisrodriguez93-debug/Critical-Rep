"""
macOS Contacts integration via the Contacts framework (pyobjc).

Reads contacts from the macOS Contacts app (synced from iCloud/iPhone),
fuzzy-matches their organization field to hospital accounts, and inserts
them into the local contacts table.

Matching rules (hardened to avoid false positives):
- Only matches on organization field, never on contact name.
- Organization must contain a known hospital keyword to be considered.
- Organizations in the exclusion list are never matched.
- Uses fuzzy matching with a high threshold (75+), no substring matching.

Requires: pip install pyobjc-framework-Contacts
"""

import logging
import re
import sys

from rapidfuzz import process, fuzz

import database as db

log = logging.getLogger(__name__)

MATCH_THRESHOLD = 60

# Delimiters used to separate hospital name from role in the Company/Org field.
# Require spaces on both sides to avoid splitting abbreviations like "PGY -4".
# Supported:  "Hospital Name - Role",  "Hospital / Role",  "Hospital | Role"
_ORG_SPLIT_RE = re.compile(r"\s+[-/|]\s+", re.IGNORECASE)

_ROLE_PREFIXES = {
    "director", "manager", "coordinator", "supervisor", "specialist",
    "nurse", "physician", "doctor", "vp ", "chief", "officer", "admin",
    "consultant", "representative", "rep ", "analyst", "technician",
}


def _parse_org_field(org: str) -> tuple[str, str | None]:
    """Split an Organization field into (hospital_name, role).

    Contacts may encode both pieces of info in the Company/Org field:
        "Baptist Health - Medical Director"
        "Memorial Hospital / Case Manager"

    Returns the hospital portion for matching, and the extracted role (or None).
    """
    if not org:
        return org, None

    parts = _ORG_SPLIT_RE.split(org, maxsplit=1)
    if len(parts) < 2:
        return org.strip(), None

    hospital_part = parts[0].strip()
    role_part = parts[1].strip()

    first_lower = hospital_part.lower()
    if any(first_lower.startswith(rp) for rp in _ROLE_PREFIXES):
        return role_part, hospital_part

    return hospital_part, role_part if role_part else None

# Organizations that should NEVER match a hospital account
EXCLUDED_ORGS = {
    "mdc medical", "medtronic", "keralty", "banner medical", "mini goats",
    "petland", "biohazard", "crossfit", "peacehealth", "rr az",
    "university health", "umh", "um hospital", "healthtrust",
    "medtronic swu", "medpro", "st. francis", "south ahore",
    "mireya's son", "um cvicu", "u miami",
}

# An org must contain at least one of these specific hospital keywords
# to be considered for matching. Generic words like "medical" or "health"
# are intentionally excluded to prevent false positives.
HOSPITAL_KEYWORDS = {
    "baptist", "broward", "cleveland", "memorial", "holy cross", "northwest",
    "boca", "jackson", "jfk", "delray", "jupiter", "mercy", "lawnwood",
    "westside", "haemonetics", "st. mary", "st mary", "st marys", "st. marys",
    "hca", "south miami",
}


def fetch_all_contacts() -> list[dict]:
    """
    Read all contacts from macOS Contacts via the Contacts framework.
    Returns list of dicts with keys: name, organization, title, phone, email.
    """
    if sys.platform != "darwin":
        log.warning("macOS Contacts sync is only available on macOS")
        return []

    try:
        import Contacts
    except ImportError:
        log.error("pyobjc-framework-Contacts not installed. Run: pip install pyobjc-framework-Contacts")
        return []

    store = Contacts.CNContactStore.alloc().init()
    keys = [
        Contacts.CNContactGivenNameKey,
        Contacts.CNContactFamilyNameKey,
        Contacts.CNContactOrganizationNameKey,
        Contacts.CNContactJobTitleKey,
        Contacts.CNContactPhoneNumbersKey,
        Contacts.CNContactEmailAddressesKey,
    ]

    request = Contacts.CNContactFetchRequest.alloc().initWithKeysToFetch_(keys)
    contacts = []

    def handler(contact, stop):
        given = contact.givenName() or ""
        family = contact.familyName() or ""
        org = contact.organizationName() or ""
        title = contact.jobTitle() or ""
        phones = contact.phoneNumbers()
        phone = phones[0].value().stringValue() if phones else ""
        emails = contact.emailAddresses()
        email = str(emails[0].value()) if emails else ""
        name = f"{given} {family}".strip()
        if name:
            contacts.append({
                "name": name,
                "organization": org,
                "title": title,
                "phone": phone,
                "email": email,
            })

    success, error = store.enumerateContactsWithFetchRequest_error_usingBlock_(
        request, None, handler
    )
    if not success:
        log.error("macOS Contacts: enumerate failed: %s", error)
        return []

    return contacts


def _is_excluded_org(org: str) -> bool:
    """Return True if the organization is in the exclusion list."""
    org_lower = org.lower().strip()
    for excluded in EXCLUDED_ORGS:
        if excluded in org_lower:
            return True
    return False


def _has_hospital_keyword(org: str) -> bool:
    """Return True if the organization contains a specific hospital keyword."""
    org_lower = org.lower()
    return any(kw in org_lower for kw in HOSPITAL_KEYWORDS)


def _shared_hospital_keywords(text_a: str, text_b: str) -> set:
    """Return the set of hospital keywords present in both strings."""
    a_lower = text_a.lower()
    b_lower = text_b.lower()
    return {kw for kw in HOSPITAL_KEYWORDS if kw in a_lower and kw in b_lower}


def _match_org_to_account(org: str, all_names: list, account_names_ids: list) -> int | None:
    """Fuzzy-match an organization string to an account name/alias.

    Only matches if:
    1. The org is not in the exclusion list.
    2. The org contains at least one hospital keyword.
    3. The org and the matched account share at least one hospital keyword.
    4. The fuzzy match score meets the threshold (75+).
    """
    if not all_names or not org:
        return None

    if _is_excluded_org(org):
        log.debug("macOS Contacts: excluded org '%s'", org)
        return None

    if not _has_hospital_keyword(org):
        log.debug("macOS Contacts: no hospital keyword in org '%s'", org)
        return None

    # Get top candidates and pick the best one that shares a hospital keyword
    matches = process.extract(org, all_names, scorer=fuzz.token_sort_ratio, limit=5)
    for match_name, score, _ in matches:
        if score < MATCH_THRESHOLD:
            break
        if _shared_hospital_keywords(org, match_name):
            return next((aid for n, aid in account_names_ids if n == match_name), None)

    return None


def sync_macos_contacts() -> dict:
    """
    Fetch contacts from macOS Contacts app, match organizations to accounts,
    insert into local contacts table.
    Returns summary dict.
    """
    contacts = fetch_all_contacts()
    total_fetched = len(contacts)
    log.info("macOS Contacts: fetched %d contacts", total_fetched)

    if not contacts:
        return {"synced": 0, "total_fetched": 0, "skipped": 0}

    account_names_ids = db.get_all_account_names_and_aliases()
    all_names = [n for n, _ in account_names_ids]

    synced = 0
    skipped = 0

    for person in contacts:
        name  = person["name"]
        raw_org = person["organization"]
        title = person["title"]
        phone = person["phone"]
        email = person["email"]

        # Parse the Org/Company field — may contain "Hospital Name - Role"
        hospital_name, extracted_role = _parse_org_field(raw_org) if raw_org else (None, None)
        effective_title = title or extracted_role

        account_id = None

        # Try parsed hospital name first (cleaner match), then full raw org
        if hospital_name and hospital_name != raw_org:
            account_id = _match_org_to_account(hospital_name, all_names, account_names_ids)
            if account_id:
                log.debug(
                    "macOS Contacts: matched '%s' via parsed hospital '%s' (raw: '%s')",
                    name, hospital_name, raw_org,
                )

        if not account_id and raw_org:
            account_id = _match_org_to_account(raw_org, all_names, account_names_ids)

        if not account_id:
            skipped += 1
            continue

        # Skip if exact name+account combo already exists
        existing = db.get_contacts(account_id)
        if any(c["name"].lower() == name.lower() for c in existing):
            skipped += 1
            continue

        notes_suffix = hospital_name or raw_org or ""
        db.add_contact(
            account_id=account_id,
            name=name,
            role=effective_title or None,
            phone=phone or None,
            email=email or None,
            notes="Synced from macOS Contacts" + (f" — {notes_suffix}" if notes_suffix else ""),
        )
        synced += 1
        log.info(
            "macOS Contacts: added '%s' -> account %d (org: %s, role: %s)",
            name, account_id, hospital_name or raw_org or "", effective_title or "",
        )

    log.info("macOS Contacts: synced %d, skipped %d of %d fetched", synced, skipped, total_fetched)
    return {"synced": synced, "total_fetched": total_fetched, "skipped": skipped}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    result = sync_macos_contacts()
    print(f"Result: {result}")
