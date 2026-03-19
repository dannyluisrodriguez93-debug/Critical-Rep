"""
Microsoft authentication via MSAL.
One OAuth login covers both Outlook email and OneNote.

First run: opens a browser/device-code flow so you log in once.
Subsequent runs: silently refresh from saved token cache.
"""

import json
import logging
import sys
from pathlib import Path

import msal

import config

log = logging.getLogger(__name__)

_app: msal.PublicClientApplication | None = None


def _get_app() -> msal.PublicClientApplication:
    global _app
    if _app is None:
        cache = msal.SerializableTokenCache()
        if config.TOKEN_PATH.exists():
            cache.deserialize(config.TOKEN_PATH.read_text())
        _app = msal.PublicClientApplication(
            client_id=config.MS_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{config.MS_TENANT_ID}",
            token_cache=cache,
        )
    return _app


def _save_cache(app: msal.PublicClientApplication):
    if app.token_cache.has_state_changed:
        config.TOKEN_PATH.write_text(app.token_cache.serialize())


def get_access_token(scopes: list[str] = None) -> str | None:
    scopes = scopes or config.MS_SCOPES

    if not config.MS_CLIENT_ID:
        log.error(
            "MS_CLIENT_ID not set. Copy .env.example to .env and add your Azure app client ID."
        )
        return None

    app = _get_app()

    # Try silent token refresh first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(scopes, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(app)
            return result["access_token"]

    # Interactive login via device code flow (works headless too)
    log.info("No cached token — starting device code flow...")
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        log.error("Failed to initiate device flow: %s", flow)
        return None

    # Print the URL + code prominently
    print("\n" + "="*60)
    print("MICROSOFT LOGIN REQUIRED")
    print("="*60)
    print(flow["message"])
    print("="*60 + "\n")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        _save_cache(app)
        log.info("Microsoft login successful — token cached for future runs")
        return result["access_token"]

    log.error("Login failed: %s", result.get("error_description", result))
    return None


def logout():
    """Clear cached token."""
    if config.TOKEN_PATH.exists():
        config.TOKEN_PATH.unlink()
    global _app
    _app = None
    print("Logged out — token cleared.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1 and sys.argv[1] == "logout":
        logout()
    else:
        token = get_access_token()
        if token:
            print(f"\nAuthenticated successfully. Token preview: {token[:20]}...")
        else:
            print("\nAuthentication failed.")
