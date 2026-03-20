"""
Geocoding utility using Nominatim (OpenStreetMap, no API key needed).
Results are cached back to the DB accounts table.
Rate-limited to 1 req/s per Nominatim usage policy.
"""

import logging
import time
import urllib.parse
import urllib.request
import json

import database as db

log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT    = "AccountHub/1.0 (local-hospital-crm)"

# Known coordinates for South Florida hospitals (fallback when Nominatim fails)
KNOWN_COORDS = {
    "Jackson Memorial Hospital":          (25.7891, -80.2097),
    "Jackson South Community Hospital":   (25.6354, -80.3789),
    "Baptist Hospital of Miami":          (25.6878, -80.3441),
    "South Miami Hospital":               (25.7000, -80.3094),
    "Boca Raton Regional Hospital":       (26.3683, -80.1289),
    "Baptist Bethesda Hospital":          (26.5375, -80.0728),
    "Memorial Regional Medical Center":   (26.0180, -80.2192),
    "Broward General Hospital":           (26.1224, -80.1479),
    "Broward Health North":               (26.3165, -80.1095),
    "Holy Cross Hospital":                (26.1537, -80.1234),
    "Cleveland Clinic Florida":           (26.1056, -80.3819),
    "Northwest Medical Center":           (26.2468, -80.1900),
    "Westside Regional Medical Center":   (26.1224, -80.2345),
    "JFK Medical Center":                 (26.6768, -80.0917),
    "Lawnwood Regional Medical Center":   (27.4437, -80.3409),
    "Delray Medical Center":              (26.4537, -80.0923),
    "St. Mary's Medical Center":          (26.7271, -80.0597),
    "Jupiter Medical Center":             (26.9293, -80.1076),
    "Mercy Hospital":                     (25.7321, -80.2416),
    "Memorial":                           (26.0180, -80.2192),
}


def geocode_address(address: str, city: str, state: str) -> tuple[float, float] | None:
    """
    Geocode an address string via Nominatim.
    Returns (lat, lng) or None on failure.
    """
    parts = [p for p in [address, city, state, "USA"] if p]
    query = ", ".join(parts)
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "limit": 1,
    })
    url = f"{NOMINATIM_URL}?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        log.debug("Nominatim geocode failed for '%s': %s", query, e)
    return None


def geocode_all_accounts(use_nominatim: bool = True) -> int:
    """
    Geocode every account that lacks lat/lng.
    Uses known coords first, then Nominatim as fallback.
    Returns number of accounts updated.
    """
    db.init_db()
    accounts = db.get_all_accounts_with_coords()
    updated = 0

    for acct in accounts:
        if acct.get("lat") and acct.get("lng"):
            continue  # already geocoded

        name = acct["name"]

        # 1) Try known coords lookup
        coords = KNOWN_COORDS.get(name)
        if coords:
            db.update_account_coords(acct["id"], coords[0], coords[1])
            log.info("Geocoded '%s' from known coords: %s", name, coords)
            updated += 1
            continue

        # 2) Try Nominatim (only if address available)
        if use_nominatim and (acct.get("address") or acct.get("city")):
            coords = geocode_address(
                address=acct.get("address") or "",
                city=acct.get("city") or "",
                state=acct.get("state") or "FL",
            )
            time.sleep(1.1)  # Nominatim rate limit: 1 req/s
            if coords:
                db.update_account_coords(acct["id"], coords[0], coords[1])
                log.info("Geocoded '%s' via Nominatim: %s", name, coords)
                updated += 1
                continue

        log.debug("Could not geocode '%s'", name)

    log.info("Geocoded %d accounts", updated)
    return updated


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    n = geocode_all_accounts(use_nominatim="--no-nominatim" not in sys.argv)
    print(f"Updated {n} accounts with coordinates")
