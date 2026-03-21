"""
Gmail integration — fetches report emails via Google OAuth.

Fetches report emails forwarded to your Gmail account from Haemonetics/Tableau.
Uses the same Google OAuth token as Google Drive (single login).

Setup: Connect Google account through the Integrations page.
       Set your report sender filter on the Integrations page too.
"""

import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import database as db
import config
from integrations.google_auth import get_credentials, is_connected

log = logging.getLogger(__name__)


def fetch_report_emails(days_back: int = 7) -> list[dict]:
    """
    Fetch report emails from Gmail.
    Returns list of dicts with id, subject, receivedDateTime, body (HTML).
    Returns empty list (with a log warning) if Google is not connected.
    """
    if not is_connected():
        log.warning("Gmail: Google account not connected — skipping email sync. "
                    "Go to Integrations to connect your Google account.")
        return []

    creds = get_credentials()
    if not creds:
        log.error("Gmail: could not load Google credentials")
        return []

    try:
        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=creds)
    except ImportError:
        log.error("google-api-python-client not installed. Run: pip install google-api-python-client")
        return []
    except Exception as e:
        log.error("Gmail: could not build service: %s", e)
        return []

    # Get the report senders from DB settings (fallback to config)
    senders_setting = db.get_setting("report_senders")
    senders = [s.strip() for s in senders_setting.split(",")] if senders_setting else config.REPORT_SENDERS

    # Always include oracle_sender in the fetch list (may be configured separately)
    oracle_setting = db.get_setting("oracle_sender") or config.ORACLE_SENDER
    for addr in oracle_setting.split(","):
        addr = addr.strip().lower()
        if addr and addr not in [s.lower() for s in senders]:
            senders.append(addr)

    if not senders:
        log.warning("Gmail: no report senders configured — skipping email sync")
        return []

    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y/%m/%d")
    sender_query = " OR ".join(f"from:{s}" for s in senders)
    query = f"({sender_query}) after:{since}"

    messages = []
    try:
        result = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=50,
        ).execute()

        message_ids = result.get("messages", [])
        log.info("Gmail: found %d matching messages", len(message_ids))

        for msg_ref in message_ids:
            msg_id = msg_ref["id"]
            try:
                msg = service.users().messages().get(
                    userId="me",
                    id=msg_id,
                    format="full",
                ).execute()

                parsed = _parse_message(msg)
                if parsed:
                    messages.append(parsed)
            except Exception as e:
                log.warning("Gmail: failed to fetch message %s: %s", msg_id, e)
                continue

    except Exception as e:
        log.error("Gmail: list messages failed: %s", e)

    log.info("Gmail: fetched %d report emails", len(messages))
    return messages


def _parse_message(msg: dict) -> Optional[dict]:
    """Extract subject, sender, date, and HTML body from a Gmail message."""
    try:
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        subject = headers.get("Subject", "")
        sender = headers.get("From", "")
        date_str = headers.get("Date", "")

        # Extract sender email address from "Name <email>" format
        import re
        email_match = re.search(r"<([^>]+)>", sender)
        sender_email = email_match.group(1) if email_match else sender

        # Parse date
        try:
            from email.utils import parsedate_to_datetime
            received_dt = parsedate_to_datetime(date_str)
            received_iso = received_dt.isoformat()
        except Exception:
            received_iso = datetime.now().isoformat()

        # Extract HTML body
        body_html = _extract_html_body(msg.get("payload", {}))

        return {
            "id": msg["id"],
            "subject": subject,
            "receivedDateTime": received_iso,
            "from": {
                "emailAddress": {"address": sender_email, "name": sender}
            },
            "body": {"content": body_html, "contentType": "html"},
        }
    except Exception as e:
        log.warning("Gmail: failed to parse message: %s", e)
        return None


def _extract_html_body(payload: dict) -> str:
    """Recursively extract HTML body from Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {})

    if mime_type == "text/html":
        data = body.get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    if mime_type == "text/plain" and not body.get("data", ""):
        pass  # keep looking for HTML

    # Recurse into parts
    for part in payload.get("parts", []):
        result = _extract_html_body(part)
        if result:
            return result

    # Fallback to plain text
    if mime_type == "text/plain":
        data = body.get("data", "")
        if data:
            text = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            return f"<pre>{text}</pre>"

    return ""
