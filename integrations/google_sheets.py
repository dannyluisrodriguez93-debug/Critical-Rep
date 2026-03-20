"""
Google Sheets integration.

Finds spreadsheets in Google Drive that match hospital account names,
reads their content, and stores as account_notes (source='google_sheets').

Uses the same OAuth token as Gmail + Drive (single Google login).
"""

import logging
from datetime import datetime

from rapidfuzz import process, fuzz

import database as db
from integrations.google_auth import get_credentials, is_connected

log = logging.getLogger(__name__)

SHEETS_MIME = "application/vnd.google-apps.spreadsheet"
EXCEL_MIME  = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def sync_google_sheets() -> dict:
    """
    Pull all spreadsheets from Drive, fuzzy-match titles to accounts,
    read cell data, and store as account_notes.
    Returns summary dict.
    """
    if not is_connected():
        log.warning("Google Sheets: not connected — skipping")
        return {"synced": 0, "sheets_found": 0, "error": "not_connected"}

    creds = get_credentials()
    if not creds:
        log.error("Google Sheets: could not load credentials")
        return {"synced": 0, "sheets_found": 0, "error": "no_credentials"}

    try:
        from googleapiclient.discovery import build
        drive_svc  = build("drive",  "v3", credentials=creds)
        sheets_svc = build("sheets", "v4", credentials=creds)
    except Exception as e:
        log.error("Google Sheets: could not build service: %s", e)
        return {"synced": 0, "sheets_found": 0, "error": str(e)}

    # Get all spreadsheets from Drive
    sheets_files = _list_spreadsheets(drive_svc)
    log.info("Google Sheets: found %d spreadsheets in Drive", len(sheets_files))

    if not sheets_files:
        return {"synced": 0, "sheets_found": 0}

    # Get account names for fuzzy matching
    account_names_ids = db.get_all_account_names_and_aliases()
    all_names = [n for n, _ in account_names_ids]

    synced = 0
    for sheet_file in sheets_files:
        file_id = sheet_file["id"]
        title   = sheet_file.get("name", "")
        modified = sheet_file.get("modifiedTime", "")

        # Fuzzy-match sheet title to an account
        account_id = _match_account(title, all_names, account_names_ids)

        if not account_id:
            # Try scanning sheet content for account name mentions
            try:
                content_text = _read_sheet_as_text(sheets_svc, file_id, max_rows=50)
                account_id = _match_account_in_text(content_text, account_names_ids)
                if not account_id:
                    log.debug("Google Sheets: no account match for '%s'", title)
                    continue
            except Exception as e:
                log.debug("Google Sheets: skip '%s' — %s", title, e)
                continue

        try:
            content_text = _read_sheet_as_text(sheets_svc, file_id, max_rows=200)
            if not content_text.strip():
                continue

            note_date = modified[:10] if modified else None
            db.upsert_account_note(
                account_id=account_id,
                source="google_sheets",
                title=title,
                content=content_text[:5000],
                note_date=note_date,
            )
            synced += 1
            log.info("Google Sheets: synced '%s' → account %d", title, account_id)
        except Exception as e:
            log.warning("Google Sheets: failed to read '%s': %s", title, e)

    log.info("Google Sheets: synced %d sheets to accounts", synced)
    return {"synced": synced, "sheets_found": len(sheets_files)}


def _list_spreadsheets(drive_svc, max_files: int = 100) -> list[dict]:
    """List Google Sheets files from Drive."""
    query = f"mimeType='{SHEETS_MIME}' and trashed=false"
    try:
        result = drive_svc.files().list(
            q=query,
            fields="files(id, name, modifiedTime, webViewLink)",
            pageSize=max_files,
            orderBy="modifiedTime desc",
        ).execute()
        return result.get("files", [])
    except Exception as e:
        log.error("Google Sheets: Drive file list failed: %s", e)
        return []


def _read_sheet_as_text(sheets_svc, spreadsheet_id: str, max_rows: int = 200) -> str:
    """
    Read the first sheet of a spreadsheet and return as plain text.
    Rows are tab-joined, rows are newline-joined.
    """
    result = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range="A1:Z" + str(max_rows),
        valueRenderOption="FORMATTED_VALUE",
    ).execute()

    rows = result.get("values", [])
    if not rows:
        return ""

    lines = []
    for row in rows:
        line = "\t".join(str(cell) for cell in row if str(cell).strip())
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def _match_account(title: str, all_names: list, account_names_ids: list) -> int | None:
    """Fuzzy-match a sheet title to an account. Returns account_id or None."""
    if not all_names:
        return None
    match = process.extractOne(title, all_names, scorer=fuzz.token_sort_ratio)
    if match and match[1] >= 65:
        matched_name = match[0]
        return next((aid for n, aid in account_names_ids if n == matched_name), None)
    return None


def _match_account_in_text(text: str, account_names_ids: list) -> int | None:
    """Scan text for account name mentions. Returns account_id or None."""
    text_lower = text.lower()
    for name, aid in account_names_ids:
        if len(name) > 8 and name.lower() in text_lower:
            return aid
    return None
