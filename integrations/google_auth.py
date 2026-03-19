"""
Google OAuth 2.0 integration.

One login covers Gmail + Google Drive + Google Sheets.
Credentials (Client ID + Secret) are stored in the DB settings table
and set by the user through the Integrations page in the UI.

OAuth flow:
  1. User visits /integrations/google/start  → redirected to Google consent screen
  2. Google redirects back to /integrations/google/callback  → token saved in DB
  3. Subsequent calls: token is refreshed silently from the DB
"""

import json
import logging
from typing import Optional

import config
import database as db

log = logging.getLogger(__name__)


def _get_credentials() -> tuple[str, str]:
    """Return (client_id, client_secret) — DB settings take priority over env vars."""
    client_id = db.get_setting("google_client_id") or config.GOOGLE_CLIENT_ID
    client_secret = db.get_setting("google_client_secret") or config.GOOGLE_CLIENT_SECRET
    return client_id, client_secret


def is_configured() -> bool:
    """Return True if Google OAuth credentials have been entered."""
    cid, csec = _get_credentials()
    return bool(cid and csec)


def is_connected() -> bool:
    """Return True if the user has completed the OAuth flow and has a valid token."""
    token_json = db.get_setting("google_token")
    if not token_json:
        return False
    try:
        token = json.loads(token_json)
        return bool(token.get("access_token") or token.get("refresh_token"))
    except Exception:
        return False


def get_connected_email() -> Optional[str]:
    """Return the Gmail address of the connected account, or None."""
    return db.get_setting("google_email")


def get_auth_url() -> Optional[str]:
    """
    Build and return the Google OAuth authorization URL.
    Returns None if credentials are not configured.
    """
    client_id, client_secret = _get_credentials()
    if not client_id:
        return None

    try:
        from google_auth_oauthlib.flow import Flow
        flow = _build_flow(client_id, client_secret)
        auth_url, _state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        # Save state for CSRF protection
        db.set_setting("google_oauth_state", _state)
        return auth_url
    except ImportError:
        log.error("google-auth-oauthlib not installed. Run: pip install google-auth-oauthlib")
        return None
    except Exception as e:
        log.error("Failed to build Google auth URL: %s", e)
        return None


def handle_callback(code: str, state: str = None) -> tuple[bool, str]:
    """
    Exchange the authorization code for tokens and save them.
    Returns (success, message).
    """
    client_id, client_secret = _get_credentials()
    if not client_id or not client_secret:
        return False, "Google credentials not configured. Please add Client ID and Secret first."

    try:
        from google_auth_oauthlib.flow import Flow
        flow = _build_flow(client_id, client_secret)
        flow.fetch_token(code=code)
        creds = flow.credentials

        # Save token
        token_data = {
            "token":         creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri":     creds.token_uri,
            "client_id":     creds.client_id,
            "client_secret": creds.client_secret,
            "scopes":        list(creds.scopes or []),
        }
        db.set_setting("google_token", json.dumps(token_data))

        # Fetch the user's email to display in the UI
        email = _fetch_user_email(creds)
        if email:
            db.set_setting("google_email", email)

        log.info("Google OAuth complete — connected as %s", email)
        return True, f"Connected as {email or 'unknown'}"

    except Exception as e:
        log.error("Google OAuth callback failed: %s", e)
        return False, f"Connection failed: {e}"


def get_credentials():
    """
    Return a valid google.oauth2.credentials.Credentials object.
    Refreshes the token automatically if needed.
    Returns None if not connected.
    """
    token_json = db.get_setting("google_token")
    if not token_json:
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        data = json.loads(token_json)
        creds = Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes"),
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Save refreshed token
            data["token"] = creds.token
            db.set_setting("google_token", json.dumps(data))

        return creds

    except Exception as e:
        log.error("Failed to load/refresh Google credentials: %s", e)
        return None


def disconnect():
    """Remove stored Google credentials."""
    db.set_setting("google_token", None)
    db.set_setting("google_email", None)
    db.set_setting("google_oauth_state", None)
    log.info("Google account disconnected")


# ── Internal helpers ───────────────────────────────────────────────────────────

def _build_flow(client_id: str, client_secret: str):
    from google_auth_oauthlib.flow import Flow
    client_config = {
        "web": {
            "client_id":                  client_id,
            "client_secret":              client_secret,
            "auth_uri":                   "https://accounts.google.com/o/oauth2/auth",
            "token_uri":                  "https://oauth2.googleapis.com/token",
            "redirect_uris":              [config.GOOGLE_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=config.GOOGLE_SCOPES,
        redirect_uri=config.GOOGLE_REDIRECT_URI,
    )
    return flow


def _fetch_user_email(creds) -> Optional[str]:
    try:
        from googleapiclient.discovery import build
        service = build("oauth2", "v2", credentials=creds)
        info = service.userinfo().get().execute()
        return info.get("email")
    except Exception:
        # Try Gmail profile as fallback
        try:
            from googleapiclient.discovery import build
            gmail = build("gmail", "v1", credentials=creds)
            profile = gmail.users().getProfile(userId="me").execute()
            return profile.get("emailAddress")
        except Exception:
            return None
