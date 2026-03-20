"""
Google Contacts integration via the People API.

Pulls contacts from the authenticated Google account, fuzzy-matches their
organization/company fields to hospital accounts, and upserts them into the
local contacts table.

Uses the same OAuth token as Gmail + Drive (single Google login).
Requires the 'contacts.readonly' scope — added to GOOGLE_SCOPES in config.py.
"""

import logging

from rapidfuzz import process, fuzz

import database as db
from integrations.google_auth import get_credentials, is_connected

log = logging.getLogger(__name__)

# Minimum score to accept a company→account match
MATCH_THRESHOLD = 65


def sync_google_contacts() -> dict:
    """
    Fetch contacts from Google, match organizations to accounts,
    upsert into local contacts table.
    Returns summary dict.
    """
    if not is_connected():
        log.warning("Google Contacts: not connected — skipping")
        return {"synced": 0, "total_fetched": 0, "error": "not_connected"}

    creds = get_credentials()
    if not creds:
        log.error("Google Contacts: could not load credentials")
        return {"synced": 0, "total_fetched": 0, "error": "no_credentials"}

    try:
        from googleapiclient.discovery import build
        people_svc = build("people", "v1", credentials=creds)
    except Exception as e:
        log.error("Google Contacts: could not build People service: %s", e)
        return {"synced": 0, "total_fetched": 0, "error": str(e)}

    contacts = _fetch_all_contacts(people_svc)
    log.info("Google Contacts: fetched %d contacts", len(contacts))

    if not contacts:
        return {"synced": 0, "total_fetched": 0}

    account_names_ids = db.get_all_account_names_and_aliases()
    all_names = [n for n, _ in account_names_ids]

    synced = 0
    skipped = 0
    for person in contacts:
        name = _get_name(person)
        if not name:
            continue

        org   = _get_org(person)
        title = _get_title(person)
        email = _get_email(person)
        phone = _get_phone(person)

        # Try to match by organization first, then by contact name (for individual
        # contacts at a hospital whose name contains the hospital name)
        account_id = None

        if org:
            account_id = _match_to_account(org, all_names, account_names_ids)

        if not account_id and name:
            account_id = _match_to_account(name, all_names, account_names_ids)

        if not account_id:
            log.debug("Google Contacts: no account match for '%s' (org: %s)", name, org)
            skipped += 1
            continue

        # Upsert: skip if exact name+account combo already exists
        existing = db.get_contacts(account_id)
        if any(c["name"].lower() == name.lower() for c in existing):
            log.debug("Google Contacts: '%s' already in account %d", name, account_id)
            continue

        db.add_contact(
            account_id=account_id,
            name=name,
            role=title,
            phone=phone,
            email=email,
            notes=f"Synced from Google Contacts{' — ' + org if org else ''}",
        )
        synced += 1
        log.info("Google Contacts: added '%s' → account %d (%s)", name, account_id, org or "")

    log.info("Google Contacts: synced %d, skipped %d", synced, skipped)
    return {"synced": synced, "skipped": skipped, "total_fetched": len(contacts)}


def _fetch_all_contacts(people_svc, max_results: int = 500) -> list[dict]:
    """Page through all contacts and return raw person resources."""
    people = []
    page_token = None

    while True:
        kwargs = dict(
            resourceName="people/me",
            pageSize=min(200, max_results - len(people)),
            personFields="names,emailAddresses,phoneNumbers,organizations",
        )
        if page_token:
            kwargs["pageToken"] = page_token

        try:
            result = people_svc.people().connections().list(**kwargs).execute()
        except Exception as e:
            log.error("Google Contacts: list failed: %s", e)
            break

        people.extend(result.get("connections", []))
        page_token = result.get("nextPageToken")
        if not page_token or len(people) >= max_results:
            break

    return people


def _get_name(person: dict) -> str | None:
    names = person.get("names", [])
    if names:
        return names[0].get("displayName") or names[0].get("unstructuredName")
    return None


def _get_org(person: dict) -> str | None:
    orgs = person.get("organizations", [])
    if orgs:
        return orgs[0].get("name") or orgs[0].get("current")
    return None


def _get_title(person: dict) -> str | None:
    orgs = person.get("organizations", [])
    if orgs:
        return orgs[0].get("title")
    return None


def _get_email(person: dict) -> str | None:
    emails = person.get("emailAddresses", [])
    return emails[0].get("value") if emails else None


def _get_phone(person: dict) -> str | None:
    phones = person.get("phoneNumbers", [])
    return phones[0].get("value") if phones else None


def _match_to_account(text: str, all_names: list, account_names_ids: list) -> int | None:
    if not all_names or not text:
        return None
    match = process.extractOne(text, all_names, scorer=fuzz.token_sort_ratio)
    if match and match[1] >= MATCH_THRESHOLD:
        matched_name = match[0]
        return next((aid for n, aid in account_names_ids if n == matched_name), None)
    return None
