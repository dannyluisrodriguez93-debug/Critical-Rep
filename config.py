import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
TOKEN_PATH = BASE_DIR / ".ms_token.json"

MS_CLIENT_ID = os.getenv("MS_CLIENT_ID", "")
MS_TENANT_ID = os.getenv("MS_TENANT_ID", "common")
MS_SCOPES = ["Mail.Read", "Notes.Read.All", "offline_access"]

SF_USERNAME = os.getenv("SF_USERNAME", "")
SF_PASSWORD = os.getenv("SF_PASSWORD", "")
SF_SECURITY_TOKEN = os.getenv("SF_SECURITY_TOKEN", "")
SF_DOMAIN = os.getenv("SF_DOMAIN", "login")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "account_hub.db"))
PORT = int(os.getenv("PORT", 5000))

REPORT_SENDERS = [
    s.strip()
    for s in os.getenv("REPORT_SENDERS", "tableau-no-reply@haemonetics.com").split(",")
]

# Alert thresholds
MTD_ALERT_PCT = 60       # flag if MTD % of target is below this
REORDER_ALERT_DAYS = 20  # flag if no orders from account in this many days
