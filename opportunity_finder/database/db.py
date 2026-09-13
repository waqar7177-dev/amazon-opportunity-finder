"""SQLite connection, schema and migrations.

The schema is versioned in the ``meta`` table. ``CREATE TABLE IF NOT EXISTS``
never adds a column to an existing table, so every schema change after v1 must
be a numbered migration in ``MIGRATIONS``.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    asin                  TEXT,
    title                 TEXT,
    brand                 TEXT,
    category              TEXT,
    fee_category          TEXT NOT NULL DEFAULT 'everything_else',
    amazon_url            TEXT,
    selling_price         REAL CHECK (selling_price IS NULL OR selling_price >= 0),
    bsr                   INTEGER CHECK (bsr IS NULL OR bsr > 0),
    bsr_category          TEXT,
    monthly_sales         INTEGER CHECK (monthly_sales IS NULL OR monthly_sales >= 0),
    total_sellers         INTEGER CHECK (total_sellers IS NULL OR total_sellers >= 0),
    fba_sellers           INTEGER CHECK (fba_sellers IS NULL OR fba_sellers >= 0),
    sourcing_price        REAL CHECK (sourcing_price IS NULL OR sourcing_price >= 0),
    supplier              TEXT,
    shipping_prep         REAL CHECK (shipping_prep IS NULL OR shipping_prep >= 0),
    other_costs           REAL CHECK (other_costs IS NULL OR other_costs >= 0),
    weight_g              REAL CHECK (weight_g IS NULL OR weight_g > 0),
    length_cm             REAL,
    width_cm              REAL,
    height_cm             REAL,
    fulfilment            TEXT NOT NULL DEFAULT 'FBA',
    referral_fee_override REAL,
    fba_fee_override      REAL,
    restriction_status    TEXT NOT NULL DEFAULT 'unknown',
    flag_hazmat           INTEGER NOT NULL DEFAULT 0,
    flag_battery          INTEGER NOT NULL DEFAULT 0,
    flag_liquid           INTEGER NOT NULL DEFAULT 0,
    flag_fragile          INTEGER NOT NULL DEFAULT 0,
    flag_seasonal         INTEGER NOT NULL DEFAULT 0,
    flag_amazon_sells     INTEGER NOT NULL DEFAULT 0,
    flag_ip_concern       INTEGER NOT NULL DEFAULT 0,
    notes                 TEXT,
    source                TEXT NOT NULL DEFAULT 'manual',
    archived              INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    amazon_checked_at     TEXT,
    evaluated_at          TEXT,
    -- Cached result of the latest evaluation (recomputed whenever it is stale).
    status                TEXT,
    risk_level            TEXT,
    risk_score            INTEGER,
    opportunity_score     INTEGER,
    net_profit            REAL,
    roi                   REAL,
    total_fees            REAL,
    conservative_units    INTEGER,
    conservative_profit   REAL,
    theoretical_profit    REAL,
    eval_json             TEXT,
    eval_fingerprint      TEXT
);
CREATE INDEX IF NOT EXISTS ix_products_asin     ON products(asin);
CREATE INDEX IF NOT EXISTS ix_products_status   ON products(status);
CREATE INDEX IF NOT EXISTS ix_products_archived ON products(archived);

CREATE TABLE IF NOT EXISTS product_snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id     INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    captured_at    TEXT NOT NULL,
    selling_price  REAL,
    bsr            INTEGER,
    total_sellers  INTEGER,
    fba_sellers    INTEGER,
    monthly_sales  INTEGER,
    sourcing_price REAL,
    source         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_snapshots_product ON product_snapshots(product_id, captured_at);

CREATE TABLE IF NOT EXISTS evaluations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id          INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    evaluated_at        TEXT NOT NULL,
    trigger             TEXT NOT NULL,
    status              TEXT NOT NULL,
    risk_level          TEXT NOT NULL,
    opportunity_score   INTEGER,
    net_profit          REAL,
    roi                 REAL,
    conservative_profit REAL,
    summary_json        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evaluations_product ON evaluations(product_id, evaluated_at);
"""

REQUIRED_TABLES = {"meta", "settings", "products", "product_snapshots", "evaluations"}

# version -> SQL (or callable taking a connection). Append new versions here.
MIGRATIONS: dict[int, str] = {}


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10, detect_types=0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(path: Path | str) -> None:
    """Create the database (and its folder) if needed, then apply pending migrations."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA_V1)
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        current = int(row["value"]) if row else 0
        if current == 0:
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            current = SCHEMA_VERSION
        for version in sorted(v for v in MIGRATIONS if v > current):
            step = MIGRATIONS[version]
            if callable(step):
                step(conn)
            else:
                conn.executescript(step)
            conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(version),))
        conn.commit()
    finally:
        conn.close()


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row["value"]) if row else 0


def looks_like_our_database(path: Path | str) -> tuple[bool, str]:
    """Used before restoring a backup: is this file a SQLite database with our tables?"""
    try:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return False, "The file could not be opened as a database."
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not REQUIRED_TABLES <= names:
            return False, "This file is not an Opportunity Finder backup (required tables are missing)."
        version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if not version or int(version[0]) > SCHEMA_VERSION:
            return False, "This backup was made by a newer version of the app."
        conn.execute("PRAGMA integrity_check").fetchone()
        return True, "ok"
    except sqlite3.DatabaseError:
        return False, "The file is not a valid SQLite database."
    finally:
        conn.close()
