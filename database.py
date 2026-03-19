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
        aliases  TEXT DEFAULT '[]'
    );

    CREATE TABLE IF NOT EXISTS accounts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        system_id   INTEGER REFERENCES hospital_systems(id),
        name        TEXT NOT NULL UNIQUE,
        aliases     TEXT DEFAULT '[]',
        address     TEXT,
        city        TEXT,
        state       TEXT,
        territory   TEXT,
        notes       TEXT,
        updated_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS contacts (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id       INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        name             TEXT NOT NULL,
        role             TEXT,
        phone            TEXT,
        email            TEXT,
        notes            TEXT,
        imessage_handle  TEXT,   -- phone or email used in iMessage
        updated_at       TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS products (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        item_number TEXT UNIQUE,
        description TEXT NOT NULL,
        prod_line   TEXT,
        prod_type   TEXT,
        category    TEXT    -- 'cartridge', 'qc', 'instrument', 'other'
    );

    CREATE TABLE IF NOT EXISTS sales (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id  INTEGER REFERENCES accounts(id),
        product_id  INTEGER REFERENCES products(id),
        prod_line   TEXT,
        units       INTEGER,
        revenue     REAL,
        report_date TEXT,
        tracking    TEXT,
        carrier     TEXT,
        created_at  TEXT DEFAULT (datetime('now')),
        UNIQUE(account_id, product_id, report_date, tracking)
    );

    CREATE TABLE IF NOT EXISTS revenue_targets (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id      INTEGER REFERENCES accounts(id),
        period_type     TEXT,
        period_label    TEXT,
        actual          REAL,
        rr_actual       REAL,
        target          REAL,
        pct_of_target   REAL,
        py_revenue      REAL,
        report_date     TEXT,
        UNIQUE(account_id, period_type, period_label, report_date)
    );

    CREATE TABLE IF NOT EXISTS account_notes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        source      TEXT NOT NULL,
        title       TEXT,
        content     TEXT,
        note_date   TEXT,
        updated_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS email_log (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        subject       TEXT,
        sender        TEXT,
        received_at   TEXT,
        parsed_at     TEXT DEFAULT (datetime('now')),
        status        TEXT DEFAULT 'ok',
        message_id    TEXT UNIQUE,
        rows_inserted INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS unmatched_accounts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_name    TEXT UNIQUE,
        first_seen  TEXT DEFAULT (datetime('now')),
        resolved_to INTEGER REFERENCES accounts(id)
    );

    -- ── TEG Machine Inventory ──────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS teg_machines (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id    INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        location      TEXT NOT NULL,       -- e.g. "OR Suite 2", "CVICU Bed 4"
        department    TEXT,                -- OR, ICU, Cath Lab, ED, NICU, etc.
        serial_number TEXT,
        model         TEXT,               -- TEG 5000, TEG 6s, TEGfunctional
        notes         TEXT,
        is_active     INTEGER DEFAULT 1,
        updated_at    TEXT DEFAULT (datetime('now'))
    );

    -- Cartridge types run on each TEG machine
    CREATE TABLE IF NOT EXISTS teg_cartridges (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        teg_id          INTEGER NOT NULL REFERENCES teg_machines(id) ON DELETE CASCADE,
        cartridge_type  TEXT NOT NULL,
        is_active       INTEGER DEFAULT 1,
        notes           TEXT,
        UNIQUE(teg_id, cartridge_type)
    );

    -- ── Communication Log ─────────────────────────────────────────────
    -- Tracks texts, calls, emails, visits — sourced from iMessage or manual
    CREATE TABLE IF NOT EXISTS communications (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        contact_id      INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
        type            TEXT NOT NULL,     -- imessage, call, email, visit, text
        occurred_at     TEXT NOT NULL,     -- ISO datetime
        duration_sec    INTEGER,           -- for calls
        notes           TEXT,
        thread_id       TEXT,              -- iMessage chat GUID
        message_preview TEXT,             -- first 300 chars (for iMessage)
        is_from_me      INTEGER DEFAULT 1,
        created_at      TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_comms_account ON communications(account_id, occurred_at DESC);
    CREATE INDEX IF NOT EXISTS idx_comms_contact ON communications(contact_id, occurred_at DESC);

    -- ── Drive File References (Google Drive or OneDrive) ───────────────
    CREATE TABLE IF NOT EXISTS onedrive_files (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        file_id     TEXT NOT NULL,
        name        TEXT NOT NULL,
        web_url     TEXT,
        size        INTEGER,
        modified_at TEXT,
        mime_type   TEXT,
        UNIQUE(account_id, file_id)
    );

    -- ── App Settings (key/value store for integration credentials) ─────
    CREATE TABLE IF NOT EXISTS settings (
        key        TEXT PRIMARY KEY,
        value      TEXT,
        updated_at TEXT DEFAULT (datetime('now'))
    );
    """)

    conn.commit()

    # Migrate existing schemas (safe, no-op if column already exists)
    _migrate(conn)

    conn.close()


def _migrate(conn):
    """Add columns that may not exist in older databases."""
    migrations = [
        ("contacts", "imessage_handle", "TEXT"),
        ("products",  "category",        "TEXT"),
    ]
    for table, col, typ in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists


# ── Settings (key/value store for integration credentials) ────────────────────

def get_setting(key: str, default: str = None) -> str | None:
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str | None):
    conn = get_conn()
    if value is None:
        conn.execute("DELETE FROM settings WHERE key=?", (key,))
    else:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value),
        )
    conn.commit()
    conn.close()


def get_all_settings() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


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
    conn = get_conn()
    row = conn.execute("SELECT * FROM accounts WHERE name=?", (name,)).fetchone()
    if row:
        conn.close()
        d = dict(row)
        d["aliases"] = json.loads(d.get("aliases") or "[]")
        return d
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
                phone: str = None, email: str = None, notes: str = None,
                imessage_handle: str = None) -> int:
    conn = get_conn()
    c = conn.execute("""
        INSERT INTO contacts (account_id, name, role, phone, email, notes, imessage_handle)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (account_id, name, role, phone, email, notes, imessage_handle))
    conn.commit()
    contact_id = c.lastrowid
    conn.close()
    return contact_id


def update_contact(contact_id: int, **kwargs):
    allowed = {"name", "role", "phone", "email", "notes", "imessage_handle"}
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

def classify_product(description: str, item_number: str = "", prod_type: str = "") -> str:
    """Classify a product as cartridge, qc, instrument, or other."""
    d = (description or "").lower()
    i = (item_number or "").upper()
    t = (prod_type or "").lower()
    if ("quality control" in d or "control material" in d or "qc" in i
            or d.startswith("qc ") or " qc " in d):
        return "qc"
    if ("analyzer" in d or "instrument" in t or "machine" in d or
            "teg 5000 system" in d or "teg 6s system" in d):
        return "instrument"
    if any(x in d for x in ("kaolin", "heparinase", "rapidteg", "platelet map",
                              "functional fibrinogen", "citrated", "cff", "delta",
                              "cartridge", "cup", "pin", "cuvette")):
        return "cartridge"
    return "other"


def upsert_product(item_number: str, description: str,
                   prod_line: str = None, prod_type: str = None,
                   category: str = None) -> int:
    if not category:
        category = classify_product(description, item_number, prod_type)
    conn = get_conn()
    conn.execute("""
        INSERT INTO products (item_number, description, prod_line, prod_type, category)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(item_number) DO UPDATE SET
            description=excluded.description,
            prod_line=excluded.prod_line,
            prod_type=excluded.prod_type,
            category=COALESCE(excluded.category, category)
    """, (item_number, description, prod_line, prod_type, category))
    conn.commit()
    row = conn.execute("SELECT id FROM products WHERE item_number=?",
                       (item_number,)).fetchone()
    conn.close()
    return row["id"]


# ── Sales ─────────────────────────────────────────────────────────────────────

def insert_sale(account_id: int, product_id: int, prod_line: str,
                units: int, revenue: float, report_date: str,
                tracking: str = None, carrier: str = None) -> bool:
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
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.description, p.prod_line, p.prod_type, p.item_number,
               COALESCE(p.category,
                 CASE
                   WHEN upper(p.item_number) LIKE '%QC%'
                     OR lower(p.description) LIKE '%quality control%'
                     OR lower(p.description) LIKE '%control material%'
                   THEN 'qc'
                   WHEN p.prod_type = 'Instrument'
                     OR lower(p.description) LIKE '%analyzer%'
                   THEN 'instrument'
                   ELSE 'cartridge'
                 END
               ) as category,
               SUM(s.units) as total_units,
               SUM(s.revenue) as total_revenue,
               MAX(s.report_date) as last_order_date
        FROM sales s
        JOIN products p ON s.product_id = p.id
        WHERE s.account_id = ? AND s.report_date >= ?
        GROUP BY p.id
        ORDER BY total_revenue DESC
    """, (account_id, since)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_cartridge_summary(account_id: int, days: int = 90) -> dict:
    """Returns {'cartridges': [...], 'qc': [...]} for the account homepage tally."""
    all_sales = get_account_sales_summary(account_id, days)
    cartridges = [s for s in all_sales if s["category"] == "cartridge"]
    qc = [s for s in all_sales if s["category"] == "qc"]
    other = [s for s in all_sales if s["category"] not in ("cartridge", "qc")]
    return {
        "cartridges": cartridges,
        "qc": qc,
        "other": other,
        "total_cartridge_units": sum(s["total_units"] or 0 for s in cartridges),
        "total_cartridge_revenue": sum(s["total_revenue"] or 0 for s in cartridges),
        "total_qc_units": sum(s["total_units"] or 0 for s in qc),
        "total_qc_revenue": sum(s["total_revenue"] or 0 for s in qc),
    }


def get_account_last_order_date(account_id: int) -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT MAX(report_date) as last FROM sales WHERE account_id=?",
        (account_id,)
    ).fetchone()
    conn.close()
    return row["last"] if row else None


def get_recent_orders(account_id: int, limit: int = 15) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT s.report_date, s.units, s.revenue, s.tracking, s.carrier,
               p.description, p.prod_line, p.item_number,
               COALESCE(p.category,
                 CASE
                   WHEN upper(p.item_number) LIKE '%QC%'
                     OR lower(p.description) LIKE '%quality control%'
                   THEN 'qc'
                   ELSE 'cartridge'
                 END
               ) as category
        FROM sales s
        JOIN products p ON s.product_id = p.id
        WHERE s.account_id = ?
        ORDER BY s.report_date DESC, s.revenue DESC
        LIMIT ?
    """, (account_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_accounts_sales_summary() -> list[dict]:
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
        LIMIT 30
    """, (account_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── TEG Machine Inventory ─────────────────────────────────────────────────────

def get_tegs(account_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT m.*,
               GROUP_CONCAT(c.cartridge_type, '||') as cartridge_types_raw
        FROM teg_machines m
        LEFT JOIN teg_cartridges c ON c.teg_id = m.id AND c.is_active = 1
        WHERE m.account_id = ? AND m.is_active = 1
        GROUP BY m.id
        ORDER BY m.department, m.location
    """, (account_id,)).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        raw = d.pop("cartridge_types_raw", None)
        d["cartridge_types"] = raw.split("||") if raw else []
        result.append(d)
    return result


def add_teg(account_id: int, location: str, department: str = None,
            serial_number: str = None, model: str = None, notes: str = None) -> int:
    conn = get_conn()
    c = conn.execute("""
        INSERT INTO teg_machines (account_id, location, department, serial_number, model, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (account_id, location, department, serial_number, model, notes))
    conn.commit()
    teg_id = c.lastrowid
    conn.close()
    return teg_id


def update_teg(teg_id: int, **kwargs):
    allowed = {"location", "department", "serial_number", "model", "notes", "is_active"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    conn = get_conn()
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE teg_machines SET {sets}, updated_at=datetime('now') WHERE id=?",
                 (*fields.values(), teg_id))
    conn.commit()
    conn.close()


def delete_teg(teg_id: int):
    conn = get_conn()
    conn.execute("UPDATE teg_machines SET is_active=0 WHERE id=?", (teg_id,))
    conn.commit()
    conn.close()


def set_teg_cartridges(teg_id: int, cartridge_types: list[str]):
    """Replace all cartridge types for a TEG machine."""
    conn = get_conn()
    conn.execute("DELETE FROM teg_cartridges WHERE teg_id=?", (teg_id,))
    for ct in cartridge_types:
        ct = ct.strip()
        if ct:
            try:
                conn.execute(
                    "INSERT INTO teg_cartridges (teg_id, cartridge_type) VALUES (?, ?)",
                    (teg_id, ct)
                )
            except sqlite3.IntegrityError:
                pass
    conn.commit()
    conn.close()


def get_account_teg_count(account_id: int) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as n FROM teg_machines WHERE account_id=? AND is_active=1",
        (account_id,)
    ).fetchone()
    conn.close()
    return row["n"] if row else 0


# ── Communications ────────────────────────────────────────────────────────────

def log_communication(account_id: int, comm_type: str, occurred_at: str,
                      contact_id: int = None, notes: str = None,
                      duration_sec: int = None, thread_id: str = None,
                      message_preview: str = None, is_from_me: int = 1) -> int:
    conn = get_conn()
    c = conn.execute("""
        INSERT INTO communications
            (account_id, contact_id, type, occurred_at, duration_sec,
             notes, thread_id, message_preview, is_from_me)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (account_id, contact_id, comm_type, occurred_at, duration_sec,
          notes, thread_id, message_preview, is_from_me))
    conn.commit()
    comm_id = c.lastrowid
    conn.close()
    return comm_id


def get_account_communications(account_id: int, limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT cm.*, c.name as contact_name, c.role as contact_role
        FROM communications cm
        LEFT JOIN contacts c ON cm.contact_id = c.id
        WHERE cm.account_id = ?
        ORDER BY cm.occurred_at DESC
        LIMIT ?
    """, (account_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_comm_stats_per_contact(account_id: int) -> list[dict]:
    """Frequency stats per contact for the comm activity panel."""
    conn = get_conn()
    now_30 = (datetime.now() - timedelta(days=30)).isoformat()
    now_7 = (datetime.now() - timedelta(days=7)).isoformat()

    rows = conn.execute("""
        SELECT
            c.id          as contact_id,
            c.name        as contact_name,
            c.role        as contact_role,
            c.phone       as contact_phone,
            c.imessage_handle,
            COUNT(cm.id)  as total_comms,
            MAX(cm.occurred_at) as last_contact,
            SUM(CASE WHEN cm.occurred_at >= ? THEN 1 ELSE 0 END) as comms_30d,
            SUM(CASE WHEN cm.occurred_at >= ? THEN 1 ELSE 0 END) as comms_7d,
            MAX(CASE WHEN cm.type IN ('imessage','text') THEN cm.occurred_at END) as last_text,
            MAX(CASE WHEN cm.type = 'call' THEN cm.occurred_at END) as last_call,
            MAX(CASE WHEN cm.type = 'visit' THEN cm.occurred_at END) as last_visit
        FROM contacts c
        LEFT JOIN communications cm ON cm.contact_id = c.id AND cm.account_id = ?
        WHERE c.account_id = ?
        GROUP BY c.id
        ORDER BY last_contact DESC NULLS LAST, c.name
    """, (now_30, now_7, account_id, account_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def imessage_already_synced(thread_id: str, occurred_at: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM communications WHERE thread_id=? AND occurred_at=? AND type='imessage'",
        (thread_id, occurred_at)
    ).fetchone()
    conn.close()
    return row is not None


# ── OneDrive Files ────────────────────────────────────────────────────────────

def upsert_onedrive_file(account_id: int, file_id: str, name: str,
                         web_url: str = None, size: int = None,
                         modified_at: str = None, mime_type: str = None):
    conn = get_conn()
    conn.execute("""
        INSERT INTO onedrive_files (account_id, file_id, name, web_url, size, modified_at, mime_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, file_id) DO UPDATE SET
            name=excluded.name, web_url=excluded.web_url,
            size=excluded.size, modified_at=excluded.modified_at
    """, (account_id, file_id, name, web_url, size, modified_at, mime_type))
    conn.commit()
    conn.close()


def get_onedrive_files(account_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM onedrive_files WHERE account_id=?
        ORDER BY modified_at DESC
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
    conn.execute("UPDATE unmatched_accounts SET resolved_to=? WHERE raw_name=?",
                 (account_id, raw_name))
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
                    "message": (f"{acct['name']}: {pct:.1f}% of monthly target — "
                                f"${shortfall:,.0f} gap remaining"),
                })

        last_order = get_account_last_order_date(acct_id)
        if last_order:
            days_since = (today - date.fromisoformat(last_order)).days
            if days_since >= config.REORDER_ALERT_DAYS:
                alerts.append({
                    "level": "warning",
                    "account_id": acct_id,
                    "account_name": acct["name"],
                    "type": "reorder",
                    "message": (f"{acct['name']}: no orders in {days_since} days — "
                                f"reorder likely due"),
                })

    alerts.sort(key=lambda a: (0 if a["level"] == "critical" else 1, a["account_name"]))
    return alerts


# ── Dashboard Summary ─────────────────────────────────────────────────────────

def get_dashboard_data() -> dict:
    accounts = get_all_accounts()
    systems = get_all_systems()
    sales_summary = get_all_accounts_sales_summary()
    sales_by_id = {r["id"]: r for r in sales_summary}
    unmatched = get_unmatched()

    for acct in accounts:
        summary = sales_by_id.get(acct["id"], {})
        acct["revenue_30d"] = summary.get("revenue_30d", 0)
        acct["units_30d"] = summary.get("units_30d", 0)
        acct["last_order"] = summary.get("last_order")
        acct["teg_count"] = get_account_teg_count(acct["id"])
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
