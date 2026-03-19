"""
OneNote sync via Microsoft Graph API.
Searches your OneNote notebooks for pages mentioning account names,
pulls the content, and stores it in account_notes.
"""

import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from rapidfuzz import process, fuzz

import database as db
from integrations.ms_auth import get_access_token

log = logging.getLogger(__name__)
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _headers() -> dict | None:
    token = get_access_token(["Notes.Read.All", "offline_access"])
    if not token:
        return None
    return {"Authorization": f"Bearer {token}"}


def get_all_notebooks() -> list[dict]:
    h = _headers()
    if not h:
        return []
    resp = requests.get(f"{GRAPH_BASE}/me/onenote/notebooks", headers=h)
    if resp.status_code != 200:
        log.error("OneNote notebooks error %d", resp.status_code)
        return []
    return resp.json().get("value", [])


def get_pages(notebook_id: str = None) -> list[dict]:
    """Get all pages (or pages from a specific notebook)."""
    h = _headers()
    if not h:
        return []

    if notebook_id:
        url = f"{GRAPH_BASE}/me/onenote/notebooks/{notebook_id}/sections"
        resp = requests.get(url, headers=h)
        if resp.status_code != 200:
            return []
        sections = resp.json().get("value", [])
        pages = []
        for sec in sections:
            sec_resp = requests.get(
                f"{GRAPH_BASE}/me/onenote/sections/{sec['id']}/pages",
                headers=h,
                params={"$select": "id,title,lastModifiedDateTime,createdDateTime"},
            )
            if sec_resp.status_code == 200:
                pages.extend(sec_resp.json().get("value", []))
        return pages
    else:
        resp = requests.get(
            f"{GRAPH_BASE}/me/onenote/pages",
            headers=h,
            params={"$select": "id,title,lastModifiedDateTime,createdDateTime", "$top": 100},
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("value", [])


def get_page_content(page_id: str) -> str:
    """Return plain text content of a OneNote page."""
    h = _headers()
    if not h:
        return ""
    resp = requests.get(
        f"{GRAPH_BASE}/me/onenote/pages/{page_id}/content",
        headers=h,
    )
    if resp.status_code != 200:
        return ""
    soup = BeautifulSoup(resp.content, "lxml")
    return soup.get_text("\n", strip=True)


def sync_onenote_notes() -> int:
    """
    Pull all OneNote pages, match titles/content to accounts,
    store matches as account_notes.
    Returns number of notes synced.
    """
    account_names_ids = db.get_all_account_names_and_aliases()
    if not account_names_ids:
        log.warning("No accounts in DB — seed accounts first")
        return 0

    all_names = [n for n, _ in account_names_ids]
    pages = get_pages()
    synced = 0

    for page in pages:
        title = page.get("title", "")
        page_id = page.get("id", "")
        modified = page.get("lastModifiedDateTime", "")

        # Try to match page title to an account
        account_id = None
        match = process.extractOne(title, all_names, scorer=fuzz.token_sort_ratio)
        if match and match[1] >= 70:
            matched_name = match[0]
            account_id = next(
                (aid for n, aid in account_names_ids if n == matched_name), None
            )

        if not account_id:
            # Also search content for account mentions
            content = get_page_content(page_id)
            for name, aid in account_names_ids:
                if len(name) > 5 and name.lower() in content.lower():
                    account_id = aid
                    break
            if not account_id:
                continue
        else:
            content = get_page_content(page_id)

        note_date = modified[:10] if modified else None
        db.upsert_account_note(
            account_id=account_id,
            source="onenote",
            title=title,
            content=content[:5000],  # cap size
            note_date=note_date,
        )
        synced += 1
        log.debug("Synced OneNote page %r → account %d", title, account_id)

    log.info("OneNote sync: %d pages matched to accounts", synced)
    return synced


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    count = sync_onenote_notes()
    print(f"Synced {count} OneNote pages")
