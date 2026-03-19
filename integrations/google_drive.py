"""
Google Drive integration — replaces OneDrive.

Searches the user's Google Drive for files related to each account.
Uses the same OAuth token as Gmail (single Google login covers both).

Setup: Connect Google account through the Integrations page.
"""

import logging
import re
from typing import Optional

import database as db
from integrations.google_auth import get_credentials, is_connected
from rapidfuzz import fuzz

log = logging.getLogger(__name__)

FUZZY_THRESHOLD = 65

RELEVANT_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
    "text/plain",
    "text/csv",
}


def sync_google_drive_files() -> dict:
    """
    Main sync entry point.  Returns summary dict.
    Gracefully returns an error dict if Google is not connected.
    """
    if not is_connected():
        return {
            "ok": False,
            "reason": "Google account not connected. Go to Integrations to connect.",
            "files_synced": 0,
        }

    creds = get_credentials()
    if not creds:
        return {"ok": False, "reason": "Could not load Google credentials.", "files_synced": 0}

    try:
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=creds)
    except ImportError:
        return {"ok": False, "reason": "google-api-python-client not installed.", "files_synced": 0}
    except Exception as e:
        return {"ok": False, "reason": str(e), "files_synced": 0}

    account_names = db.get_all_account_names_and_aliases()
    if not account_names:
        return {"ok": True, "files_synced": 0, "reason": "No accounts in database yet."}

    files_synced = 0
    processed_ids: set[str] = set()

    # Search Drive for files matching account names (top 20 accounts)
    top_accounts = account_names[:20]
    seen_queries: set[str] = set()

    for acct_name, acct_id in top_accounts:
        words = [w for w in acct_name.split() if len(w) > 3]
        if not words:
            continue
        query = " ".join(words[:2])
        if query in seen_queries:
            continue
        seen_queries.add(query)

        try:
            results = service.files().list(
                q=f"name contains '{query}' and trashed=false",
                fields="files(id,name,webViewLink,size,modifiedTime,mimeType,parents)",
                pageSize=25,
            ).execute()

            for item in results.get("files", []):
                file_id = item.get("id")
                if file_id in processed_ids:
                    continue
                mime = item.get("mimeType", "")
                if mime not in RELEVANT_MIME_TYPES and not mime.startswith("application/vnd.google-apps"):
                    continue

                name = item.get("name", "")
                stem = name.rsplit(".", 1)[0] if "." in name else name
                stem = re.sub(r"[_\-]", " ", stem)

                best_score = 0
                best_match_id = None
                for an, aid in account_names:
                    score = fuzz.token_set_ratio(stem.lower(), an.lower())
                    if score > best_score:
                        best_score = score
                        best_match_id = aid

                if best_score >= FUZZY_THRESHOLD and best_match_id:
                    db.upsert_onedrive_file(
                        account_id=best_match_id,
                        file_id=file_id,
                        name=name,
                        web_url=item.get("webViewLink"),
                        size=item.get("size"),
                        modified_at=item.get("modifiedTime"),
                        mime_type=mime,
                    )
                    processed_ids.add(file_id)
                    files_synced += 1

        except Exception as e:
            log.warning("Drive search failed for query %r: %s", query, e)
            continue

    log.info("Google Drive sync complete: %d files stored", files_synced)
    return {"ok": True, "files_synced": files_synced}
