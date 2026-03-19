"""
OneDrive integration — uses Microsoft Graph API to discover and index
files that are relevant to each account.

Strategy:
  1. List all files in the user's OneDrive that mention any account name
     (search-based, fuzzy matched).
  2. Also check a configurable root folder (ONEDRIVE_FOLDER config var)
     for structured account subfolders.
  3. Store file references (not content) per account for display in the UI.

Authentication re-uses the existing ms_auth token (Mail.Read + Files.Read scopes).
"""

import logging
import re
from typing import Optional

import requests

import config
import database as db
from integrations.ms_auth import get_access_token
from rapidfuzz import fuzz

log = logging.getLogger(__name__)

GRAPH_BASE  = "https://graph.microsoft.com/v1.0"
# Additional scope needed for OneDrive
DRIVE_SCOPE = ["Files.Read", "offline_access"]

# Configurable root folder name (set ONEDRIVE_FOLDER in .env)
ONEDRIVE_FOLDER = getattr(config, "ONEDRIVE_FOLDER", "Account Files")

# Fuzzy match threshold for file → account association
FUZZY_THRESHOLD = 65

# File types we care about (others are ignored)
RELEVANT_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".txt", ".csv", ".msg", ".eml", ".one",
}


def _headers() -> Optional[dict]:
    token = get_access_token(DRIVE_SCOPE)
    if not token:
        log.warning("OneDrive: could not get access token")
        return None
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _get(url: str, params: dict = None) -> Optional[dict]:
    headers = _headers()
    if not headers:
        return None
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log.error("OneDrive GET %s failed: %s", url, e)
        return None


def _search_drive(query: str, max_results: int = 50) -> list[dict]:
    """Search OneDrive for files matching a query string."""
    url = f"{GRAPH_BASE}/me/drive/root/search(q='{query}')"
    data = _get(url, params={"$top": max_results,
                              "$select": "id,name,webUrl,size,lastModifiedDateTime,file,parentReference"})
    if not data:
        return []
    return data.get("value", [])


def _list_folder(folder_path: str) -> list[dict]:
    """List files in a specific OneDrive folder path."""
    encoded = folder_path.replace(" ", "%20")
    url = f"{GRAPH_BASE}/me/drive/root:/{encoded}:/children"
    data = _get(url, params={"$select": "id,name,webUrl,size,lastModifiedDateTime,file",
                              "$top": 200})
    if not data:
        return []
    return data.get("value", [])


def _list_folder_children(folder_path: str) -> list[dict]:
    """Recursively list subfolders and their contents (2 levels deep)."""
    items = _list_folder(folder_path)
    results = []
    for item in items:
        if "file" in item:
            results.append(item)
        elif "folder" in item:
            subfolder = f"{folder_path}/{item['name']}"
            results.extend(_list_folder(subfolder))
    return results


def _is_relevant_file(name: str) -> bool:
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext in RELEVANT_EXTENSIONS


def _match_file_to_account(filename: str, parent_name: str,
                             account_names: list[tuple[str, int]]) -> Optional[int]:
    """
    Return account_id if filename or parent folder name fuzzy-matches an account.
    Checks parent folder name first (stronger signal), then filename.
    """
    # Remove extension and split on underscores/dashes for cleaner matching
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    stem = re.sub(r"[_\-]", " ", stem)

    candidates = [
        (parent_name, 80),   # parent folder requires stronger match
        (stem, FUZZY_THRESHOLD),
    ]

    for text, threshold in candidates:
        if not text:
            continue
        best_score = 0
        best_id = None
        for acct_name, acct_id in account_names:
            score = fuzz.token_set_ratio(text.lower(), acct_name.lower())
            if score > best_score:
                best_score = score
                best_id = acct_id
        if best_score >= threshold:
            return best_id
    return None


def sync_onedrive_files() -> dict:
    """
    Main sync entry point. Returns summary dict.
    """
    headers = _headers()
    if not headers:
        return {"ok": False, "reason": "Could not authenticate with Microsoft Graph"}

    account_names = db.get_all_account_names_and_aliases()
    if not account_names:
        return {"ok": True, "files_synced": 0, "reason": "No accounts in database"}

    files_synced = 0
    processed_ids: set[str] = set()

    # ── Strategy 1: Search the configured account files folder ─────────
    try:
        folder_items = _list_folder_children(ONEDRIVE_FOLDER)
        for item in folder_items:
            if not _is_relevant_file(item.get("name", "")):
                continue
            file_id = item.get("id")
            if file_id in processed_ids:
                continue

            parent = (item.get("parentReference") or {}).get("name", "")
            account_id = _match_file_to_account(
                item["name"], parent, account_names
            )
            if account_id:
                _store_file(account_id, item)
                processed_ids.add(file_id)
                files_synced += 1
    except Exception:
        log.exception("OneDrive folder listing failed")

    # ── Strategy 2: Search by account name for large accounts ──────────
    # Only search top-20 account names to avoid hammering the API
    top_accounts = account_names[:20]
    seen_queries: set[str] = set()

    for acct_name, acct_id in top_accounts:
        # Use first meaningful word(s) to avoid overly broad searches
        words = [w for w in acct_name.split() if len(w) > 3]
        if not words:
            continue
        query = " ".join(words[:2])
        if query in seen_queries:
            continue
        seen_queries.add(query)

        try:
            search_results = _search_drive(query, max_results=25)
            for item in search_results:
                if not item.get("file"):
                    continue
                if not _is_relevant_file(item.get("name", "")):
                    continue
                file_id = item.get("id")
                if file_id in processed_ids:
                    continue

                parent = (item.get("parentReference") or {}).get("name", "")
                matched_id = _match_file_to_account(
                    item["name"], parent, account_names
                )
                if matched_id:
                    _store_file(matched_id, item)
                    processed_ids.add(file_id)
                    files_synced += 1
        except Exception:
            log.exception("OneDrive search failed for query: %s", query)
            continue

    log.info("OneDrive sync complete: %d files stored", files_synced)
    return {"ok": True, "files_synced": files_synced}


def _store_file(account_id: int, item: dict):
    """Persist a OneDrive file reference to the database."""
    mime = (item.get("file") or {}).get("mimeType", "")
    db.upsert_onedrive_file(
        account_id=account_id,
        file_id=item["id"],
        name=item.get("name", "Unknown"),
        web_url=item.get("webUrl"),
        size=item.get("size"),
        modified_at=item.get("lastModifiedDateTime"),
        mime_type=mime,
    )
