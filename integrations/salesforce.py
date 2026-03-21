"""
Salesforce integration (optional).
If you have API access, this pulls account contacts and revenue data
directly from SF and merges it into the local database.

Gracefully no-ops if credentials are missing or access is denied.
"""

import logging

from rapidfuzz import process, fuzz

import config
import database as db

log = logging.getLogger(__name__)


def _get_sf():
    """Return a Salesforce connection or None if unavailable.

    Prefers OAuth tokens (Web Server Flow) over legacy username/password auth.
    """
    from simple_salesforce import Salesforce

    # ── OAuth path (preferred) ─────────────────────────────────────────────────
    try:
        from integrations.salesforce_auth import is_connected, get_access_token, get_instance_url
        if is_connected():
            access_token = get_access_token()
            instance_url = get_instance_url()
            if access_token and instance_url:
                sf = Salesforce(session_id=access_token, instance_url=instance_url)
                log.info("Salesforce connected via OAuth — instance: %s", instance_url)
                return sf
    except Exception as e:
        log.warning("Salesforce OAuth init failed, trying credentials: %s", e)

    # ── Legacy username/password path (fallback) ───────────────────────────────
    username = db.get_setting("sf_username") or config.SF_USERNAME
    password = db.get_setting("sf_password") or config.SF_PASSWORD
    token    = db.get_setting("sf_security_token") or config.SF_SECURITY_TOKEN
    domain   = db.get_setting("sf_domain") or config.SF_DOMAIN

    if not all([username, password]):
        log.info("Salesforce not configured — skipping SF sync")
        return None
    try:
        sf = Salesforce(
            username=username,
            password=password,
            security_token=token or "",
            domain=domain or "login",
        )
        log.info("Salesforce connected as %s", username)
        return sf
    except Exception as e:
        log.warning("Salesforce connection failed: %s", e)
        return None


def sync_sf_contacts() -> int:
    """
    Pull contacts from Salesforce and match them to local accounts.
    Returns number of contacts synced.
    """
    sf = _get_sf()
    if not sf:
        return 0

    account_names_ids = db.get_all_account_names_and_aliases()
    all_names = [n for n, _ in account_names_ids]

    try:
        result = sf.query_all("""
            SELECT Id, Name, Title, Phone, Email, Account.Name, Account.Id
            FROM Contact
            WHERE Account.Name != null
            ORDER BY Account.Name, Name
        """)
    except Exception as e:
        log.warning("SF contacts query failed: %s", e)
        return 0

    synced = 0
    for record in result.get("records", []):
        acct_name_sf = record.get("Account", {}).get("Name", "")
        contact_name = record.get("Name", "")
        if not acct_name_sf or not contact_name:
            continue

        match = process.extractOne(acct_name_sf, all_names, scorer=fuzz.token_sort_ratio)
        if not match or match[1] < 70:
            continue

        account_id = next(
            (aid for n, aid in account_names_ids if n == match[0]), None
        )
        if not account_id:
            continue

        # Check if contact already exists
        existing = db.get_contacts(account_id)
        if any(c["name"].lower() == contact_name.lower() for c in existing):
            continue  # don't duplicate

        db.add_contact(
            account_id=account_id,
            name=contact_name,
            role=record.get("Title"),
            phone=record.get("Phone"),
            email=record.get("Email"),
            notes="Synced from Salesforce",
        )
        synced += 1

    log.info("Salesforce: synced %d contacts", synced)
    return synced


def sync_sf_opportunities() -> int:
    """
    Pull current quarter opportunity amounts from Salesforce.
    Stores as revenue_targets entries.
    Returns number of accounts updated.
    """
    sf = _get_sf()
    if not sf:
        return 0

    account_names_ids = db.get_all_account_names_and_aliases()
    all_names = [n for n, _ in account_names_ids]

    try:
        result = sf.query_all("""
            SELECT Account.Name, SUM(Amount) TotalAmount, CALENDAR_QUARTER(CloseDate) Quarter
            FROM Opportunity
            WHERE IsClosed = false AND CloseDate = THIS_QUARTER
            GROUP BY Account.Name, CALENDAR_QUARTER(CloseDate)
        """)
    except Exception as e:
        log.warning("SF opportunities query failed (may need GroupBy permission): %s", e)
        return 0

    from datetime import date
    today = date.today()
    quarter_label = f"{today.year}-Q{((today.month - 1) // 3) + 1}"
    updated = 0

    for record in result.get("records", []):
        acct_name_sf = record.get("Account", {}).get("Name", "")
        amount = record.get("TotalAmount", 0) or 0

        match = process.extractOne(acct_name_sf, all_names, scorer=fuzz.token_sort_ratio)
        if not match or match[1] < 70:
            continue

        account_id = next(
            (aid for n, aid in account_names_ids if n == match[0]), None
        )
        if not account_id:
            continue

        db.upsert_revenue_target(
            account_id=account_id,
            period_type="quarter",
            period_label=quarter_label,
            actual=amount,
            rr_actual=amount,
            target=0,
            pct_of_target=0,
            py_revenue=0,
            report_date=today.isoformat(),
        )
        updated += 1

    log.info("Salesforce: updated %d account opportunity amounts", updated)
    return updated


def run_sf_sync() -> dict:
    contacts = sync_sf_contacts()
    opps = sync_sf_opportunities()
    return {"contacts_synced": contacts, "opportunities_synced": opps}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    result = run_sf_sync()
    print(result)
