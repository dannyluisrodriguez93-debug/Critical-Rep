"""
Salesforce integration (optional).
If you have API access, this pulls account contacts, shipment/revenue data,
and opportunity data directly from SF and merges it into the local database.

Gracefully no-ops if credentials are missing or access is denied.
"""

import logging
import re
from datetime import date, timedelta

from rapidfuzz import process, fuzz

import config
import database as db

log = logging.getLogger(__name__)

# Report ID for "TEG Disp Focus" (Shipments with Accounts)
TEG_DISP_FOCUS_REPORT_ID = "00OC0000005QijwMAC"

# Known custom object API name candidates for shipments
_SHIPMENT_OBJECT_CANDIDATES = [
    "Shipment__c",
    "Ship_To_Site__c",
    "Shipments__c",
    "Revenue_Line__c",
    "Revenue_Line_Item__c",
    "Order_Line__c",
]


def _get_sf():
    """Return a Salesforce connection or None if unavailable."""
    # DB settings take priority over env vars
    username = db.get_setting("sf_username") or config.SF_USERNAME
    password = db.get_setting("sf_password") or config.SF_PASSWORD
    token    = db.get_setting("sf_security_token") or config.SF_SECURITY_TOKEN
    domain   = db.get_setting("sf_domain") or config.SF_DOMAIN

    if not all([username, password]):
        log.info("Salesforce credentials not configured — skipping SF sync")
        return None
    try:
        from simple_salesforce import Salesforce
        sf = Salesforce(
            username=username,
            password=password,
            security_token=token or "",
            domain=domain or "login",
        )
        log.info("Salesforce connected as %s", username)
        return sf
    except Exception as e:
        log.warning("Salesforce connection failed: %s", e)
        return None


def sync_sf_contacts() -> int:
    """
    Pull contacts from Salesforce and match them to local accounts.
    Returns number of contacts synced.
    """
    sf = _get_sf()
    if not sf:
        return 0

    account_names_ids = db.get_all_account_names_and_aliases()
    all_names = [n for n, _ in account_names_ids]

    try:
        result = sf.query_all("""
            SELECT Id, Name, Title, Phone, Email, Account.Name, Account.Id
            FROM Contact
            WHERE Account.Name != null
            ORDER BY Account.Name, Name
        """)
    except Exception as e:
        log.warning("SF contacts query failed: %s", e)
        return 0

    synced = 0
    for record in result.get("records", []):
        acct_name_sf = record.get("Account", {}).get("Name", "")
        contact_name = record.get("Name", "")
        if not acct_name_sf or not contact_name:
            continue

        match = process.extractOne(acct_name_sf, all_names, scorer=fuzz.token_sort_ratio)
        if not match or match[1] < 70:
            continue

        account_id = next(
            (aid for n, aid in account_names_ids if n == match[0]), None
        )
        if not account_id:
            continue

        # Check if contact already exists
        existing = db.get_contacts(account_id)
        if any(c["name"].lower() == contact_name.lower() for c in existing):
            continue  # don't duplicate

        db.add_contact(
            account_id=account_id,
            name=contact_name,
            role=record.get("Title"),
            phone=record.get("Phone"),
            email=record.get("Email"),
            notes="Synced from Salesforce",
        )
        synced += 1

    log.info("Salesforce: synced %d contacts", synced)
    return synced


def sync_sf_opportunities() -> int:
    """
    Pull current quarter opportunity amounts from Salesforce.
    Stores as revenue_targets entries.
    Returns number of accounts updated.
    """
    sf = _get_sf()
    if not sf:
        return 0

    account_names_ids = db.get_all_account_names_and_aliases()
    all_names = [n for n, _ in account_names_ids]

    try:
        result = sf.query_all("""
            SELECT Account.Name, SUM(Amount) TotalAmount, CALENDAR_QUARTER(CloseDate) Quarter
            FROM Opportunity
            WHERE IsClosed = false AND CloseDate = THIS_QUARTER
            GROUP BY Account.Name, CALENDAR_QUARTER(CloseDate)
        """)
    except Exception as e:
        log.warning("SF opportunities query failed (may need GroupBy permission): %s", e)
        return 0

    from datetime import date
    today = date.today()
    quarter_label = f"{today.year}-Q{((today.month - 1) // 3) + 1}"
    updated = 0

    for record in result.get("records", []):
        acct_name_sf = record.get("Account", {}).get("Name", "")
        amount = record.get("TotalAmount", 0) or 0

        match = process.extractOne(acct_name_sf, all_names, scorer=fuzz.token_sort_ratio)
        if not match or match[1] < 70:
            continue

        account_id = next(
            (aid for n, aid in account_names_ids if n == match[0]), None
        )
        if not account_id:
            continue

        db.upsert_revenue_target(
            account_id=account_id,
            period_type="quarter",
            period_label=quarter_label,
            actual=amount,
            rr_actual=amount,
            target=0,
            pct_of_target=0,
            py_revenue=0,
            report_date=today.isoformat(),
        )
        updated += 1

    log.info("Salesforce: updated %d account opportunity amounts", updated)
    return updated


def _discover_shipment_object(sf) -> str | None:
    """Try to find the API name of the shipment/revenue custom object."""
    for obj_name in _SHIPMENT_OBJECT_CANDIDATES:
        try:
            desc = sf.__getattr__(obj_name).describe()
            log.info("Found shipment object: %s (%s)", obj_name, desc.get("label", ""))
            return obj_name
        except Exception:
            continue

    # Fallback: search all custom objects for anything shipment-related
    try:
        sobjects = sf.describe()["sobjects"]
        for obj in sobjects:
            name_lower = obj["name"].lower()
            label_lower = obj.get("label", "").lower()
            if any(kw in name_lower or kw in label_lower
                   for kw in ("shipment", "ship_to", "revenue_line")):
                if obj.get("queryable"):
                    log.info("Discovered shipment object: %s (%s)",
                             obj["name"], obj.get("label"))
                    return obj["name"]
    except Exception as e:
        log.warning("Object discovery failed: %s", e)

    return None


def _get_shipment_fields(sf, obj_name: str) -> dict:
    """Get field API names for the shipment object by matching known labels."""
    try:
        desc = sf.__getattr__(obj_name).describe()
    except Exception as e:
        log.warning("Cannot describe %s: %s", obj_name, e)
        return {}

    # Map labels we saw in the report builder to API names
    label_to_key = {
        "revenue amount": "revenue_field",
        "gl date": "gl_date_field",
        "item number": "item_number_field",
        "description": "description_field",
        "product line": "product_line_field",
        "product type": "product_type_field",
        "product sub type": "product_sub_type_field",
        "units": "units_field",
        "trx_number": "trx_number_field",
        "shipment id": "shipment_id_field",
        "account name": "account_name_field",
        "site number": "site_number_field",
        "teg clinical": "teg_clinical_field",
    }

    field_map = {}
    for field in desc["fields"]:
        label_lower = field["label"].lower().strip()
        if label_lower in label_to_key:
            field_map[label_to_key[label_lower]] = field["name"]

    # Also look for parent account relationship
    for field in desc["fields"]:
        if field["type"] == "reference" and "Account" in (field.get("referenceTo") or []):
            field_map.setdefault("account_lookup_field", field["name"])

    log.info("Shipment field map: %s", field_map)
    return field_map


def _match_account(sf_name: str, account_names_ids: list, all_names: list) -> int | None:
    """Fuzzy-match a Salesforce account name to a local account ID."""
    if not sf_name:
        return None
    match = process.extractOne(sf_name, all_names, scorer=fuzz.token_sort_ratio)
    if not match or match[1] < 65:
        return None
    return next((aid for n, aid in account_names_ids if n == match[0]), None)


def sync_sf_shipments_via_report(sf=None) -> int:
    """
    Pull shipment/revenue data using the Salesforce Analytics API
    to run the 'TEG Disp Focus' report. This doesn't require knowing
    the custom object's API name.

    Returns number of sales rows synced.
    """
    if sf is None:
        sf = _get_sf()
    if not sf:
        return 0

    account_names_ids = db.get_all_account_names_and_aliases()
    all_names = [n for n, _ in account_names_ids]

    try:
        # Run the report via Analytics API
        report_data = sf.restful(
            f"analytics/reports/{TEG_DISP_FOCUS_REPORT_ID}",
            method="POST",
            json={"reportMetadata": {"detailColumns": []}},
        )
    except Exception as e:
        log.warning("Report API call failed: %s", e)
        return 0

    if not report_data:
        log.warning("Empty report response")
        return 0

    # Parse the report result
    metadata = report_data.get("reportMetadata", {})
    detail_cols = metadata.get("detailColumnInfo", {})
    groupings_down = report_data.get("groupingsDown", {})
    fact_map = report_data.get("factMap", {})

    synced = 0

    # The report groups by TEG Clinical > Parent Account, then columns by quarter/month
    # factMap keys like "0!0" = first row group, first col group
    # We need the aggregates per account

    # For grouped reports, iterate groupingsDown to get account names
    # then pull the aggregate from factMap
    groups = groupings_down.get("groupings", [])

    for teg_group in groups:
        # First level: TEG Clinical (should be Danny Rodriguez)
        account_groups = teg_group.get("groupings", [])

        for acct_group in account_groups:
            sf_account_name = acct_group.get("label", "")
            acct_key = acct_group.get("key", "")

            account_id = _match_account(sf_account_name, account_names_ids, all_names)
            if not account_id:
                log.debug("No local match for SF account: %s", sf_account_name)
                continue

            # Get the aggregate row for this account across all time periods
            # factMap key pattern: "{teg_key}_{acct_key}!T" for the row subtotal
            teg_key = teg_group.get("key", "")
            fact_key = f"{teg_key}_{acct_key}!T"
            fact = fact_map.get(fact_key, {})

            if not fact:
                # Try alternate key patterns
                fact_key = f"{teg_key}_{acct_key}!0"
                fact = fact_map.get(fact_key, {})

            aggregates = fact.get("aggregates", [])
            if aggregates:
                total_revenue = aggregates[0].get("value", 0) or 0
            else:
                total_revenue = 0

            if total_revenue <= 0:
                continue

            # Store as a summary sale entry for this account
            # Use a synthetic item number for the report-based import
            product_id = db.upsert_product(
                item_number="SF-REPORT-SUMMARY",
                description="Salesforce Report Summary (TEG Disposables)",
                prod_line="TEG",
                prod_type="Summary",
                category="cartridge",
            )

            today = date.today()
            report_date = today.isoformat()

            inserted = db.insert_sale(
                account_id=account_id,
                product_id=product_id,
                prod_line="TEG",
                units=0,
                revenue=total_revenue,
                report_date=report_date,
                tracking=f"SF-RPT-{acct_key}",
            )
            if inserted:
                synced += 1
                log.info("  → SF report: %s → account %d, revenue $%.2f",
                         sf_account_name, account_id, total_revenue)

    log.info("Salesforce report sync: %d account summaries synced", synced)
    return synced


def sync_sf_shipments_via_soql(sf=None) -> int:
    """
    Pull individual shipment records via SOQL.
    Discovers the custom object name and fields dynamically.

    Returns number of sales rows synced.
    """
    if sf is None:
        sf = _get_sf()
    if not sf:
        return 0

    # Discover the shipment object
    obj_name = _discover_shipment_object(sf)
    if not obj_name:
        log.info("Shipment object not found — falling back to report API")
        return sync_sf_shipments_via_report(sf)

    # Discover field names
    fields = _get_shipment_fields(sf, obj_name)
    if not fields.get("revenue_field") or not fields.get("gl_date_field"):
        log.warning("Missing critical fields on %s — falling back to report API", obj_name)
        return sync_sf_shipments_via_report(sf)

    # Build SOQL query
    rev_field = fields["revenue_field"]
    date_field = fields["gl_date_field"]
    item_field = fields.get("item_number_field", "Name")
    desc_field = fields.get("description_field", "Name")
    prod_line_field = fields.get("product_line_field")
    units_field = fields.get("units_field")
    trx_field = fields.get("trx_number_field")
    account_field = fields.get("account_lookup_field", "Account__c")

    # Calculate date range: last 365 days
    since = (date.today() - timedelta(days=365)).isoformat()

    select_fields = [
        rev_field, date_field, item_field, desc_field,
        f"{account_field.replace('__c', '__r') if account_field.endswith('__c') else 'Account'}.Name",
    ]
    if prod_line_field:
        select_fields.append(prod_line_field)
    if units_field:
        select_fields.append(units_field)
    if trx_field:
        select_fields.append(trx_field)

    soql = f"""
        SELECT {', '.join(select_fields)}
        FROM {obj_name}
        WHERE {date_field} >= {since}
        ORDER BY {date_field} DESC
    """

    try:
        result = sf.query_all(soql)
    except Exception as e:
        log.warning("SOQL shipment query failed: %s — falling back to report", e)
        return sync_sf_shipments_via_report(sf)

    account_names_ids = db.get_all_account_names_and_aliases()
    all_names = [n for n, _ in account_names_ids]

    synced = 0
    for record in result.get("records", []):
        # Extract account name from relationship
        acct_ref = account_field.replace("__c", "__r") if account_field.endswith("__c") else "Account"
        sf_account_name = (record.get(acct_ref) or {}).get("Name", "")

        account_id = _match_account(sf_account_name, account_names_ids, all_names)
        if not account_id:
            continue

        item_num = record.get(item_field, "") or "UNKNOWN"
        description = record.get(desc_field, "") or item_num
        revenue = record.get(rev_field, 0) or 0
        gl_date = record.get(date_field, "")
        units = record.get(units_field, 0) if units_field else 0
        prod_line = record.get(prod_line_field, "TEG") if prod_line_field else "TEG"
        trx_number = record.get(trx_field, "") if trx_field else ""

        if revenue <= 0:
            continue

        # Parse GL date to YYYY-MM-DD
        if gl_date and "T" in gl_date:
            gl_date = gl_date.split("T")[0]

        product_id = db.upsert_product(
            item_number=item_num,
            description=description,
            prod_line=prod_line,
        )

        inserted = db.insert_sale(
            account_id=account_id,
            product_id=product_id,
            prod_line=prod_line,
            units=units or 0,
            revenue=revenue,
            report_date=gl_date,
            tracking=trx_number or None,
        )
        if inserted:
            synced += 1

    log.info("Salesforce SOQL sync: %d shipment records synced", synced)
    return synced


def sync_sf_shipments() -> int:
    """
    Main entry point for shipment sync.
    Tries SOQL first (granular data), falls back to report API (summary).
    """
    sf = _get_sf()
    if not sf:
        return 0
    return sync_sf_shipments_via_soql(sf)


def run_sf_sync() -> dict:
    contacts = sync_sf_contacts()
    opps = sync_sf_opportunities()
    shipments = sync_sf_shipments()
    return {
        "contacts_synced": contacts,
        "opportunities_synced": opps,
        "shipments_synced": shipments,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    result = run_sf_sync()
    print(result)
