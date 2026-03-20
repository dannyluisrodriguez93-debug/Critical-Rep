"""
Apple Notes sync via AppleScript (macOS only).
Reads notes containing account names and stores content in account_notes.
Works silently in the background — no UI interaction required.
"""

import logging
import subprocess
import sys
from html import unescape

from rapidfuzz import process, fuzz

import database as db

log = logging.getLogger(__name__)


def _run_applescript(script: str) -> str | None:
    """Execute an AppleScript and return stdout, or None on failure."""
    if sys.platform != "darwin":
        log.warning("Apple Notes sync is only available on macOS")
        return None
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.error("AppleScript error: %s", result.stderr.strip())
            return None
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        log.error("AppleScript timed out")
        return None
    except FileNotFoundError:
        log.error("osascript not found — are you on macOS?")
        return None


def get_all_note_titles() -> list[str]:
    """Get list of all note titles from Apple Notes."""
    script = """
    tell application "Notes"
        set noteNames to {}
        repeat with n in every note
            set end of noteNames to name of n
        end repeat
        return noteNames
    end tell
    """
    raw = _run_applescript(script)
    if not raw:
        return []
    # AppleScript returns comma-separated list
    return [t.strip() for t in raw.split(",") if t.strip()]


def get_note_content(title: str) -> str:
    """Get the plain text content of a note by title."""
    safe_title = title.replace('"', '\\"')
    script = f"""
    tell application "Notes"
        set matchNote to first note whose name is "{safe_title}"
        return body of matchNote
    end tell
    """
    raw = _run_applescript(script)
    if not raw:
        return ""
    # Apple Notes body is HTML — strip tags
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(raw, "lxml").get_text("\n", strip=True)
    except Exception:
        return unescape(raw)


def get_all_note_titles_fast() -> list[str]:
    """
    Fetch only note titles in one fast AppleScript call.
    Much faster than fetching bodies — used to pre-filter before fetching content.
    """
    script = """
    tell application "Notes"
        set output to ""
        repeat with n in every note
            set output to output & "|||" & name of n
        end repeat
        return output
    end tell
    """
    raw = _run_applescript(script)
    if not raw:
        return []
    return [t.strip() for t in raw.split("|||") if t.strip()]


def get_note_content_by_index(idx: int) -> str:
    """Fetch content of note at 1-based index (faster than searching by name)."""
    script = f"""
    tell application "Notes"
        set n to item {idx} of every note
        return body of n
    end tell
    """
    raw = _run_applescript(script)
    if not raw:
        return ""
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(raw, "lxml").get_text("\n", strip=True)
    except Exception:
        return unescape(raw)


def get_all_notes_bulk() -> list[dict]:
    """
    Fetch all notes titles first, then only fetch body content for notes
    whose titles match account names. This avoids timeout on large collections.
    Returns list of {title, content} dicts for ALL notes (content empty for non-matched,
    but sync_apple_notes will only call this for matched titles).
    """
    # Fast title-only pass first
    titles = get_all_note_titles_fast()
    if not titles:
        return []

    notes = []
    for i, title in enumerate(titles, start=1):
        notes.append({"title": title, "content": "", "_index": i})
    return notes


def sync_apple_notes() -> int:
    """
    Pull all Apple Notes, fuzzy-match titles to accounts, fetch content only
    for matched notes, then store as account_notes (source='apple_notes').

    Strategy: titles-first approach avoids timeout on large Notes libraries.
    Returns number of notes synced.
    """
    if sys.platform != "darwin":
        log.info("Skipping Apple Notes sync — not on macOS")
        return 0

    account_names_ids = db.get_all_account_names_and_aliases()
    if not account_names_ids:
        log.warning("No accounts seeded — run setup_accounts.py first")
        return 0

    all_names = [n for n, _ in account_names_ids]

    # Step 1: fetch titles only (fast — no body content)
    note_stubs = get_all_notes_bulk()
    log.info("Apple Notes: found %d notes, matching titles to accounts...", len(note_stubs))

    synced = 0
    for note in note_stubs:
        title = note["title"]
        note_index = note.get("_index")

        # Match title to an account
        account_id = None
        match = process.extractOne(title, all_names, scorer=fuzz.token_sort_ratio)
        if match and match[1] >= 60:
            matched_name = match[0]
            account_id = next(
                (aid for n, aid in account_names_ids if n == matched_name), None
            )

        if not account_id:
            continue

        # Step 2: fetch content only for matched notes
        content = ""
        if note_index:
            content = get_note_content_by_index(note_index)
        if not content:
            content = get_note_content(title)

        db.upsert_account_note(
            account_id=account_id,
            source="apple_notes",
            title=title,
            content=content[:5000],
            note_date=None,
        )
        synced += 1
        log.info("Apple Notes: synced %r → account %d", title, account_id)

    log.info("Apple Notes sync: %d notes matched to accounts", synced)
    return synced


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    count = sync_apple_notes()
    print(f"Synced {count} Apple Notes")
