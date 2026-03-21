"""
Salesforce OAuth 2.0 Web Server Flow integration.

Flow:
  1. User enters Connected App credentials (Consumer Key + Secret) in UI
  2. User clicks "Connect via SSO" → redirected to Salesforce login page
  3. Salesforce redirects to /integrations/salesforce/callback → tokens saved in DB
  4. Subsequent calls use the stored access_token (refreshed automatically)
"""

import json
import logging
import secrets
import urllib.parse
from typing import Optional

import requests

import config
import database as db

log = logging.getLogger(__name__)


def is_configured() -> bool:
    """Return True if Salesforce Connected App credentials (Consumer Key + Secret) are set."""
    cid = db.get_setting("sf_client_id") or config.SF_CLIENT_ID
    csec = db.get_setting("sf_client_secret") or config.SF_CLIENT_SECRET
    return bool(cid and csec)


def is_connected() -> bool:
    """Return True if the user has completed OAuth and has a valid token."""
    token_json = db.get_setting("sf_oauth_token")
    if not token_json:
        return False
    try:
        token = json.loads(token_json)
        return bool(token.get("access_token") or token.get("refresh_token"))
    except Exception:
        return False


def get_connected_user() -> Optional[str]:
    """Return the Salesforce username/email of the connected account, or None."""
    return db.get_setting("sf_connected_user")


def get_instance_url() -> Optional[str]:
    """Return the Salesforce instance URL, or None."""
    return db.get_setting("sf_instance_url")


def get_auth_url() -> Optional[str]:
    """
    Build and return the Salesforce OAuth authorization URL.
    Returns None if Connected App credentials are not configured.
    """
    client_id = db.get_setting("sf_client_id") or config.SF_CLIENT_ID
    if not client_id:
        return None

    domain = db.get_setting("sf_domain") or config.SF_DOMAIN or "login"
    base_url = _build_base_url(domain)

    state = secrets.token_urlsafe(32)
    db.set_setting("sf_oauth_state", state)

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": config.SF_REDIRECT_URI,
        "scope": "api refresh_token offline_access",
        "state": state,
    }
    auth_url = f"{base_url}/services/oauth2/authorize?" + urllib.parse.urlencode(params)
    log.info("Salesforce OAuth URL built for domain: %s", domain)
    return auth_url


def handle_callback(code: str, state: str = None) -> tuple[bool, str]:
    """
    Exchange the OAuth authorization code for tokens and save them.
    Returns (success, message).
    """
    client_id = db.get_setting("sf_client_id") or config.SF_CLIENT_ID
    client_secret = db.get_setting("sf_client_secret") or config.SF_CLIENT_SECRET

    if not client_id or not client_secret:
        return False, "Salesforce Connected App credentials not configured. Please add Consumer Key and Secret first."

    # Validate state to prevent CSRF
    saved_state = db.get_setting("sf_oauth_state")
    if saved_state and state and saved_state != state:
        return False, "OAuth state mismatch — please try connecting again."

    domain = db.get_setting("sf_domain") or config.SF_DOMAIN or "login"
    base_url = _build_base_url(domain)
    token_url = f"{base_url}/services/oauth2/token"

    try:
        resp = requests.post(token_url, data={
            "grant_type":    "authorization_code",
            "code":          code,
            "client_id":     client_id,
            "client_secret": client_secret,
            "redirect_uri":  config.SF_REDIRECT_URI,
        }, timeout=15)
        resp.raise_for_status()
        token_data = resp.json()

        if "error" in token_data:
            return False, f"Salesforce error: {token_data.get('error_description', token_data['error'])}"

        # Persist tokens
        db.set_setting("sf_oauth_token", json.dumps({
            "access_token":  token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "instance_url":  token_data.get("instance_url"),
            "token_type":    token_data.get("token_type"),
        }))
        instance_url = token_data.get("instance_url", "")
        db.set_setting("sf_instance_url", instance_url)
        db.set_setting("sf_oauth_state", None)

        # Fetch and store user info
        user_info = _fetch_user_info(token_data["access_token"], instance_url)
        if user_info:
            db.set_setting("sf_connected_user", user_info)

        log.info("Salesforce OAuth complete — instance: %s, user: %s", instance_url, user_info)
        return True, f"Connected as {user_info or instance_url}"

    except Exception as e:
        log.error("Salesforce OAuth callback failed: %s", e)
        return False, f"Connection failed: {e}"


def get_access_token() -> Optional[str]:
    """
    Return a valid Salesforce access token, refreshing if expired.
    Returns None if not connected.
    """
    token_json = db.get_setting("sf_oauth_token")
    if not token_json:
        return None

    try:
        token_data = json.loads(token_json)
        access_token = token_data.get("access_token")
        if access_token:
            return access_token
        return _refresh(token_data)
    except Exception as e:
        log.error("Failed to get Salesforce access token: %s", e)
        return None


def _refresh(token_data: dict) -> Optional[str]:
    """Refresh the access token using the stored refresh token."""
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        return None

    client_id = db.get_setting("sf_client_id") or config.SF_CLIENT_ID
    client_secret = db.get_setting("sf_client_secret") or config.SF_CLIENT_SECRET
    domain = db.get_setting("sf_domain") or config.SF_DOMAIN or "login"
    base_url = _build_base_url(domain)

    try:
        resp = requests.post(f"{base_url}/services/oauth2/token", data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     client_id,
            "client_secret": client_secret,
        }, timeout=15)
        resp.raise_for_status()
        new_data = resp.json()

        if "access_token" in new_data:
            token_data["access_token"] = new_data["access_token"]
            if "instance_url" in new_data:
                token_data["instance_url"] = new_data["instance_url"]
                db.set_setting("sf_instance_url", new_data["instance_url"])
            db.set_setting("sf_oauth_token", json.dumps(token_data))
            log.info("Salesforce access token refreshed")
            return new_data["access_token"]
    except Exception as e:
        log.error("Salesforce token refresh failed: %s", e)

    return None


def disconnect():
    """Remove stored Salesforce OAuth tokens and credentials."""
    for key in ("sf_oauth_token", "sf_instance_url", "sf_oauth_state", "sf_connected_user"):
        db.set_setting(key, None)
    log.info("Salesforce OAuth account disconnected")


# ── Internal helpers ────────────────────────────────────────────────────────────

def _build_base_url(domain: str) -> str:
    """Build the Salesforce base URL from a domain setting."""
    # If it's just "login" or "test", expand it
    if domain in ("login", "test"):
        return f"https://{domain}.salesforce.com"
    # If it already looks like a full hostname (e.g. "mycompany.my.salesforce.com")
    if "." in domain:
        return f"https://{domain}"
    # Default: treat as subdomain
    return f"https://{domain}.salesforce.com"


def _fetch_user_info(access_token: str, instance_url: str) -> Optional[str]:
    try:
        resp = requests.get(
            f"{instance_url}/services/oauth2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        info = resp.json()
        return info.get("email") or info.get("preferred_username") or info.get("name")
    except Exception:
        return None
