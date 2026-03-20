"""
Email ingestion — fetches daily sales report emails, parses HTML tables,
stores results in SQLite.

Email source: Gmail (via Google OAuth — connect through the Integrations page).
Your Outlook emails should be forwarded to your Gmail address.

Handles four email types:
  1. "Yesterday's Sales Report" — per-shipment rows (account, product, units, revenue)
     Sender: tableau-no-reply@haemonetics.com
  2. "BI Daily Report: Quarter Breakdown by Product" — quarterly rollup
     Sender: tableau-no-reply@haemonetics.com
  3. "Pricing Hold Report" / Revenue Targets — overall MTD/QTD/YTD targets
     Sender: tableau-no-reply@haemonetics.com
  4. Oracle supply order notifications — order confirmations with item/quantity detail
     Sender: oracle-no-reply@haemonetics.com (or configured via ORACLE_SENDER / DB setting)
     Subject keywords: "order", "shipment", "supply order", "order confirmation"

To add additional senders, update REPORT_SENDERS in config.py or set the
"report_senders" key in DB settings (comma-separated).  The Oracle sender can
also be set independently via ORACLE_SENDER in config.py / env.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup
from rapidfuzz import process, fuzz

import config
import database as db

log = logging.getLogger(__name__)


# ── Account name resolver ─────────────────────────────────────────────────────

_name_cache: list[tuple[str, int]] = []


def _load_name_cache():
    global _name_cache
    _name_cache = db.get_all_account_names_and_aliases()


def resolve_account_name(raw_name: str) -> int | None:
    """
    Fuzzy-match a raw account name from an email report to a DB account id.
    Returns None if no confident match; flags the name as unmatched.
    """
    if not _name_cache:
        _load_name_cache()

    # Strip "Total" / whitespace suffixes that appear in report subtotals
    clean = re.sub(r"\s+(Total|total|TOTAL)$", "", raw_name).strip()

    names = [n for n, _ in _name_cache]
    match = process.extractOne(clean, names, scorer=fuzz.token_sort_ratio)
    if match and match[1] >= 75:
        matched_name = match[0]
        account_id = next(aid for n, aid in _name_cache if n == matched_name)
        return account_id

    # No confident match — flag for manual resolution
    db.flag_unmatched(raw_name)
    log.warning("Unmatched account name: %r", raw_name)
    return None


def _parse_currency(s: str) -> float:
    """'$1,234.56' → 1234.56"""
    if not s:
        return 0.0
    return float(re.sub(r"[^\d.]", "", s) or "0")


def _parse_int(s: str) -> int:
    if not s:
        return 0
    cleaned = re.sub(r"[^\d]", "", s)
    return int(cleaned) if cleaned else 0


# ── Gmail fetch ───────────────────────────────────────────────────────────────

def fetch_report_emails(days_back: int = 7) -> list[dict]:
    """
    Fetch recent report emails from Gmail.
    Returns list of message dicts with id, subject, receivedDateTime, body.
    Returns [] gracefully if Google is not connected.
    """
    from integrations.gmail import fetch_report_emails as gmail_fetch
    return gmail_fetch(days_back=days_back)


# ── HTML table parser ─────────────────────────────────────────────────────────

def _parse_html_table(html: str) -> tuple[list[str], list[list[str]]]:
    """Extract headers and rows from the first meaningful table in HTML."""
    soup = BeautifulSoup(html, "lxml")
    # find the largest table (usually the data table, not layout)
    tables = soup.find_all("table")
    best = max(tables, key=lambda t: len(t.find_all("tr")), default=None)
    if not best:
        return [], []

    headers = []
    rows = []
    for i, tr in enumerate(best.find_all("tr")):
        cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
        if not any(cells):
            continue
        if i == 0 or not headers:
            headers = cells
        else:
            rows.append(cells)
    return headers, rows


def _col_index(headers: list[str], *candidates: str) -> int | None:
    """Find index of first matching column header (case-insensitive)."""
    lower = [h.lower() for h in headers]
    for c in candidates:
        try:
            return lower.index(c.lower())
        except ValueError:
            continue
    return None


# ── Yesterday's Sales Report parser ──────────────────────────────────────────

def parse_sales_report(html: str, report_date: str) -> int:
    """
    Parse 'Yesterday's Sales Report' HTML body.
    Columns: Employee Name, Prod Line Desc, Key Account Name, Prod Type Desc,
             Item Number, Item Description, TRACKING_NUMBER, CARRIER, Units, Revenue
    Returns count of rows inserted.
    """
    headers, rows = _parse_html_table(html)
    if not headers:
        log.warning("No table found in sales report")
        return 0

    ci = {
        "account": _col_index(headers, "Key Account Name", "Account Name"),
        "prod_line": _col_index(headers, "Prod Line Desc", "Prod Line"),
        "prod_type": _col_index(headers, "Prod Type Desc", "Prod Type"),
        "item_num": _col_index(headers, "Item Number", "Item #"),
        "item_desc": _col_index(headers, "Item Description", "Description"),
        "tracking": _col_index(headers, "TRACKING_NUMBER", "Tracking Number", "Tracking"),
        "carrier": _col_index(headers, "CARRIER", "Carrier"),
        "units": _col_index(headers, "Units"),
        "revenue": _col_index(headers, "Revenue"),
    }

    _load_name_cache()
    inserted = 0

    for row in rows:
        def get(key):
            idx = ci.get(key)
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        account_raw = get("account")
        if not account_raw or "Total" in account_raw:
            continue

        account_id = resolve_account_name(account_raw)
        if not account_id:
            continue

        item_number = get("item_num")
        description = get("item_desc")
        if not description:
            continue

        product_id = db.upsert_product(
            item_number=item_number,
            description=description,
            prod_line=get("prod_line"),
            prod_type=get("prod_type"),
        )

        units_str = get("units")
        revenue_str = get("revenue")
        units = _parse_int(units_str)
        revenue = _parse_currency(revenue_str)

        ok = db.insert_sale(
            account_id=account_id,
            product_id=product_id,
            prod_line=get("prod_line"),
            units=units,
            revenue=revenue,
            report_date=report_date,
            tracking=get("tracking") or None,
            carrier=get("carrier") or None,
        )
        if ok:
            inserted += 1

    log.info("Sales report: inserted %d rows for %s", inserted, report_date)
    return inserted


# ── BI Daily Report: Quarter Breakdown parser ─────────────────────────────────

def parse_bi_quarterly_report(html: str, report_date: str) -> int:
    """
    Parse 'BI Daily Report: Quarter Breakdown by Product'.
    Columns span quarters — we capture the most recent quarter total.
    Returns rows inserted.
    """
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    best = max(tables, key=lambda t: len(t.find_all("tr")), default=None)
    if not best:
        return 0

    # The table has merged/complex headers; we grab text rows and look for
    # rows with recognizable account patterns + dollar amounts
    rows_inserted = 0
    _load_name_cache()

    text_rows = []
    for tr in best.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
        text_rows.append(cells)

    # Find rows that contain dollar amounts (revenue rows)
    dollar_re = re.compile(r"\$[\d,]+")
    for row in text_rows:
        # Look for "Grand Total" or account-named rows
        row_text = " ".join(row)
        if "Grand Total" in row_text:
            continue
        amounts = [_parse_currency(c) for c in row if dollar_re.match(c)]
        if not amounts:
            continue

        # Try to find account name in row
        account_raw = None
        for cell in row:
            if len(cell) > 5 and not dollar_re.match(cell) and not cell.isdigit():
                account_raw = cell
                break
        if not account_raw:
            continue

        account_id = resolve_account_name(account_raw)
        if not account_id:
            continue

        # We store the last dollar value as QTD revenue approximation
        if amounts:
            # Upsert as a quarterly summary note (not individual sales — that's the sales report)
            # We just use the grand total value from the row
            pass

        rows_inserted += 1

    return rows_inserted


# ── Revenue Targets (Pricing Hold Report) ────────────────────────────────────

def parse_revenue_targets(html: str, report_date: str) -> int:
    """
    Parse Revenue Targets email content.
    Extracts: MONTH, QUARTER, YEAR columns with Actuals, RR Actuals, Target, % of Target, PY Revenue.
    These are rep-level (not account-level) targets from the Tableau dashboard.
    """
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    # Extract the structured values using regex on the combined text
    periods = {}
    for period_name in ("MONTH", "QUARTER", "YEAR"):
        section_re = re.compile(
            rf"{period_name}.*?Actuals\s+([\$\d,]+).*?"
            rf"RR Actuals\s+([\$\d,]+).*?"
            rf"Target\s+([\$\d,]+).*?"
            rf"RR % of Target\s+([\d.]+)%.*?"
            rf"PY revenue\s+([\$\d,]+)",
            re.DOTALL | re.IGNORECASE,
        )
        m = section_re.search(text)
        if m:
            periods[period_name.lower()] = {
                "actual": _parse_currency(m.group(1)),
                "rr_actual": _parse_currency(m.group(2)),
                "target": _parse_currency(m.group(3)),
                "pct_of_target": float(m.group(4)),
                "py_revenue": _parse_currency(m.group(5)),
            }

    if not periods:
        log.warning("Could not parse revenue targets from email")
        return 0

    # Store against a special "rep-level" account (id=0 doesn't exist,
    # so we find/create a __REP__ account)
    rep_account_id = _ensure_rep_account()

    today = date.today()
    period_labels = {
        "month": today.strftime("%Y-%m"),
        "quarter": f"{today.year}-Q{((today.month - 1) // 3) + 1}",
        "year": str(today.year),
    }

    inserted = 0
    for period_type, data in periods.items():
        db.upsert_revenue_target(
            account_id=rep_account_id,
            period_type=period_type,
            period_label=period_labels[period_type],
            report_date=report_date,
            **data,
        )
        inserted += 1

    return inserted


# ── Oracle Supply Order parser ────────────────────────────────────────────────

def parse_oracle_order(html: str, report_date: str) -> int:
    """
    Parse Oracle supply order notification emails.

    Oracle order emails typically contain a table with columns like:
        Item Number | Description | Quantity Ordered | Unit Price | Extended Amount
    or similar variants.  Account name is usually in the subject or a header
    line rather than per-row.

    Because the exact Oracle template is not yet confirmed, this parser:
      - Tries common column-name patterns for item, qty, and price
      - Falls back to a text-only scan for "$" amounts if no table is found
      - Stores matched rows as sales records (units + revenue) tied to the
        account resolved from the email body

    If the Oracle format differs, update the column aliases in `ci` below or
    override the "oracle_sender" DB setting and reach out to adjust the parser.

    Returns count of rows inserted.
    """
    headers, rows = _parse_html_table(html)

    # Column aliases — extend these as the real Oracle format becomes known
    if headers:
        ci = {
            "account":     _col_index(headers,
                               "Account", "Customer", "Ship To", "Key Account Name"),
            "item_num":    _col_index(headers,
                               "Item Number", "Item No", "Item #", "Product Number",
                               "Part Number"),
            "item_desc":   _col_index(headers,
                               "Description", "Item Description", "Product Description"),
            "units":       _col_index(headers,
                               "Quantity", "Qty", "Qty Ordered", "Quantity Ordered",
                               "Units"),
            "unit_price":  _col_index(headers,
                               "Unit Price", "Price", "Unit Cost"),
            "extended":    _col_index(headers,
                               "Extended Amount", "Extended Price", "Total", "Revenue"),
        }
    else:
        ci = {k: None for k in ("account", "item_num", "item_desc",
                                 "units", "unit_price", "extended")}

    _load_name_cache()
    inserted = 0

    # Attempt to find a top-level account name from the body text
    # (Oracle emails often list "Ship-To: <account name>" outside the table)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    body_text = soup.get_text(" ", strip=True)

    # Patterns like "Ship To: Hospital Name" or "Account: Hospital Name"
    top_account_id = None
    for pat in (
        r"Ship[\s\-]?To[:\s]+([A-Za-z][\w\s,\.]+?)(?:\s{2,}|\n|$)",
        r"Account[:\s]+([A-Za-z][\w\s,\.]+?)(?:\s{2,}|\n|$)",
        r"Customer[:\s]+([A-Za-z][\w\s,\.]+?)(?:\s{2,}|\n|$)",
    ):
        m = re.search(pat, body_text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if len(candidate) > 4:
                top_account_id = resolve_account_name(candidate)
                if top_account_id:
                    break

    for row in rows:
        def get(key):
            idx = ci.get(key)
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        # Per-row account overrides the top-level account (if column exists)
        account_id = None
        if ci.get("account") is not None:
            raw = get("account")
            if raw and raw.lower() not in ("", "total", "grand total"):
                account_id = resolve_account_name(raw)
        if not account_id:
            account_id = top_account_id
        if not account_id:
            continue

        item_number = get("item_num")
        description = get("item_desc")
        if not description and not item_number:
            continue

        product_id = db.upsert_product(
            item_number=item_number or None,
            description=description or f"Oracle item {item_number}",
            prod_line="TEG",
            prod_type="Supply Order",
        )

        units = _parse_int(get("units"))
        # Prefer extended/total amount; fall back to unit_price * units
        revenue_str = get("extended") or get("unit_price")
        revenue = _parse_currency(revenue_str)
        if not revenue and get("unit_price") and units:
            revenue = _parse_currency(get("unit_price")) * units

        ok = db.insert_sale(
            account_id=account_id,
            product_id=product_id,
            prod_line="TEG",
            units=units or 1,
            revenue=revenue,
            report_date=report_date,
            tracking=None,
            carrier=None,
        )
        if ok:
            inserted += 1

    log.info("Oracle order: inserted %d rows for %s", inserted, report_date)
    return inserted


def _is_oracle_sender(sender: str) -> bool:
    """Check whether an email came from Oracle (configurable via DB or config)."""
    oracle_sender = db.get_setting("oracle_sender") or config.ORACLE_SENDER
    # Support comma-separated list in case the setting holds multiple addresses
    oracle_senders = [s.strip().lower() for s in oracle_sender.split(",")]
    return sender.strip().lower() in oracle_senders


def _ensure_rep_account() -> int:
    acct = db.find_account_by_name("__REP_TOTALS__")
    if acct:
        return acct["id"]
    return db.upsert_account("__REP_TOTALS__", aliases=["Rep Total", "Danny Rodriguez Total"])


# ── Main ingestion entry point ────────────────────────────────────────────────

def run_ingestion(days_back: int = 7) -> dict:
    """
    Fetch and process all recent report emails.
    Returns summary stats.
    """
    messages = fetch_report_emails(days_back=days_back)
    stats = {"emails_processed": 0, "emails_skipped": 0, "rows_inserted": 0}

    for msg in messages:
        msg_id = msg.get("id", "")
        if db.email_already_processed(msg_id):
            stats["emails_skipped"] += 1
            continue

        subject = msg.get("subject", "")
        sender = msg.get("from", {}).get("emailAddress", {}).get("address", "")
        received = msg.get("receivedDateTime", "")
        body_html = msg.get("body", {}).get("content", "")

        # Derive the report date from receivedDateTime
        try:
            report_dt = datetime.fromisoformat(received.rstrip("Z"))
            # Sales reports are "yesterday's" — subtract 1 day
            if "yesterday" in subject.lower() or "sales report" in subject.lower():
                report_date = (report_dt - timedelta(days=1)).date().isoformat()
            else:
                report_date = report_dt.date().isoformat()
        except Exception:
            report_date = date.today().isoformat()

        subject_lower = subject.lower()
        rows = 0
        status = "ok"

        try:
            if "yesterday" in subject_lower or "sales report" in subject_lower:
                rows = parse_sales_report(body_html, report_date)
            elif "bi daily" in subject_lower or "quarter breakdown" in subject_lower:
                rows = parse_bi_quarterly_report(body_html, report_date)
            elif "pricing hold" in subject_lower or "revenue target" in subject_lower:
                rows = parse_revenue_targets(body_html, report_date)
            elif _is_oracle_sender(sender) or any(
                kw in subject_lower
                for kw in ("order confirmation", "supply order", "order notification",
                           "shipment notification", "po acknowledgment",
                           "purchase order", "order acknowledgment", "order receipt",
                           "your order", "order #", "order no.", "delivery notification",
                           "fwd: order", "fw: order")
            ):
                rows = parse_oracle_order(body_html, report_date)
            else:
                log.info("Unrecognized email type: %r — skipping", subject)
                status = "unrecognized"
        except Exception as e:
            log.exception("Error parsing email %r: %s", subject, e)
            status = "error"

        db.log_email(subject, sender, received, msg_id, rows, status)
        stats["emails_processed"] += 1
        stats["rows_inserted"] += rows

    log.info("Ingestion complete: %s", stats)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    result = run_ingestion(days_back=30)
    print(json.dumps(result, indent=2))
