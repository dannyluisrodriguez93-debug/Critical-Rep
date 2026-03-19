# Account Hub

A personal sales account management tool for tracking hospital accounts, TEG machines, sales data, contacts, and communications — all in one place on your Mac.

---

## Quick Start (Non-Technical — Click-by-Click)

### Step 1 — Download Python

1. Open your web browser and go to **https://www.python.org/downloads/**
2. Click the big yellow **"Download Python 3.x.x"** button
3. Open the downloaded file and follow the installer — click **Continue**, **Continue**, **Install**
4. When asked, check **"Add Python to PATH"** if the option appears

---

### Step 2 — Download the App

If you received this as a ZIP file:
1. Double-click the ZIP to unzip it
2. Move the folder somewhere easy to find, like your **Desktop** or **Documents**

If you cloned it from GitHub, you already have the folder.

---

### Step 3 — Install the App (one time only)

1. Find the file called **`start.command`** inside the app folder
2. **Right-click** it → click **Open** → click **Open** again when macOS asks if you're sure
3. A terminal window opens and installs everything automatically
4. When it says `Account Hub — Starting`, you're ready!

> **Note:** The first time you open `start.command`, macOS may warn you it's "from an unidentified developer." Right-click → Open to bypass this — it's safe.

---

### Step 4 — Open the App

After `start.command` finishes, your browser should open automatically to:

**http://localhost:5000**

If it doesn't open automatically, copy that address and paste it into Chrome, Safari, or Firefox.

---

### Step 5 — Complete the Setup Wizard

When the app opens for the first time, a **Setup Wizard** will appear automatically.

Follow the on-screen steps:
1. **Welcome** — overview of what we'll connect
2. **Google Account** — follow the in-app instructions to connect Gmail + Drive
3. **Salesforce** — optional; skip if you don't use it
4. **Email Filter** — enter the email addresses your report emails come from
5. **Done!**

---

## Starting the App After Setup

From now on, just double-click **`start.command`** and the app starts.

Your browser opens to **http://localhost:5000** automatically.

To stop the app, click the terminal window and press **Control + C**, or just close the window.

---

## Setting Up Google (Detailed Instructions)

The app uses your Google account to:
- **Read report emails** forwarded to Gmail from Outlook
- **Index files** in Google Drive related to your accounts
- **Read Google Sheets** for data you paste there

### Getting Google OAuth Credentials (one time only)

1. Go to **https://console.cloud.google.com/** — sign in with your Google account
2. Click the project dropdown at the top → click **New Project**
   - Name it anything, e.g. `AccountHub` → click **Create**
3. Click **APIs & Services** → **Library**
   - Search for and enable: **Gmail API**, **Google Drive API**, **Google Sheets API**
4. Click **APIs & Services** → **OAuth consent screen**
   - Choose **External** → click Create
   - Fill in App name (e.g. `AccountHub`) and your email → click Save and Continue
   - Skip through the remaining screens by clicking Save and Continue
5. Click **APIs & Services** → **Credentials** → **+ Create Credentials** → **OAuth client ID**
   - Application type: **Web application**
   - Name: anything you like
   - Under **Authorized redirect URIs**, click **+ Add URI** and enter:
     `http://localhost:5000/integrations/google/callback`
   - Click **Create**
6. A popup shows your **Client ID** and **Client Secret** — copy both
7. In Account Hub, go to **Integrations** → paste them in the Google section → click **Save & Connect Google**
8. You'll be taken to Google's sign-in page — log in and click **Allow**
9. You'll be returned to Account Hub and see "Connected as you@gmail.com" ✓

---

## Setting Up Email Forwarding from Outlook

So that your Haemonetics/Tableau report emails arrive in Gmail:

1. Open Outlook in your browser (outlook.office.com)
2. Click the gear icon (⚙️) → **View all Outlook settings**
3. Go to **Mail** → **Forwarding**
4. Check **Enable forwarding**
5. Enter your Gmail address
6. Click **Save**

Now all emails (including report emails) will be forwarded to Gmail, where Account Hub can read them.

---

## Using Google Drive Instead of OneDrive

Since you don't have Azure/OneDrive access, here's how to use Google Drive:

1. Create a folder in **Google Drive** called `Account Files`
2. Inside it, create a subfolder for each hospital account
3. Copy/paste any relevant files (PDFs, spreadsheets, notes) into those subfolders
4. In Account Hub, click **Drive** (top right) to sync — the app will find and link files to accounts

---

## Using Google Sheets for Notes

Google Sheets can serve as a replacement for OneNote:

1. Go to **drive.google.com** and create a new Google Sheet
2. Use columns like: Account Name, Date, Note
3. The app will discover the sheet in Drive sync
4. You can also type notes directly in Account Hub under any account → Notes tab

---

## Adding Your Accounts

1. Click the **+** button at the top of the left sidebar
2. Enter the hospital/account name
3. Optionally add the hospital system name, address, and territory
4. Click **Create Account**

Repeat for each account. You can also add contacts, TEG machines, and notes from each account's page.

---

## Syncing Data

Use the buttons in the top-right corner to sync:

| Button | What it does |
|--------|-------------|
| **Email** | Fetches and parses report emails from Gmail |
| **Notes** | Syncs Apple Notes (Mac only) |
| **Drive** | Syncs Google Drive files |
| **iMsg**  | Syncs iMessage history (Mac only) |
| **SF**    | Syncs Salesforce data |

The app also syncs automatically in the background once a day.

---

## Checking Integration Status

Click the **⚙ Integrations** button (top right) to see:
- Which services are connected (green = connected)
- What needs attention
- Connect/disconnect buttons for each service
- Settings for each integration

---

## Troubleshooting

**The app won't start:**
- Make sure Python is installed (Step 1)
- Try right-clicking `start.command` → Open (not just double-clicking)

**Email sync returns nothing:**
- Make sure your Google account is connected (Integrations page)
- Make sure email forwarding from Outlook is set up
- Check that the report sender addresses match what's in the Email section of Integrations

**"Google not connected" error:**
- Go to Integrations and click **Save & Connect Google** again

**The app loses its data:**
- Data is stored in `account_hub.db` in the app folder. Don't delete this file.

---

## For ChatGPT / Codex (Developer Notes)

This is a Python/Flask web app with a SQLite database and vanilla JS frontend.

- Entry point: `app.py` — run with `python app.py`
- Database: SQLite at `account_hub.db` — schema in `database.py`
- All integration credentials are stored in the `settings` table (not env vars)
- Google OAuth: `integrations/google_auth.py` — standard web OAuth flow
- Email fetching: `integrations/gmail.py` — uses Gmail API via Google OAuth
- Drive sync: `integrations/google_drive.py` — uses Drive API v3
- Microsoft/Azure has been removed; Google replaces it throughout
- Frontend: single-page app in `static/app.js` + `static/style.css` + `templates/dashboard.html`
- No build step needed; all pure HTML/CSS/JS
- The integrations page is at route `/#integrations` and uses `GET /api/integrations/status`
- First-run wizard is triggered when `setup_complete` setting is missing from DB
