# Account Hub

A personal sales account management tool for tracking hospital accounts, TEG machines, sales data, contacts, and communications — all in one place on your Mac.

---

## Quick Start — Click-by-Click for Non-Technical Users

### Step 1 — Install Python (one time only)

1. Open Safari or Chrome and go to **https://www.python.org/downloads/**
2. Click the big yellow **"Download Python 3.x.x"** button
3. Open the downloaded file → click **Continue**, **Continue**, **Install**
4. Close the installer when it says "The installation was successful"

---

### Step 2 — Get the App Files

If you received a ZIP file:
1. Double-click the ZIP to unzip it
2. Move the resulting folder somewhere easy to find — your **Desktop** works fine

---

### Step 3 — Start the App (first time)

1. Open the app folder
2. Find the file called **`start.command`**
3. **Right-click it → Open → Open** (macOS will ask the first time because it's a downloaded file — clicking Open is safe)
4. A terminal window opens and installs everything automatically
5. When you see `App is starting…` your browser should open to the app

> After the first time, you can just double-click `start.command` to launch — no right-click needed.

---

### Step 4 — Open the App in Your Browser

The app opens at: **http://localhost:5000**

If your browser doesn't open automatically, copy that address and paste it into Chrome, Safari, or Firefox.

---

### Step 5 — Follow the Setup Wizard

When the app opens for the first time, a **Setup Wizard** appears automatically. Follow the steps:

1. **Welcome** — overview of the setup
2. **Connect Google** — follow the in-app instructions to connect Gmail and Drive
3. **Salesforce** — optional; skip if you don't have access
4. **Email Filter** — enter the sender address(es) your report emails come from
5. **Done** — start using the app

You can revisit any of these settings any time by clicking **⚙ Integrations** in the top-right corner.

---

## Starting the App After Setup

Double-click **`start.command`** → the app starts and your browser opens.

To stop the app: press **Control+C** in the terminal window, or just close the terminal window.

---

## Connecting Google (Step-by-Step)

The app uses Google for two things:
- **Gmail** — reads your report emails (forwarded from Outlook) to parse sales data automatically
- **Google Drive** — finds files in your Drive that relate to your accounts and shows them in the Files tab

### Getting Google Credentials (one time only)

1. Open **https://console.cloud.google.com/** — sign in with your Google account
2. Click the project dropdown → **New Project** → name it anything (e.g. `AccountHub`) → **Create**
3. In the left menu, click **APIs & Services → Library**
   - Search **Gmail API** → click it → **Enable**
   - Search **Google Drive API** → click it → **Enable**
4. Click **APIs & Services → OAuth consent screen**
   - Choose **External** → click **Create**
   - Fill in **App name** (e.g. `AccountHub`) and your email address → **Save and Continue**
   - Click **Save and Continue** on the next two screens too → **Back to Dashboard**
5. Click **APIs & Services → Credentials** → **+ Create Credentials** → **OAuth client ID**
   - Application type: **Web application**
   - Name: anything you like (e.g. `AccountHub`)
   - Under **Authorized redirect URIs**, click **+ Add URI** and type exactly:
     `http://localhost:5000/integrations/google/callback`
   - Click **Create**
6. A popup shows your **Client ID** and **Client Secret** — keep this window open
7. In Account Hub, click **⚙ Integrations** (top right)
8. Paste the Client ID and Client Secret into the Google section → **Save & Connect Google**
9. You'll be taken to Google's sign-in page — log in with the Gmail address you want to use → **Allow**
10. You'll be returned to Account Hub and see "Connected as you@gmail.com" ✅

---

## Forwarding Outlook Emails to Gmail

Your Haemonetics/Tableau report emails arrive in Outlook. To get them into Gmail for the app to read:

1. Open Outlook in your browser (outlook.office.com)
2. Click the gear icon ⚙️ → **View all Outlook settings**
3. Go to **Mail → Forwarding**
4. Check **Enable forwarding**
5. Enter your Gmail address → **Save**

From now on, all emails (including report emails) will be forwarded to Gmail automatically.

---

## Using Google Drive for Files

1. Go to **drive.google.com** and create a folder called `Account Files`
2. Inside it, create a subfolder for each hospital account (name each subfolder with the account name)
3. Copy any relevant files (PDFs, spreadsheets, etc.) into those subfolders
4. In Account Hub, click **Drive** (top right) to sync — files will appear in each account's **Files** tab

> **Note:** Google Sheets files you save in Drive will also appear in the Files tab. The app doesn't read their content — it just links them so you can click to open them directly.

---

## Adding Your Accounts

1. Click the **+** button at the top of the left sidebar
2. Enter the hospital/account name
3. Optionally add the hospital system, address, and territory
4. Click **Create Account**

Repeat for each account. Add contacts, TEG machines, and notes from each account's page.

---

## Syncing Data

Use the buttons in the top-right corner:

| Button | What it does |
|--------|-------------|
| **Email** | Reads report emails from Gmail and parses sales data |
| **Notes** | Syncs Apple Notes (Mac only) |
| **Drive** | Finds and links files from Google Drive |
| **iMsg**  | Syncs iMessage history (Mac only) |
| **SF**    | Syncs Salesforce contacts and opportunities |

The app also syncs automatically in the background every day.

---

## Checking Connections

Click **⚙ Integrations** (top right) to see:
- Which services are connected (**green** = connected, **gray** = not connected)
- Connect/disconnect buttons for each service
- Where to enter credentials
- What each integration does

---

## Troubleshooting

**The app won't start**
→ Make sure Python is installed (Step 1 above)
→ Right-click `start.command` → Open (not just double-click, first time only)

**Email sync returns no data**
→ Check the Integrations page — Google must be connected (green)
→ Check that Outlook forwarding is set up (see above)
→ Confirm the sender address in the Email Parser section of Integrations matches your report email sender

**"Google not connected" message**
→ Go to Integrations and click **Save & Connect Google** to go through the connection process again

**App data is lost / database is empty**
→ The data lives in `account_hub.db` in the app folder — do not delete this file

---

## For Developers / ChatGPT Codex

**Stack:** Python 3 / Flask / SQLite / vanilla JS (no build step)

**Key files:**
- `app.py` — Flask routes; entry point (`python app.py`)
- `database.py` — SQLite schema and all query helpers
- `config.py` — configuration (loads from `.env` and DB settings)
- `ingestion/email_fetcher.py` — fetches emails via Gmail API, parses HTML tables
- `ingestion/scheduler.py` — APScheduler background jobs
- `integrations/google_auth.py` — Google OAuth 2.0 web flow
- `integrations/gmail.py` — Gmail API email fetching
- `integrations/google_drive.py` — Google Drive API file sync
- `integrations/salesforce.py` — Salesforce API (optional)
- `integrations/apple_notes.py` — AppleScript-based Notes sync (Mac only)
- `integrations/imessage.py` — SQLite-based iMessage sync (Mac only)
- `static/app.js` — Single-page app logic
- `static/style.css` — Dark theme stylesheet
- `templates/dashboard.html` — Main HTML shell

**Architecture notes:**
- All integration credentials are stored in the `settings` DB table, not `.env` files
- The Integrations page (`/api/integrations/status`) drives UI connect/disconnect flows
- First-run wizard is triggered when `setup_complete` is absent from the settings table
- Google OAuth callback: `/integrations/google/callback`
- Drive files are stored in the `drive_files` table (renamed from legacy `onedrive_files`)
- Microsoft/Azure/OneDrive/OneNote have been fully removed — Google replaces all of it
- iMessage and Apple Notes gracefully no-op on non-Mac systems
- All syncs degrade gracefully (return `{ok: False, reason: "…"}`) when not connected

**To set up for development:**
```bash
pip install -r requirements.txt
python app.py
# Open http://localhost:5000
```
