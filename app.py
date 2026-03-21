"""
Account Hub — Flask application.
Run with: python app.py   (or double-click start.command on Mac)
Then open: http://localhost:5000
"""

import json
import logging
import os
import threading
from datetime import datetime

# Allow Google OAuth over plain http://localhost (safe for local dev)
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
# Allow Google to return a superset of requested scopes (happens with include_granted_scopes)
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from flask import Flask, jsonify, redirect, render_template, request, abort, url_for

import config
import database as db
from ingestion.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
# Also write to /tmp/account_hub.log so OAuth errors are always capturable
_file_handler = logging.FileHandler("/tmp/account_hub.log")
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s"))
logging.getLogger().addHandler(_file_handler)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY


# ── Bootstrap ─────────────────────────────────────────────────────────────────

db.init_db()
start_scheduler()


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("dashboard.html")


# ── Settings API ──────────────────────────────────────────────────────────────

MASKED_KEYS = {"google_client_secret", "sf_password", "sf_security_token", "google_token"}


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    """Return all settings; secrets are masked."""
    raw = db.get_all_settings()
    safe = {}
    for k, v in raw.items():
        if k in MASKED_KEYS:
            safe[k] = "••••••••" if v else ""
        else:
            safe[k] = v
    return jsonify(safe)


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    """Save one or more settings. Blank strings clear the key."""
    body = request.get_json(force=True)
    allowed = {
        "google_client_id", "google_client_secret",
        "sf_username", "sf_password", "sf_security_token", "sf_domain",
        "report_senders",
        "setup_complete",
        "alert_mtd_pct", "alert_reorder_days",
    }
    saved = []
    for key, value in body.items():
        if key not in allowed:
            continue
        v = str(value).strip() if value is not None else None
        db.set_setting(key, v if v else None)
        saved.append(key)
    return jsonify({"ok": True, "saved": saved})


# ── Integrations status ────────────────────────────────────────────────────────

@app.route("/api/integrations/status")
def api_integrations_status():
    """Return connection status for all integrations."""
    from integrations.google_auth import is_configured, is_connected, get_connected_email

    google_connected = is_connected()
    google_email = get_connected_email() if google_connected else None

    # Salesforce status
    sf_user = db.get_setting("sf_username") or config.SF_USERNAME
    sf_pass = db.get_setting("sf_password") or config.SF_PASSWORD
    sf_token = db.get_setting("sf_security_token") or config.SF_SECURITY_TOKEN
    sf_configured = bool(sf_user and sf_pass)

    # Report senders
    report_senders = db.get_setting("report_senders") or ",".join(config.REPORT_SENDERS)

    # Email log stats
    conn = db.get_conn()
    email_count = conn.execute("SELECT COUNT(*) as n FROM email_log WHERE status='ok'").fetchone()["n"]
    conn.close()

    # iMessage / Apple Notes — Mac-only
    import platform
    is_mac = platform.system() == "Darwin"

    google_client_id = db.get_setting("google_client_id") or config.GOOGLE_CLIENT_ID

    return jsonify({
        "google": {
            "connected":  google_connected,
            "configured": is_configured(),
            "client_id":  google_client_id or "",
            "email":      google_email,
            "covers":     ["Gmail", "Google Drive", "Google Sheets", "Google Contacts"],
        },
        "salesforce": {
            "configured": sf_configured,
            "username":   sf_user,
        },
        "email_parser": {
            "active":         True,
            "emails_parsed":  email_count,
            "report_senders": report_senders,
        },
        "imessage": {
            "available": is_mac,
            "platform_note": "iMessage sync requires a Mac running this app locally.",
        },
        "apple_notes": {
            "available": is_mac,
            "platform_note": "Apple Notes sync requires a Mac running this app locally.",
        },
        "setup_complete": bool(db.get_setting("setup_complete")),
    })


# ── Google OAuth routes ────────────────────────────────────────────────────────

@app.route("/integrations/google/start")
def google_oauth_start():
    from integrations.google_auth import get_auth_url
    url = get_auth_url()
    if not url:
        return redirect("/#integrations?google_error=not_configured")
    return redirect(url)


@app.route("/integrations/google/callback")
def google_oauth_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        log.warning("Google OAuth error: %s", error)
        return redirect("/#integrations?google_error=" + error)

    if not code:
        return redirect("/#integrations?google_error=no_code")

    from integrations.google_auth import handle_callback
    success, message = handle_callback(authorization_response=request.url, state=state)

    if success:
        return redirect("/#integrations?google_connected=1")
    else:
        return redirect(f"/#integrations?google_error={message}")


@app.route("/integrations/google/disconnect", methods=["POST"])
def google_disconnect():
    from integrations.google_auth import disconnect
    disconnect()
    return jsonify({"ok": True})


@app.route("/integrations/google/test")
def google_test():
    """Verify the stored token works by fetching the connected user's profile."""
    from integrations.google_auth import get_credentials, get_connected_email
    creds = get_credentials()
    if not creds:
        return jsonify({"ok": False, "message": "Not connected — no stored token."})
    try:
        from googleapiclient.discovery import build
        service = build("oauth2", "v2", credentials=creds)
        info = service.userinfo().get().execute()
        return jsonify({
            "ok": True,
            "email": info.get("email"),
            "name": info.get("name"),
            "picture": info.get("picture"),
        })
    except Exception as e:
        log.error("Google token test failed: %s", e, exc_info=True)
        return jsonify({"ok": False, "message": f"Token test failed: {e}"})


# ── Salesforce test ────────────────────────────────────────────────────────────

@app.route("/integrations/salesforce/test", methods=["POST"])
def salesforce_test():
    body = request.get_json(force=True)
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    token    = body.get("security_token", "").strip()
    domain   = body.get("domain", "login").strip()

    if not username or not password:
        return jsonify({"ok": False, "message": "Username and password are required."})

    try:
        from simple_salesforce import Salesforce, SalesforceAuthenticationFailed
        sf = Salesforce(
            username=username,
            password=password,
            security_token=token,
            domain=domain,
        )
        # Quick query to verify access
        result = sf.query("SELECT Id, Name FROM User WHERE IsActive=true LIMIT 1")
        # Save credentials on success
        db.set_setting("sf_username", username)
        db.set_setting("sf_password", password)
        db.set_setting("sf_security_token", token)
        db.set_setting("sf_domain", domain)
        return jsonify({"ok": True, "message": f"Connected to Salesforce as {username}"})
    except Exception as e:
        return jsonify({"ok": False, "message": f"Connection failed: {e}"})


@app.route("/integrations/salesforce/disconnect", methods=["POST"])
def salesforce_disconnect():
    for key in ("sf_username", "sf_password", "sf_security_token"):
        db.set_setting(key, None)
    return jsonify({"ok": True})


# ── Dashboard API ─────────────────────────────────────────────────────────────

@app.route("/api/dashboard")
def api_dashboard():
    data = db.get_dashboard_data()
    return jsonify(data)


@app.route("/api/alerts")
def api_alerts():
    return jsonify(db.compute_alerts())


@app.route("/api/unmatched")
def api_unmatched():
    return jsonify(db.get_unmatched())


@app.route("/api/unmatched/resolve", methods=["POST"])
def api_resolve_unmatched():
    body = request.get_json(force=True)
    raw_name = body.get("raw_name")
    account_id = body.get("account_id")
    if not raw_name or not account_id:
        abort(400, "raw_name and account_id required")
    db.resolve_unmatched(raw_name, int(account_id))
    return jsonify({"ok": True})


# ── Accounts API ──────────────────────────────────────────────────────────────

@app.route("/api/accounts")
def api_accounts():
    accounts = db.get_all_accounts()
    summary = {r["id"]: r for r in db.get_all_accounts_sales_summary()}
    for a in accounts:
        s = summary.get(a["id"], {})
        a["revenue_30d"] = s.get("revenue_30d", 0)
        a["last_order"] = s.get("last_order")
        a["teg_count"] = db.get_account_teg_count(a["id"])
    return jsonify(accounts)


@app.route("/api/accounts/<int:account_id>")
def api_account_detail(account_id: int):
    acct = db.get_account(account_id)
    if not acct:
        abort(404)

    days = int(request.args.get("days", 90))
    sales = db.get_account_sales_summary(account_id, days=days)
    cartridge_summary = db.get_cartridge_summary(account_id, days=days)
    recent_orders = db.get_recent_orders(account_id, limit=15)
    targets = db.get_latest_targets(account_id)
    contacts = db.get_contacts(account_id)
    notes = db.get_account_notes(account_id)
    tegs = db.get_tegs(account_id)
    comms = db.get_account_communications(account_id, limit=50)
    comm_stats = db.get_comm_stats_per_contact(account_id)
    files = db.get_drive_files(account_id)

    return jsonify({
        "account": acct,
        "sales_summary": sales,
        "cartridge_summary": cartridge_summary,
        "recent_orders": recent_orders,
        "targets": targets,
        "contacts": contacts,
        "notes": notes,
        "tegs": tegs,
        "comms": comms,
        "comm_stats": comm_stats,
        "files": files,
    })


@app.route("/api/accounts", methods=["POST"])
def api_create_account():
    body = request.get_json(force=True)
    name = body.get("name", "").strip()
    if not name:
        abort(400, "name required")
    system_id = body.get("system_id")
    if body.get("system_name") and not system_id:
        system_id = db.upsert_system(body["system_name"])
    account_id = db.upsert_account(
        name=name,
        system_id=system_id,
        aliases=body.get("aliases", []),
        address=body.get("address"),
        city=body.get("city"),
        state=body.get("state"),
        territory=body.get("territory"),
    )
    return jsonify({"id": account_id, "name": name}), 201


@app.route("/api/accounts/<int:account_id>", methods=["PATCH"])
def api_update_account(account_id: int):
    acct = db.get_account(account_id)
    if not acct:
        abort(404)
    body = request.get_json(force=True)
    conn = db.get_conn()
    allowed = {"notes", "territory", "address", "city", "state"}
    fields = {k: v for k, v in body.items() if k in allowed}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(
            f"UPDATE accounts SET {sets}, updated_at=datetime('now') WHERE id=?",
            (*fields.values(), account_id),
        )
        conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ── Contacts API ──────────────────────────────────────────────────────────────

@app.route("/api/accounts/<int:account_id>/contacts", methods=["GET"])
def api_get_contacts(account_id: int):
    return jsonify(db.get_contacts(account_id))


@app.route("/api/accounts/<int:account_id>/contacts", methods=["POST"])
def api_add_contact(account_id: int):
    if not db.get_account(account_id):
        abort(404)
    body = request.get_json(force=True)
    name = body.get("name", "").strip()
    if not name:
        abort(400, "name required")
    contact_id = db.add_contact(
        account_id=account_id,
        name=name,
        role=body.get("role"),
        phone=body.get("phone"),
        email=body.get("email"),
        notes=body.get("notes"),
        imessage_handle=body.get("imessage_handle"),
    )
    return jsonify({"id": contact_id}), 201


@app.route("/api/contacts/<int:contact_id>", methods=["PATCH"])
def api_update_contact(contact_id: int):
    body = request.get_json(force=True)
    db.update_contact(contact_id, **body)
    return jsonify({"ok": True})


@app.route("/api/contacts/<int:contact_id>", methods=["DELETE"])
def api_delete_contact(contact_id: int):
    db.delete_contact(contact_id)
    return jsonify({"ok": True})


# ── Notes API ─────────────────────────────────────────────────────────────────

@app.route("/api/accounts/<int:account_id>/notes", methods=["POST"])
def api_add_note(account_id: int):
    if not db.get_account(account_id):
        abort(404)
    body = request.get_json(force=True)
    content = body.get("content", "").strip()
    if not content:
        abort(400, "content required")
    note_id = db.add_manual_note(account_id, content, title=body.get("title"))
    return jsonify({"id": note_id}), 201


# ── TEG Machine API ───────────────────────────────────────────────────────────

@app.route("/api/accounts/<int:account_id>/tegs", methods=["GET"])
def api_get_tegs(account_id: int):
    return jsonify(db.get_tegs(account_id))


@app.route("/api/accounts/<int:account_id>/tegs", methods=["POST"])
def api_add_teg(account_id: int):
    if not db.get_account(account_id):
        abort(404)
    body = request.get_json(force=True)
    location = body.get("location", "").strip()
    if not location:
        abort(400, "location required")
    teg_id = db.add_teg(
        account_id=account_id,
        location=location,
        department=body.get("department"),
        serial_number=body.get("serial_number"),
        model=body.get("model"),
        notes=body.get("notes"),
    )
    if body.get("cartridge_types"):
        db.set_teg_cartridges(teg_id, body["cartridge_types"])
    return jsonify({"id": teg_id}), 201


@app.route("/api/tegs/<int:teg_id>", methods=["PATCH"])
def api_update_teg(teg_id: int):
    body = request.get_json(force=True)
    cartridge_types = body.pop("cartridge_types", None)
    db.update_teg(teg_id, **body)
    if cartridge_types is not None:
        db.set_teg_cartridges(teg_id, cartridge_types)
    return jsonify({"ok": True})


@app.route("/api/tegs/<int:teg_id>", methods=["DELETE"])
def api_delete_teg(teg_id: int):
    db.delete_teg(teg_id)
    return jsonify({"ok": True})


# ── Communications API ────────────────────────────────────────────────────────

@app.route("/api/accounts/<int:account_id>/comms", methods=["GET"])
def api_get_comms(account_id: int):
    comms = db.get_account_communications(account_id)
    stats = db.get_comm_stats_per_contact(account_id)
    return jsonify({"comms": comms, "stats": stats})


@app.route("/api/accounts/<int:account_id>/comms", methods=["POST"])
def api_log_comm(account_id: int):
    if not db.get_account(account_id):
        abort(404)
    body = request.get_json(force=True)
    comm_type = body.get("type", "").strip()
    occurred_at = body.get("occurred_at") or datetime.now().isoformat()
    if not comm_type:
        abort(400, "type required")
    comm_id = db.log_communication(
        account_id=account_id,
        comm_type=comm_type,
        occurred_at=occurred_at,
        contact_id=body.get("contact_id"),
        notes=body.get("notes"),
        duration_sec=body.get("duration_sec"),
        message_preview=body.get("message_preview"),
        is_from_me=body.get("is_from_me", 1),
    )
    return jsonify({"id": comm_id}), 201


@app.route("/api/comms/<int:comm_id>", methods=["DELETE"])
def api_delete_comm(comm_id: int):
    conn = db.get_conn()
    conn.execute("DELETE FROM communications WHERE id=?", (comm_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ── Sync API ──────────────────────────────────────────────────────────────────

@app.route("/api/sync/email", methods=["POST"])
def api_sync_email():
    body = request.get_json(force=True, silent=True) or {}
    days_back = int(body.get("days_back", 7))

    def _run():
        from ingestion.email_fetcher import run_ingestion
        run_ingestion(days_back=days_back)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": f"Syncing last {days_back} days of emails..."})


@app.route("/api/sync/notes", methods=["POST"])
def api_sync_notes():
    def _run():
        import platform
        if platform.system() == "Darwin":
            try:
                from integrations.apple_notes import sync_apple_notes
                sync_apple_notes()
            except Exception as e:
                log.warning("Apple Notes sync failed: %s", e)
        else:
            log.info("Apple Notes sync skipped — not on Mac")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Syncing notes from Apple Notes..."})


@app.route("/api/sync/salesforce", methods=["POST"])
def api_sync_sf():
    def _run():
        try:
            from integrations.salesforce import run_sf_sync
            run_sf_sync()
        except Exception as e:
            log.warning("Salesforce sync failed: %s", e)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Syncing Salesforce contacts, opportunities, and shipments..."})


@app.route("/api/sync/imessage", methods=["POST"])
def api_sync_imessage():
    def _run():
        import platform
        if platform.system() == "Darwin":
            try:
                from integrations.imessage import sync_imessage
                result = sync_imessage()
                log.info("iMessage sync: %s", result)
            except Exception as e:
                log.warning("iMessage sync failed: %s", e)
        else:
            log.info("iMessage sync skipped — not on Mac")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Syncing iMessage communication history..."})


@app.route("/api/sync/macos-contacts", methods=["POST"])
def api_sync_macos_contacts():
    def _run():
        import platform
        if platform.system() == "Darwin":
            try:
                from integrations.macos_contacts import sync_macos_contacts
                result = sync_macos_contacts()
                log.info("macOS Contacts sync: %s", result)
            except Exception as e:
                log.warning("macOS Contacts sync failed: %s", e)
        else:
            log.info("macOS Contacts sync skipped — not on Mac")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Syncing macOS Contacts..."})


@app.route("/api/sync/drive", methods=["POST"])
def api_sync_drive():
    def _run():
        try:
            from integrations.google_drive import sync_google_drive_files
            result = sync_google_drive_files()
            log.info("Google Drive sync: %s", result)
        except Exception as e:
            log.warning("Google Drive sync failed: %s", e)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Syncing Google Drive files..."})


@app.route("/api/sync/sheets", methods=["POST"])
def api_sync_sheets():
    def _run():
        try:
            from integrations.google_sheets import sync_google_sheets
            result = sync_google_sheets()
            log.info("Google Sheets sync: %s", result)
        except Exception as e:
            log.warning("Google Sheets sync failed: %s", e)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Syncing Google Sheets data..."})


@app.route("/api/sync/contacts", methods=["POST"])
def api_sync_contacts():
    def _run():
        # Sync Google Contacts
        try:
            from integrations.google_contacts import sync_google_contacts
            result = sync_google_contacts()
            log.info("Google Contacts sync: %s", result)
        except Exception as e:
            log.warning("Google Contacts sync failed: %s", e)
        # Sync macOS/iOS Contacts
        import platform
        if platform.system() == "Darwin":
            try:
                from integrations.macos_contacts import sync_macos_contacts
                result = sync_macos_contacts()
                log.info("macOS Contacts sync: %s", result)
            except Exception as e:
                log.warning("macOS Contacts sync failed: %s", e)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Syncing contacts (Google + iOS)..."})


@app.route("/api/accounts/geocode", methods=["POST"])
def api_geocode_accounts():
    """Geocode all accounts that lack lat/lng. Runs synchronously (fast with known coords)."""
    try:
        from utils.geocode import geocode_all_accounts
        n = geocode_all_accounts(use_nominatim=True)
        return jsonify({"ok": True, "updated": n})
    except Exception as e:
        log.error("Geocode failed: %s", e, exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/accounts/map")
def api_accounts_map():
    """Return all accounts with lat/lng for the map."""
    accounts = db.get_all_accounts_with_coords()
    return jsonify(accounts)


@app.route("/api/accounts/<int:account_id>/synopsis")
def api_account_synopsis(account_id: int):
    """Return the latest update synopsis for an account."""
    if not db.get_account(account_id):
        abort(404)
    synopsis = db.get_account_synopsis(account_id)
    return jsonify(synopsis or {})


@app.route("/api/sync/status")
def api_sync_status():
    conn = db.get_conn()
    rows = conn.execute("""
        SELECT subject, parsed_at, rows_inserted, status
        FROM email_log ORDER BY parsed_at DESC LIMIT 10
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ── Hospital Systems API ──────────────────────────────────────────────────────

@app.route("/api/systems")
def api_systems():
    return jsonify(db.get_all_systems())


@app.route("/api/systems", methods=["POST"])
def api_create_system():
    body = request.get_json(force=True)
    name = body.get("name", "").strip()
    if not name:
        abort(400, "name required")
    system_id = db.upsert_system(name, aliases=body.get("aliases", []))
    return jsonify({"id": system_id, "name": name}), 201


# ── Products API ──────────────────────────────────────────────────────────────

@app.route("/api/products")
def api_products():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM products ORDER BY prod_line, description"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ── Teardown ──────────────────────────────────────────────────────────────────

import atexit
atexit.register(stop_scheduler)


if __name__ == "__main__":
    print(f"\n{'='*50}")
    print("  Account Hub — Starting")
    print(f"  Open your browser to: http://localhost:{config.PORT}")
    print(f"{'='*50}\n")
    app.run(host="0.0.0.0", port=config.PORT, debug=False)
