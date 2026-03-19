"""
SQLite database layer — schema, connection, and all query helpers.
WAL mode enabled for concurrent reads from Flask + scheduler.
"""

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import config


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS hospital_systems (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        name     TEXT NOT NULL UNIQUE,
        aliases  TEXT DEFAULT '[]'   -- JSON array of alternate names
    );

    CREATE TABLE IF NOT EXISTS accounts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        system_id   INTEGER REFERENCES hospital_systems(id),
        name        TEXT NOT NULL UNIQUE,
        aliases     TEXT DEFAULT '[]',   -- JSON array of alternate names / email report names
        address     TEXT,
        city        TEXT,
        state       TEXT,
        territory   TEXT,
        notes       TEXT,
        updated_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS contacts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        name        TEXT NOT NULL,
        role        TEXT,
        phone       TEXT,
        email       TEXT,
        notes       TEXT,
        updated_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS products (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        item_number TEXT UNIQUE,
        description TEXT NOT NULL,
        prod_line   TEXT,   -- TEG, TEG6, HCC-SE6, etc.
        prod_type   TEXT    -- Disposable, Instrument, etc.
    );

    CREATE TABLE IF NOT EXISTS sales (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id  INTEGER REFERENCES accounts(id),
        product_id  INTEGER REFERENCES products(id),
        prod_line   TEXT,
        units       INTEGER,
        revenue     REAL,
        report_date TEXT,   -- ISO date string YYYY-MM-DD
        tracking    TEXT,
        carrier     TEXT,
        created_at  TEXT DEFAULT (datetime('now')),
        UNIQUE(account_id, product_id, report_date, tracking)
    );

    CREATE TABLE IF NOT EXISTS revenue_targets (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id      INTEGER REFERENCES accounts(id),
        period_type     TEXT,    -- month, quarter, year
        period_label    TEXT,    -- e.g. "2026-Q1", "2026-03"
        actual          REAL,
        rr_actual       REAL,    -- run-rate actual
        target          REAL,
        pct_of_target   REAL,
        py_revenue      REAL,    -- prior year
        report_date     TEXT,
        UNIQUE(account_id, period_type, period_label, report_date)
    );

    CREATE TABLE IF NOT EXISTS account_notes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        source      TEXT NOT NULL,   -- apple_notes, onenote, manual
        title       TEXT,
        content     TEXT,
        note_date   TEXT,
        updated_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS email_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        subject     TEXT,
        sender      TEXT,
        received_at TEXT,
        parsed_at   TEXT DEFAULT (datetime('now')),
        status      TEXT DEFAULT 'ok',
        message_id  TEXT UNIQUE,
        rows_inserted INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS unmatched_accounts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_name    TEXT UNIQUE,
        first_seen  TEXT DEFAULT (datetime('now')),
        resolved_to INTEGER REFERENCES accounts(id)
    );
    """)

    conn.commit()
    conn.close()


# ── Hospital Systems ──────────────────────────────────────────────────────────

def upsert_system(name: str, aliases: list[str] = None) -> int:
    conn = get_conn()
    aliases_json = json.dumps(aliases or [])
    conn.execute(
        "INSERT INTO hospital_systems (name, aliases) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET aliases=excluded.aliases",
        (name, aliases_json),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM hospital_systems WHERE name=?", (name,)).fetchone()
    conn.close()
    return row["id"]


def get_all_systems() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM hospital_systems ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Accounts ──────────────────────────────────────────────────────────────────

def upsert_account(name: str, system_id: int = None, aliases: list[str] = None,
                   address: str = None, city: str = None, state: str = None,
                   territory: str = None) -> int:
    conn = get_conn()
    aliases_json = json.dumps(aliases or [])
    conn.execute("""
        INSERT INTO accounts (name, system_id, aliases, address, city, state, territory)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            system_id=COALESCE(excluded.system_id, system_id),
            aliases=excluded.aliases,
            updated_at=datetime('now')
    """, (name, system_id, aliases_json, address, city, state, territory))
    conn.commit()
    row = conn.execute("SELECT id FROM accounts WHERE name=?", (name,)).fetchone()
    conn.close()
    return row["id"]


def get_all_accounts() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, hs.name as system_name
        FROM accounts a
        LEFT JOIN hospital_systems hs ON a.system_id = hs.id
        ORDER BY hs.name NULLS LAST, a.name
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["aliases"] = json.loads(d.get("aliases") or "[]")
        result.append(d)
    return result


def get_account(account_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("""
        SELECT a.*, hs.name as system_name
        FROM accounts a
        LEFT JOIN hospital_systems hs ON a.system_id = hs.id
        WHERE a.id = ?
    """, (account_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["aliases"] = json.loads(d.get("aliases") or "[]")
    return d


def find_account_by_name(name: str) -> dict | None:
    """Exact match first, then check aliases JSON."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM accounts WHERE name=?", (name,)).fetchone()
    if row:
        conn.close()
        d = dict(row)
        d["aliases"] = json.loads(d.get("aliases") or "[]")
        return d
    # search aliases
    rows = conn.execute("SELECT * FROM accounts").fetchall()
    conn.close()
    for r in rows:
        aliases = json.loads(r["aliases"] or "[]")
        if name in aliases:
            d = dict(r)
            d["aliases"] = aliases
            return d
    return None


def get_all_account_names_and_aliases() -> list[tuple[str, int]]:
    """Return [(name_or_alias, account_id), ...] for fuzzy matching."""
    conn = get_conn()
    rows = conn.execute("SELECT id, name, aliases FROM accounts").fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append((r["name"], r["id"]))
        for alias in json.loads(r["aliases"] or "[]"):
            result.append((alias, r["id"]))
    return result


def add_alias_to_account(account_id: int, alias: str):
    conn = get_conn()
    row = conn.execute("SELECT aliases FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        conn.close()
        return
    aliases = json.loads(row["aliases"] or "[]")
    if alias not in aliases:
        aliases.append(alias)
        conn.execute("UPDATE accounts SET aliases=? WHERE id=?",
                     (json.dumps(aliases), account_id))
        conn.commit()
    conn.close()


# ── Contacts ──────────────────────────────────────────────────────────────────

def get_contacts(account_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM contacts WHERE account_id=? ORDER BY name", (account_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_contact(account_id: int, name: str, role: str = None,
                phone: str = None, email: str = None, notes: str = None) -> int:
    conn = get_conn()
    c = conn.execute("""
        INSERT INTO contacts (account_id, name, role, phone, email, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (account_id, name, role, phone, email, notes))
    conn.commit()
    contact_id = c.lastrowid
    conn.close()
    return contact_id


def update_contact(contact_id: int, **kwargs):
    allowed = {"name", "role", "phone", "email", "notes"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    conn = get_conn()
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE contacts SET {sets}, updated_at=datetime('now') WHERE id=?",
                 (*fields.values(), contact_id))
    conn.commit()
    conn.close()


def delete_contact(contact_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
    conn.commit()
    conn.close()


# ── Products ──────────────────────────────────────────────────────────────────

def upsert_product(item_number: str, description: str,
                   prod_line: str = None, prod_type: str = None) -> int:
    conn = get_conn()
    conn.execute("""
        INSERT INTO products (item_number, description, prod_line, prod_type)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(item_number) DO UPDATE SET
            description=excluded.description,
            prod_line=excluded.prod_line,
            prod_type=excluded.prod_type
    """, (item_number, description, prod_line, prod_type))
    conn.commit()
    row = conn.execute("SELECT id FROM products WHERE item_number=?",
                       (item_number,)).fetchone()
    conn.close()
    return row["id"]


# ── Sales ─────────────────────────────────────────────────────────────────────

def insert_sale(account_id: int, product_id: int, prod_line: str,
                units: int, revenue: float, report_date: str,
                tracking: str = None, carrier: str = None) -> bool:
    """Returns True if inserted, False if duplicate."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO sales (account_id, product_id, prod_line, units, revenue,
                               report_date, tracking, carrier)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (account_id, product_id, prod_line, units, revenue,
              report_date, tracking, carrier))
        conn.commit()
        inserted = True
    except sqlite3.IntegrityError:
        inserted = False
    finally:
        conn.close()
    return inserted


def get_account_sales_summary(account_id: int, days: int = 90) -> list[dict]:
    """Product-level rollup for the last N days."""
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.description, p.prod_line, p.prod_type, p.item_number,
               SUM(s.units) as total_units, SUM(s.revenue) as total_revenue,
               MAX(s.report_date) as last_order_date
        FROM sales s
        JOIN products p ON s.product_id = p.id
        WHERE s.account_id = ? AND s.report_date >= ?
        GROUP BY p.id
        ORDER BY total_revenue DESC
    """, (account_id, since)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_account_last_order_date(account_id: int) -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT MAX(report_date) as last FROM sales WHERE account_id=?",
        (account_id,)
    ).fetchone()
    conn.close()
    return row["last"] if row else None


def get_recent_orders(account_id: int, limit: int = 10) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT s.report_date, s.units, s.revenue, s.tracking, s.carrier,
               p.description, p.prod_line, p.item_number
        FROM sales s
        JOIN products p ON s.product_id = p.id
        WHERE s.account_id = ?
        ORDER BY s.report_date DESC, s.revenue DESC
        LIMIT ?
    """, (account_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_accounts_sales_summary() -> list[dict]:
    """Aggregate stats for every account — used for sidebar health indicators."""
    since_30 = (date.today() - timedelta(days=30)).isoformat()
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.id, a.name, a.system_id,
               COALESCE(SUM(s.revenue), 0) as revenue_30d,
               COALESCE(SUM(s.units), 0)   as units_30d,
               MAX(s.report_date)           as last_order
        FROM accounts a
        LEFT JOIN sales s ON s.account_id = a.id AND s.report_date >= ?
        GROUP BY a.id
        ORDER BY revenue_30d DESC
    """, (since_30,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Revenue Targets ───────────────────────────────────────────────────────────

def upsert_revenue_target(account_id: int, period_type: str, period_label: str,
                          actual: float, rr_actual: float, target: float,
                          pct_of_target: float, py_revenue: float, report_date: str):
    conn = get_conn()
    conn.execute("""
        INSERT INTO revenue_targets
            (account_id, period_type, period_label, actual, rr_actual,
             target, pct_of_target, py_revenue, report_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, period_type, period_label, report_date) DO UPDATE SET
            actual=excluded.actual, rr_actual=excluded.rr_actual,
            target=excluded.target, pct_of_target=excluded.pct_of_target
    """, (account_id, period_type, period_label, actual, rr_actual,
          target, pct_of_target, py_revenue, report_date))
    conn.commit()
    conn.close()


def get_latest_targets(account_id: int) -> dict:
    """Returns most recent month/quarter/year targets."""
    conn = get_conn()
    result = {}
    for period in ("month", "quarter", "year"):
        row = conn.execute("""
            SELECT * FROM revenue_targets
            WHERE account_id=? AND period_type=?
            ORDER BY report_date DESC LIMIT 1
        """, (account_id, period)).fetchone()
        result[period] = dict(row) if row else None
    conn.close()
    return result


# ── Account Notes ─────────────────────────────────────────────────────────────

def upsert_account_note(account_id: int, source: str, title: str,
                        content: str, note_date: str = None):
    conn = get_conn()
    conn.execute("""
        INSERT INTO account_notes (account_id, source, title, content, note_date)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
    """, (account_id, source, title, content, note_date))
    conn.commit()
    conn.close()


def add_manual_note(account_id: int, content: str, title: str = None) -> int:
    conn = get_conn()
    c = conn.execute("""
        INSERT INTO account_notes (account_id, source, title, content, note_date)
        VALUES (?, 'manual', ?, ?, date('now'))
    """, (account_id, title or "Note", content))
    conn.commit()
    note_id = c.lastrowid
    conn.close()
    return note_id


def get_account_notes(account_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM account_notes
        WHERE account_id=?
        ORDER BY updated_at DESC
        LIMIT 20
    """, (account_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Email Log ─────────────────────────────────────────────────────────────────

def log_email(subject: str, sender: str, received_at: str,
              message_id: str, rows_inserted: int = 0, status: str = "ok"):
    conn = get_conn()
    conn.execute("""
        INSERT INTO email_log (subject, sender, received_at, message_id, rows_inserted, status)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO NOTHING
    """, (subject, sender, received_at, message_id, rows_inserted, status))
    conn.commit()
    conn.close()


def email_already_processed(message_id: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT id FROM email_log WHERE message_id=?",
                       (message_id,)).fetchone()
    conn.close()
    return row is not None


# ── Unmatched Accounts ────────────────────────────────────────────────────────

def flag_unmatched(raw_name: str):
    conn = get_conn()
    conn.execute("""
        INSERT INTO unmatched_accounts (raw_name)
        VALUES (?)
        ON CONFLICT(raw_name) DO NOTHING
    """, (raw_name,))
    conn.commit()
    conn.close()


def get_unmatched() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT u.*, a.name as resolved_name
        FROM unmatched_accounts u
        LEFT JOIN accounts a ON u.resolved_to = a.id
        WHERE u.resolved_to IS NULL
        ORDER BY u.first_seen DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resolve_unmatched(raw_name: str, account_id: int):
    conn = get_conn()
    conn.execute("""
        UPDATE unmatched_accounts SET resolved_to=? WHERE raw_name=?
    """, (account_id, raw_name))
    conn.commit()
    conn.close()
    add_alias_to_account(account_id, raw_name)


# ── Alerts ────────────────────────────────────────────────────────────────────

def compute_alerts() -> list[dict]:
    alerts = []
    today = date.today()
    accounts = get_all_accounts()

    for acct in accounts:
        acct_id = acct["id"]

        # Check revenue target shortfall
        targets = get_latest_targets(acct_id)
        month_t = targets.get("month")
        if month_t and month_t.get("target") and month_t["target"] > 0:
            pct = month_t.get("pct_of_target", 0) or 0
            if pct < config.MTD_ALERT_PCT:
                shortfall = (month_t["target"] or 0) - (month_t["actual"] or 0)
                alerts.append({
                    "level": "critical" if pct < 40 else "warning",
                    "account_id": acct_id,
                    "account_name": acct["name"],
                    "type": "revenue",
                    "message": f"{acct['name']}: {pct:.1f}% of monthly target — "
                               f"${shortfall:,.0f} gap remaining",
                })

        # Check days since last order
        last_order = get_account_last_order_date(acct_id)
        if last_order:
            days_since = (today - date.fromisoformat(last_order)).days
            if days_since >= config.REORDER_ALERT_DAYS:
                alerts.append({
                    "level": "warning",
                    "account_id": acct_id,
                    "account_name": acct["name"],
                    "type": "reorder",
                    "message": f"{acct['name']}: no orders in {days_since} days — "
                               f"reorder likely due",
                })

    # Sort: critical first
    alerts.sort(key=lambda a: (0 if a["level"] == "critical" else 1, a["account_name"]))
    return alerts


# ── Dashboard Summary (single query for fast page load) ──────────────────────

def get_dashboard_data() -> dict:
    accounts = get_all_accounts()
    systems = get_all_systems()
    sales_summary = get_all_accounts_sales_summary()
    sales_by_id = {r["id"]: r for r in sales_summary}
    unmatched = get_unmatched()

    # Annotate each account with 30-day revenue + last order
    for acct in accounts:
        summary = sales_by_id.get(acct["id"], {})
        acct["revenue_30d"] = summary.get("revenue_30d", 0)
        acct["units_30d"] = summary.get("units_30d", 0)
        acct["last_order"] = summary.get("last_order")
        targets = get_latest_targets(acct["id"])
        acct["targets"] = targets

    return {
        "accounts": accounts,
        "systems": systems,
        "alerts": compute_alerts(),
        "unmatched": unmatched,
        "last_sync": _get_last_sync(),
    }


def _get_last_sync() -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT MAX(parsed_at) as last FROM email_log WHERE status='ok'"
    ).fetchone()
    conn.close()
    return row["last"] if row else None
