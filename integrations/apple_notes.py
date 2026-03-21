"""
Apple Notes sync via AppleScript (macOS only).
Reads notes, intelligently matches content to hospital accounts,
splits multi-hospital notes, and stores organized summaries.
"""

import logging
import re
import subprocess
import sys
from html import unescape

from rapidfuzz import process, fuzz

import database as db

log = logging.getLogger(__name__)


# ── AppleScript helpers ──────────────────────────────────────────────────────

def _run_applescript(script: str, timeout: int = 30) -> str | None:
    """Execute an AppleScript and return stdout, or None on failure."""
    if sys.platform != "darwin":
        log.warning("Apple Notes sync is only available on macOS")
        return None
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            log.error("AppleScript error: %s", result.stderr.strip())
            return None
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        log.error("AppleScript timed out after %ds", timeout)
        return None
    except FileNotFoundError:
        log.error("osascript not found — are you on macOS?")
        return None


def get_all_note_titles_fast() -> list[str]:
    """Fetch only note titles in one fast AppleScript call."""
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
    """Fetch content of note at 1-based index."""
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


# ── Hospital alias / keyword matching ────────────────────────────────────────

# Short aliases that are too ambiguous on their own
_SHORT_ALIASES = {"hca", "ccf", "bh", "jmh", "smh"}

# Keywords that map to specific hospitals (used for content scanning)
_CONTENT_KEYWORDS = {
    "jackson main":     "Jackson Memorial Hospital",
    "jackson memorial": "Jackson Memorial Hospital",
    "jackson south":    "Jackson South Community Hospital",
    "jmh":              "Jackson Memorial Hospital",
    "baptist main":     "Baptist Hospital of Miami",
    "baptist hospital": "Baptist Hospital of Miami",
    "south miami":      "South Miami Hospital",
    "boca raton":       "Boca Raton Regional Hospital",
    "boca":             "Boca Raton Regional Hospital",
    "bethesda":         "Baptist Health Bethesda Hospital",
    "memorial regional":"Memorial Regional Medical Center",
    "memorial healthcare": "Memorial Regional Medical Center",
    "broward general":  "Broward General Hospital",
    "broward health north": "Broward Health North",
    "holy cross":       "Holy Cross Hospital",
    "cleveland clinic": "Cleveland Clinic Florida",
    "ccf":              "Cleveland Clinic Florida",
    "weston":           "Cleveland Clinic Florida",
    "northwest":        "Northwest Medical Center",
    "westside":         "Westside Regional Medical Center",
    "jfk":              "JFK Medical Center",
    "lawnwood":         "Lawnwood Regional Medical Center",
    "delray":           "Delray Medical Center",
    "st. mary":         "St. Mary's Medical Center",
    "st mary":          "St. Mary's Medical Center",
    "jupiter":          "Jupiter Medical Center",
    "mercy":            "Mercy Hospital",
    "kendall":          "South Miami Hospital",  # Kendall = South Miami area
}


def _build_name_to_id(account_names_ids: list[tuple[str, int]]) -> dict[str, int]:
    """Build a name→account_id lookup from the DB list."""
    lookup = {}
    for name, aid in account_names_ids:
        lookup[name] = aid
    return lookup


def _find_hospitals_in_text(text: str, name_to_id: dict[str, int],
                            alias_lookup: list[tuple[str, int]]) -> list[int]:
    """
    Scan text for hospital mentions. Returns list of account IDs found.
    Uses content keywords first (most specific), then alias lookup.
    """
    text_lower = text.lower()
    found_ids = set()

    # Phase 1: Content keywords (most specific — "jackson south" before "jackson")
    for keyword, canonical_name in sorted(_CONTENT_KEYWORDS.items(),
                                           key=lambda x: len(x[0]), reverse=True):
        if keyword in text_lower:
            aid = name_to_id.get(canonical_name)
            if aid:
                found_ids.add(aid)

    # Phase 2: Alias substring match (longer aliases first)
    for alias_lower, aid in alias_lookup:
        if len(alias_lower) < 5:
            continue  # skip very short aliases
        if alias_lower in text_lower and aid not in found_ids:
            found_ids.add(aid)

    return list(found_ids)


# ── Content splitting & summarization ────────────────────────────────────────

def _split_note_into_hospital_sections(
    content: str,
    alias_lookup: list[tuple[str, int]],
    name_to_id: dict[str, int],
    id_to_name: dict[int, str],
) -> dict[int, list[str]]:
    """
    Split a note's content into per-hospital sections.
    Scans through lines — when a hospital is mentioned, attributes subsequent
    lines to that hospital until another hospital is detected.
    Returns {account_id: [lines...]}.
    """
    lines = content.split('\n')
    sections: dict[int, list[str]] = {}
    current_account = None

    # Build sorted keyword list (longest first for priority)
    keyword_items = sorted(_CONTENT_KEYWORDS.items(), key=lambda x: len(x[0]), reverse=True)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        line_lower = stripped.lower()

        # Check if this line mentions a hospital
        detected_id = None
        for keyword, canonical_name in keyword_items:
            if keyword in line_lower:
                aid = name_to_id.get(canonical_name)
                if aid:
                    detected_id = aid
                    break

        if not detected_id:
            for alias_lower, aid in alias_lookup:
                if len(alias_lower) >= 5 and alias_lower in line_lower:
                    detected_id = aid
                    break

        if detected_id:
            current_account = detected_id
            # If the line is JUST a hospital name/header, skip adding it as content
            if len(stripped) < 40 and any(kw in line_lower for kw, _ in keyword_items):
                continue

        if current_account and stripped:
            sections.setdefault(current_account, []).append(stripped)

    return sections


def _summarize_lines(lines: list[str], max_chars: int = 2000) -> str:
    """
    Clean up raw note lines into an organized summary.
    - Deduplicates lines
    - Formats as bullet points
    - Trims to max_chars
    """
    seen = set()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Deduplicate
        norm = stripped.lower()
        if norm in seen:
            continue
        seen.add(norm)
        # Ensure bullet format
        if not stripped.startswith(('-', '*', '•')):
            stripped = f"- {stripped}"
        cleaned.append(stripped)

    summary = '\n'.join(cleaned)
    if len(summary) > max_chars:
        summary = summary[:max_chars - 3] + "..."
    return summary


# ── Main sync ────────────────────────────────────────────────────────────────

def sync_apple_notes() -> int:
    """
    Pull Apple Notes, intelligently match content to hospital accounts,
    split multi-hospital notes, and store organized summaries.

    Strategy:
    1. Fetch all note titles (fast)
    2. For notes whose title fuzzy-matches OR contains a hospital name,
       fetch the full content
    3. Scan content for ALL hospital mentions
    4. Split multi-hospital notes into per-hospital sections
    5. Store organized bullet-point summaries per hospital

    Returns number of note entries synced.
    """
    if sys.platform != "darwin":
        log.info("Skipping Apple Notes sync — not on macOS")
        return 0

    account_names_ids = db.get_all_account_names_and_aliases()
    if not account_names_ids:
        log.warning("No accounts seeded — run setup_accounts.py first")
        return 0

    all_names = [n for n, _ in account_names_ids]
    name_to_id = _build_name_to_id(account_names_ids)
    id_to_name = {}
    for name, aid in account_names_ids:
        if aid not in id_to_name:
            id_to_name[aid] = name

    # Pre-build alias lookup sorted longest-first
    alias_lookup = [(n.lower(), aid) for n, aid in account_names_ids]
    alias_lookup.sort(key=lambda x: len(x[0]), reverse=True)

    # Step 1: Fetch titles
    titles = get_all_note_titles_fast()
    if not titles:
        log.info("No Apple Notes found")
        return 0
    log.info("Apple Notes: found %d notes, scanning for hospital mentions...", len(titles))

    # Step 2: Clear old apple_notes to prevent duplicates on re-sync
    conn = db.get_conn()
    conn.execute("DELETE FROM account_notes WHERE source='apple_notes'")
    conn.commit()
    conn.close()
    log.info("Cleared old apple_notes entries for clean re-sync")

    # Step 3: For each note, determine relevance and fetch content if needed
    synced = 0
    for i, title in enumerate(titles, start=1):
        # Quick title check: does it mention any hospital?
        title_hospital_ids = _find_hospitals_in_text(title, name_to_id, alias_lookup)

        # Also try fuzzy match on title
        fuzzy_match = process.extractOne(title, all_names, scorer=fuzz.token_sort_ratio)
        fuzzy_id = None
        if fuzzy_match and fuzzy_match[1] >= 65:
            fuzzy_id = next((aid for n, aid in account_names_ids if n == fuzzy_match[0]), None)

        candidate_ids = set(title_hospital_ids)
        if fuzzy_id:
            candidate_ids.add(fuzzy_id)

        # If title doesn't hint at any hospital, skip content fetch (saves time)
        # But also check for common work-related terms that might contain hospital info inside
        title_lower = title.lower()
        has_work_hints = any(w in title_lower for w in [
            "tuesday", "wednesday", "thursday", "friday", "monday",
            "go live", "validation", "follow up", "meeting", "rounds",
            "inservice", "in-service", "notes", "update", "plan",
        ])

        if not candidate_ids and not has_work_hints:
            continue

        # Fetch full content
        content = get_note_content_by_index(i)
        if not content or len(content.strip()) < 10:
            continue

        # Scan content for ALL hospital mentions
        content_hospital_ids = _find_hospitals_in_text(content, name_to_id, alias_lookup)
        all_hospital_ids = set(content_hospital_ids) | candidate_ids

        if not all_hospital_ids:
            continue

        # Split content into per-hospital sections
        sections = _split_note_into_hospital_sections(
            content, alias_lookup, name_to_id, id_to_name)

        if sections:
            # File each section to its hospital
            for account_id, lines in sections.items():
                if account_id not in all_hospital_ids:
                    continue  # only file to hospitals we confirmed exist in content
                summary = _summarize_lines(lines)
                if len(summary.strip()) < 5:
                    continue
                db.upsert_account_note(
                    account_id=account_id,
                    source="apple_notes",
                    title=title,
                    content=summary,
                    note_date=None,
                )
                synced += 1
                log.info("  → synced section from %r to account %d (%s)",
                         title, account_id, id_to_name.get(account_id, "?"))
        else:
            # No sections detected — content doesn't mention specific hospitals by line
            # File entire note to the best-matching hospital from title
            if len(all_hospital_ids) == 1:
                account_id = list(all_hospital_ids)[0]
            elif fuzzy_id and fuzzy_id in all_hospital_ids:
                account_id = fuzzy_id
            elif title_hospital_ids:
                account_id = title_hospital_ids[0]
            else:
                account_id = list(all_hospital_ids)[0]

            summary = _summarize_lines(content.split('\n'))
            if len(summary.strip()) < 5:
                continue
            db.upsert_account_note(
                account_id=account_id,
                source="apple_notes",
                title=title,
                content=summary,
                note_date=None,
            )
            synced += 1
            log.info("  → synced full note %r to account %d (%s)",
                     title, account_id, id_to_name.get(account_id, "?"))

    log.info("Apple Notes sync complete: %d entries across accounts", synced)
    return synced


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    count = sync_apple_notes()
    print(f"Synced {count} Apple Notes")
