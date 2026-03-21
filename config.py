import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# ── App ────────────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
DB_PATH    = os.getenv("DB_PATH", str(BASE_DIR / "account_hub.db"))
PORT       = int(os.getenv("PORT", 5000))

# ── Google OAuth (filled in via UI — stored in DB settings) ───────────────────
# Users set these through the Integrations page, not this file.
# Advanced: you can also set them as env vars as a fallback.
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", f"http://localhost:{int(os.getenv('PORT', 5000))}/integrations/google/callback")

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

# ── Salesforce OAuth (filled in via UI — stored in DB settings) ───────────────
# OAuth 2.0 Web Server Flow — requires a Salesforce Connected App.
# Users enter Consumer Key + Secret through the Integrations page.
SF_CLIENT_ID      = os.getenv("SF_CLIENT_ID", "")
SF_CLIENT_SECRET  = os.getenv("SF_CLIENT_SECRET", "")
SF_REDIRECT_URI   = os.getenv("SF_REDIRECT_URI", f"http://localhost:{int(os.getenv('PORT', 5000))}/integrations/salesforce/callback")
SF_DOMAIN         = os.getenv("SF_DOMAIN", "login")

# Legacy username/password auth (fallback if OAuth not configured)
SF_USERNAME       = os.getenv("SF_USERNAME", "")
SF_PASSWORD       = os.getenv("SF_PASSWORD", "")
SF_SECURITY_TOKEN = os.getenv("SF_SECURITY_TOKEN", "")

# ── Email report parsing ───────────────────────────────────────────────────────
# Comma-separated list of allowed sender addresses.
# Tableau sends daily sales/revenue reports; Oracle sends supply order confirmations.
# Override via REPORT_SENDERS env var or the "report_senders" DB setting (Integrations page).
REPORT_SENDERS = [
    s.strip()
    for s in os.getenv(
        "REPORT_SENDERS",
        "tableau-no-reply@haemonetics.com,oracle-no-reply@haemonetics.com",
    ).split(",")
]

# Oracle order notification sender — can be set independently if Oracle uses a
# different address from the comma-separated REPORT_SENDERS list above.
ORACLE_SENDER = os.getenv("ORACLE_SENDER", "oracle-no-reply@haemonetics.com")

# ── Alert thresholds ──────────────────────────────────────────────────────────
MTD_ALERT_PCT     = 60   # flag if MTD % of target is below this
REORDER_ALERT_DAYS = 20  # flag if no orders from account in this many days
