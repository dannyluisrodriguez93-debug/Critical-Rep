"""
iMessage integration — reads the local macOS Messages database to populate
the communication log with text/iMessage history for known contacts.

Requires macOS + Full Disk Access granted to the Python process or Terminal.
The Messages database is at ~/Library/Messages/chat.db (read-only).

Apple's datetime epoch starts 2001-01-01 (not Unix 1970-01-01).
Offset = 978307200 seconds.
"""

import logging
import os
import platform
import sqlite3
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import database as db

log = logging.getLogger(__name__)

APPLE_EPOCH_OFFSET = 978307200      # seconds between 1970-01-01 and 2001-01-01
APPLE_EPOCH_NANO   = 1_000_000_000  # iMessage stores timestamps in nanoseconds (macOS 10.13+)
MESSAGES_DB        = Path.home() / "Library" / "Messages" / "chat.db"
LOOKBACK_DAYS      = 90             # how far back to pull messages on full sync


def _is_available() -> bool:
    return platform.system() == "Darwin" and MESSAGES_DB.exists()


def _apple_ts_to_iso(ts: int) -> str | None:
    """Convert Apple Core Data timestamp (nanoseconds since 2001-01-01) to ISO string."""
    if not ts:
        return None
    try:
        # Timestamps ≥ 1e15 are in nanoseconds; otherwise seconds
        if ts > 1_000_000_000_000:
            secs = ts / APPLE_EPOCH_NANO
        else:
            secs = float(ts)
        unix_ts = secs + APPLE_EPOCH_OFFSET
        return datetime.utcfromtimestamp(unix_ts).isoformat()
    except Exception:
        return None


def _normalize_phone(phone: str) -> str:
    """Strip all non-digit characters for phone comparison."""
    return "".join(c for c in (phone or "") if c.isdigit())


def _build_handle_map(conn: sqlite3.Connection) -> dict[str, str]:
    """
    Returns {normalized_id: original_id} for all handles.
    handle.id is a phone number (+15551234567) or email address.
    """
    rows = conn.execute("SELECT id FROM handle").fetchall()
    handle_map = {}
    for r in rows:
        h_id = r[0]
        normalized = _normalize_phone(h_id) if h_id.startswith("+") else h_id.lower()
        handle_map[normalized] = h_id
    return handle_map


def _match_contacts_to_handles(handle_map: dict) -> list[dict]:
    """
    Cross-reference all contacts (with phone or imessage_handle) against
    the iMessage handle map.  Returns list of {contact, handles: [raw_ids]}.
    """
    all_contacts_by_account = {}
    conn_app = db.get_conn()
    contacts = conn_app.execute(
        "SELECT c.*, a.id as acct_id FROM contacts c JOIN accounts a ON c.account_id = a.id"
    ).fetchall()
    conn_app.close()

    matched = []
    for c in contacts:
        c = dict(c)
        candidate_handles = []

        # Try imessage_handle first (explicit mapping)
        if c.get("imessage_handle"):
            norm = _normalize_phone(c["imessage_handle"]) if c["imessage_handle"].startswith("+") \
                   else c["imessage_handle"].lower()
            if norm in handle_map:
                candidate_handles.append(handle_map[norm])

        # Try phone number
        if c.get("phone"):
            norm = _normalize_phone(c["phone"])
            if len(norm) >= 10:
                # Match last 10 digits (strip country code from both sides)
                for h_norm, h_raw in handle_map.items():
                    if h_norm.endswith(norm[-10:]) or norm.endswith(h_norm[-10:]):
                        if h_raw not in candidate_handles:
                            candidate_handles.append(h_raw)

        # Try email
        if c.get("email"):
            email_lower = c["email"].lower()
            if email_lower in handle_map:
                h_raw = handle_map[email_lower]
                if h_raw not in candidate_handles:
                    candidate_handles.append(h_raw)

        if candidate_handles:
            matched.append({"contact": c, "handles": candidate_handles})

    return matched


def sync_imessage(days_back: int = LOOKBACK_DAYS) -> dict:
    """
    Pull iMessage history for all matched contacts and store in communications table.
    Returns summary dict.
    """
    if not _is_available():
        return {"ok": False, "reason": "macOS Messages database not found or not macOS"}

    # Copy the DB to a temp location to avoid lock conflicts with Messages.app
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        shutil.copy2(str(MESSAGES_DB), tmp.name)
        return _sync_from_db(tmp.name, days_back)
    except PermissionError:
        return {"ok": False, "reason": "Permission denied — grant Full Disk Access to Terminal"}
    except Exception as e:
        log.exception("iMessage sync failed")
        return {"ok": False, "reason": str(e)}
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def _sync_from_db(db_path: str, days_back: int) -> dict:
    msg_conn = sqlite3.connect(db_path)
    msg_conn.row_factory = sqlite3.Row

    handle_map = _build_handle_map(msg_conn)
    matched_contacts = _match_contacts_to_handles(handle_map)

    if not matched_contacts:
        msg_conn.close()
        return {"ok": True, "contacts_matched": 0, "messages_synced": 0}

    # Cutoff in Apple epoch nanoseconds
    cutoff_dt = datetime.utcnow() - timedelta(days=days_back)
    cutoff_ts = (cutoff_dt.timestamp() - APPLE_EPOCH_OFFSET) * APPLE_EPOCH_NANO

    total_synced = 0

    for item in matched_contacts:
        contact = item["contact"]
        account_id = contact["acct_id"]
        contact_id = contact["id"]

        for handle_id in item["handles"]:
            # Find handle row id
            h_row = msg_conn.execute(
                "SELECT ROWID FROM handle WHERE id=?", (handle_id,)
            ).fetchone()
            if not h_row:
                continue

            handle_rowid = h_row[0]

            # Get messages for this handle
            messages = msg_conn.execute("""
                SELECT m.ROWID, m.text, m.date, m.is_from_me,
                       c.guid as chat_guid
                FROM message m
                JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
                JOIN chat c ON c.ROWID = cmj.chat_id
                JOIN chat_handle_join chj ON chj.chat_id = c.ROWID
                WHERE chj.handle_id = ?
                  AND m.date > ?
                  AND m.text IS NOT NULL
                  AND m.text != ''
                ORDER BY m.date DESC
                LIMIT 500
            """, (handle_rowid, cutoff_ts)).fetchall()

            for msg in messages:
                occurred_at = _apple_ts_to_iso(msg["date"])
                if not occurred_at:
                    continue

                thread_id = msg["chat_guid"] or ""
                preview = (msg["text"] or "")[:300]
                is_from_me = int(msg["is_from_me"] or 0)

                # Deduplicate: skip if already stored
                if db.imessage_already_synced(thread_id + str(msg["ROWID"]), occurred_at):
                    continue

                db.log_communication(
                    account_id=account_id,
                    comm_type="imessage",
                    occurred_at=occurred_at,
                    contact_id=contact_id,
                    thread_id=thread_id + str(msg["ROWID"]),
                    message_preview=preview,
                    is_from_me=is_from_me,
                )
                total_synced += 1

    msg_conn.close()
    log.info("iMessage sync complete: %d contacts matched, %d messages synced",
             len(matched_contacts), total_synced)
    return {
        "ok": True,
        "contacts_matched": len(matched_contacts),
        "messages_synced": total_synced,
    }


def get_thread_messages(contact_phone: str, limit: int = 50) -> list[dict]:
    """
    Pull the most recent messages for a single contact's thread.
    Used for a future 'view thread' feature.
    """
    if not _is_available():
        return []

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        shutil.copy2(str(MESSAGES_DB), tmp.name)
        msg_conn = sqlite3.connect(tmp.name)
        msg_conn.row_factory = sqlite3.Row

        norm = _normalize_phone(contact_phone)
        if not norm:
            return []

        handle = msg_conn.execute(
            "SELECT ROWID FROM handle WHERE replace(replace(replace(id,'+',''),'-',''),' ','') LIKE ?",
            (f"%{norm[-10:]}",)
        ).fetchone()

        if not handle:
            msg_conn.close()
            return []

        rows = msg_conn.execute("""
            SELECT m.text, m.date, m.is_from_me, m.ROWID
            FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            JOIN chat c ON c.ROWID = cmj.chat_id
            JOIN chat_handle_join chj ON chj.chat_id = c.ROWID
            WHERE chj.handle_id = ? AND m.text IS NOT NULL AND m.text != ''
            ORDER BY m.date DESC
            LIMIT ?
        """, (handle["ROWID"], limit)).fetchall()

        msg_conn.close()
        return [
            {
                "text": r["text"],
                "occurred_at": _apple_ts_to_iso(r["date"]),
                "is_from_me": bool(r["is_from_me"]),
            }
            for r in rows
        ]
    except Exception:
        log.exception("get_thread_messages failed")
        return []
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
