"""
macOS Contacts integration via the Contacts framework (pyobjc).

Reads contacts from the macOS Contacts app (synced from iCloud/iPhone),
fuzzy-matches their organization field to hospital accounts, and inserts
them into the local contacts table.

Requires: pip install pyobjc-framework-Contacts
"""

import logging
import sys

from rapidfuzz import process, fuzz

import database as db

log = logging.getLogger(__name__)

MATCH_THRESHOLD = 60

# Separators used in Company fields that combine hospital name + role
# e.g. "St. Mary's Hospital - Lab Director"  or  "BJC Healthcare | Purchasing"
_COMPANY_SEPARATORS = [" - ", " — ", " | ", " / ", "; "]


def _parse_company_field(company: str) -> tuple[list[str], str | None]:
    """
    Parse a Company field that may embed a role alongside the hospital name,
    e.g. "St. Mary's Medical Center - Lab Director".

    Returns:
      candidates  — ordered list of strings to try for hospital matching
                    (left part first, then right, then full string as fallback)
      role        — extracted role string, or None if field is a plain name
    """
    company = (company or "").strip()
    if not company:
        return [], None

    for sep in _COMPANY_SEPARATORS:
        if sep in company:
            left, right = company.split(sep, 1)
            left, right = left.strip(), right.strip()
            # Left side is usually the hospital name; right is usually the role.
            # Return left first so matching tries the cleaner hospital name first.
            role = right if right else None
            return [left, right, company], role

    return [company], None


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


def _match_to_account(text: str, all_names: list, account_names_ids: list) -> int | None:
    """Fuzzy-match a string to an account name/alias."""
    if not all_names or not text:
        return None
    match = process.extractOne(text, all_names, scorer=fuzz.token_sort_ratio)
    if match and match[1] >= MATCH_THRESHOLD:
        matched_name = match[0]
        return next((aid for n, aid in account_names_ids if n == matched_name), None)
    return None


def _substring_match(text: str, alias_lookup: list) -> int | None:
    """Check if any account name/alias is a substring of the text."""
    text_lower = text.lower()
    for alias_lower, aid in alias_lookup:
        if len(alias_lower) >= 4 and alias_lower in text_lower:
            return aid
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

    # Build alias lookup for substring matching (longest first)
    alias_lookup = [(n.lower(), aid) for n, aid in account_names_ids]
    alias_lookup.sort(key=lambda x: len(x[0]), reverse=True)

    synced = 0
    skipped = 0

    for person in contacts:
        name = person["name"]
        org = person["organization"]
        title = person["title"]
        phone = person["phone"]
        email = person["email"]

        account_id = None

        # Parse the Company field — it may contain "Hospital Name - Role"
        company_candidates, embedded_role = _parse_company_field(org)

        # Use embedded role when no explicit Job Title is set
        effective_title = title or embedded_role

        # Strategy 1: fuzzy match on each Company field candidate (left part first)
        for candidate in company_candidates:
            account_id = _match_to_account(candidate, all_names, account_names_ids)
            if account_id:
                break

        # Strategy 2: substring match on each Company candidate
        if not account_id:
            for candidate in company_candidates:
                account_id = _substring_match(candidate, alias_lookup)
                if account_id:
                    break

        # Strategy 3: fuzzy match on contact name as last resort
        if not account_id and name:
            account_id = _match_to_account(name, all_names, account_names_ids)

        if not account_id:
            skipped += 1
            continue

        # Skip if exact name+account combo already exists
        existing = db.get_contacts(account_id)
        if any(c["name"].lower() == name.lower() for c in existing):
            skipped += 1
            continue

        db.add_contact(
            account_id=account_id,
            name=name,
            role=effective_title or None,
            phone=phone or None,
            email=email or None,
            notes="Synced from macOS Contacts" + (f" — {org}" if org else ""),
        )
        synced += 1
        log.info("macOS Contacts: added '%s' -> account %d (%s)", name, account_id, org or "")

    log.info("macOS Contacts: synced %d, skipped %d of %d fetched", synced, skipped, total_fetched)
    return {"synced": synced, "total_fetched": total_fetched, "skipped": skipped}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    result = sync_macos_contacts()
    print(f"Result: {result}")
