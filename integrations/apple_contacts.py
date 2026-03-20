"""
Apple Contacts sync via AppleScript (macOS only).

Reads all contacts from the macOS Contacts app, fuzzy-matches each contact's
organization name against known hospital accounts, and upserts matched contacts
into the contacts table with their job title stored as the 'role' field.

Requires macOS + Contacts access granted to Terminal / Python (System Settings →
Privacy & Security → Contacts).
"""

import logging
import subprocess
import sys

from rapidfuzz import fuzz, process

import database as db

log = logging.getLogger(__name__)

# Minimum fuzzy score to consider an organization → account match
MATCH_THRESHOLD = 65


def _is_available() -> bool:
    return sys.platform == "darwin"


def _run_applescript(script: str, timeout: int = 60) -> str | None:
    """Execute an AppleScript string and return stdout, or None on error."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            log.error("AppleScript error: %s", result.stderr.strip())
            return None
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        log.error("AppleScript timed out after %ds", timeout)
        return None
    except FileNotFoundError:
        log.error("osascript not found — are you on macOS?")
        return None


def get_all_contacts_bulk() -> list[dict]:
    """
    Fetch all contacts from macOS Contacts.app via a single AppleScript call.
    Returns a list of dicts with keys: name, job_title, organization, phone, email.
    Fields default to empty string when unavailable.
    """
    # Use ASCII record separator (chr 30) so we can safely split lines
    script = r"""
set RS to ASCII character 30
set output to ""
tell application "Contacts"
    repeat with p in every person
        set pName to ""
        try
            set pName to name of p
        end try

        set pTitle to ""
        try
            set pTitle to job title of p
        end try
        if pTitle is missing value then set pTitle to ""

        set pOrg to ""
        try
            set pOrg to organization of p
        end try
        if pOrg is missing value then set pOrg to ""

        set pPhone to ""
        try
            if (count of phones of p) > 0 then
                set pPhone to value of item 1 of phones of p
            end if
        end try

        set pEmail to ""
        try
            if (count of emails of p) > 0 then
                set pEmail to value of item 1 of emails of p
            end if
        end try

        set output to output & pName & tab & pTitle & tab & pOrg & tab & pPhone & tab & pEmail & RS
    end repeat
end tell
return output
"""
    raw = _run_applescript(script, timeout=90)
    if raw is None:
        return []

    contacts = []
    for record in raw.split("\x1e"):  # ASCII 30 = record separator
        record = record.strip()
        if not record:
            continue
        parts = record.split("\t")
        # Pad to 5 fields in case any are missing
        parts += [""] * (5 - len(parts))
        name, job_title, organization, phone, email = [p.strip() for p in parts[:5]]
        if not name:
            continue
        contacts.append({
            "name":         name,
            "job_title":    job_title,
            "organization": organization,
            "phone":        phone,
            "email":        email,
        })

    log.info("Apple Contacts: fetched %d contacts from Contacts.app", len(contacts))
    return contacts


def _build_account_lookup(accounts: list[dict]) -> dict[str, int]:
    """
    Returns a flat name→account_id map including the main name and all aliases.
    Used as the haystack for rapidfuzz matching.
    """
    lookup = {}
    for acct in accounts:
        lookup[acct["name"]] = acct["id"]
        for alias in acct.get("aliases") or []:
            if alias:
                lookup[alias] = acct["id"]
    return lookup


def _normalize(s: str) -> str:
    """Lowercase and strip common suffixes that obscure fuzzy matching."""
    s = s.lower().strip()
    for suffix in (" hospital", " medical center", " health", " healthcare",
                   " clinic", " center", " regional", " community"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    return s


def _match_organization(organization: str, account_lookup: dict[str, int]) -> int | None:
    """
    Fuzzy-match an organization name against all known account names/aliases.
    Returns the account_id if a match meets MATCH_THRESHOLD, otherwise None.
    """
    if not organization:
        return None

    norm_org = _normalize(organization)
    norm_lookup = {_normalize(k): v for k, v in account_lookup.items()}

    result = process.extractOne(
        norm_org,
        norm_lookup.keys(),
        scorer=fuzz.token_set_ratio,
        score_cutoff=MATCH_THRESHOLD,
    )
    if result:
        matched_key, score, _ = result
        log.debug("Matched '%s' → '%s' (score=%d)", organization, matched_key, score)
        return norm_lookup[matched_key]
    return None


def _contact_exists(conn, account_id: int, phone: str, email: str) -> bool:
    """Return True if a contact with this phone or email already exists for the account."""
    checks = []
    params = []

    if phone:
        checks.append("phone=?")
        params.append(phone)
    if email:
        checks.append("email=?")
        params.append(email)

    if not checks:
        return False

    where = " OR ".join(checks)
    row = conn.execute(
        f"SELECT id FROM contacts WHERE account_id=? AND ({where}) LIMIT 1",
        [account_id, *params],
    ).fetchone()
    return row is not None


def sync_apple_contacts() -> dict:
    """
    Main entry point.  Reads Contacts.app, matches organizations to accounts,
    and inserts new contacts (with role = job_title) into the contacts table.

    Returns a summary dict with keys:
        ok, contacts_found, matched, added, skipped_existing
    """
    if not _is_available():
        return {"ok": False, "reason": "Not on macOS"}

    raw_contacts = get_all_contacts_bulk()
    if not raw_contacts:
        return {"ok": True, "contacts_found": 0, "matched": 0, "added": 0, "skipped_existing": 0}

    accounts = db.get_all_accounts()
    account_lookup = _build_account_lookup(accounts)

    conn = db.get_conn()
    added = 0
    matched = 0
    skipped = 0

    for c in raw_contacts:
        account_id = _match_organization(c["organization"], account_lookup)
        if account_id is None:
            continue
        matched += 1

        if _contact_exists(conn, account_id, c["phone"], c["email"]):
            skipped += 1
            continue

        conn.execute(
            """INSERT INTO contacts (account_id, name, role, phone, email, notes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                account_id,
                c["name"],
                c["job_title"] or None,
                c["phone"] or None,
                c["email"] or None,
                "Synced from Apple Contacts",
            ),
        )
        added += 1

    conn.commit()
    conn.close()

    log.info(
        "Apple Contacts sync complete: found=%d matched=%d added=%d skipped=%d",
        len(raw_contacts), matched, added, skipped,
    )
    return {
        "ok": True,
        "contacts_found": len(raw_contacts),
        "matched": matched,
        "added": added,
        "skipped_existing": skipped,
    }
