"""SQL for brand research: brands, searches, per-search items, rejected history and supplier prices."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime

SEARCH_COLUMNS = {
    "status", "phase", "message", "progress_done", "progress_total", "pages_processed", "discovery_complete",
    "criteria_fingerprint", "started_at", "finished_at", "error", "reevaluate_rejected",
}
ITEM_COLUMNS = {
    "title", "page", "position", "sponsored", "search_snapshot", "relevance", "stage", "outcome", "was_known",
    "product_id", "reasons", "error",
}
ACTIVE_STATUSES = ("queued", "running")


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def brand_key(name: str | None) -> str:
    """Case- and punctuation-insensitive brand identity: "L'Oréal Paris" -> "lorealparis"."""
    import unicodedata

    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _json(value):
    return json.dumps(value) if isinstance(value, (list, dict)) else value


def _decode(row: sqlite3.Row | None, *json_cols: str) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    for col in json_cols:
        if data.get(col):
            try:
                data[col] = json.loads(data[col])
            except (TypeError, ValueError):
                pass
    return data


class ResearchRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ------------------------------------------------------------ brands
    def get_or_create_brand(self, name: str) -> dict:
        key = brand_key(name)
        row = self.conn.execute("SELECT * FROM brands WHERE name_key = ?", (key,)).fetchone()
        if row:
            return dict(row)
        cur = self.conn.execute("INSERT INTO brands (name, name_key, created_at) VALUES (?, ?, ?)",
                                (name.strip(), key, now_iso()))
        return dict(self.conn.execute("SELECT * FROM brands WHERE id = ?", (cur.lastrowid,)).fetchone())

    def get_brand(self, brand_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM brands WHERE id = ?", (brand_id,)).fetchone()
        return dict(row) if row else None

    def touch_brand(self, brand_id: int) -> None:
        self.conn.execute("UPDATE brands SET last_analyzed_at = ? WHERE id = ?", (now_iso(), brand_id))

    # ---------------------------------------------------------- searches
    def create_search(self, brand_id: int, query: str, *, store_url: str | None, marketplace: str,
                      reevaluate_rejected: bool, criteria_fingerprint: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO brand_searches (brand_id, query, store_url, marketplace, reevaluate_rejected, status, phase, "
            "message, criteria_fingerprint, created_at) VALUES (?, ?, ?, ?, ?, 'queued', 'queued', ?, ?, ?)",
            (brand_id, query, store_url, marketplace, int(reevaluate_rejected), "Waiting to start…", criteria_fingerprint, now_iso()))
        return cur.lastrowid

    def get_search(self, search_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT s.*, b.name AS brand_name, b.name_key AS brand_key FROM brand_searches s JOIN brands b ON b.id = s.brand_id "
            "WHERE s.id = ?", (search_id,)).fetchone()
        return dict(row) if row else None

    def update_search(self, search_id: int, **fields) -> None:
        bad = set(fields) - SEARCH_COLUMNS
        if bad:
            raise ValueError(f"Unknown search columns: {sorted(bad)}")
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE brand_searches SET {sets} WHERE id = ?", [*fields.values(), search_id])

    def recent_searches(self, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT s.*, b.name AS brand_name FROM brand_searches s JOIN brands b ON b.id = s.brand_id "
            "ORDER BY s.created_at DESC, s.id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def searches_for_brand(self, brand_id: int) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM brand_searches WHERE brand_id = ? ORDER BY created_at DESC, id DESC", (brand_id,))
        return [dict(r) for r in rows]

    def brand_history(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT b.*, (SELECT id FROM brand_searches s WHERE s.brand_id = b.id ORDER BY s.created_at DESC, s.id DESC LIMIT 1) "
            "AS last_search_id, (SELECT COUNT(*) FROM brand_searches s WHERE s.brand_id = b.id) AS search_count "
            "FROM brands b ORDER BY COALESCE(b.last_analyzed_at, b.created_at) DESC")
        return [dict(r) for r in rows]

    def active_search(self) -> dict | None:
        row = self.conn.execute(
            f"SELECT * FROM brand_searches WHERE status IN ({','.join('?' * len(ACTIVE_STATUSES))}) ORDER BY id LIMIT 1",
            ACTIVE_STATUSES).fetchone()
        return dict(row) if row else None

    def queued_search_ids(self) -> list[int]:
        return [r[0] for r in self.conn.execute("SELECT id FROM brand_searches WHERE status = 'queued' ORDER BY id")]

    def mark_interrupted(self) -> int:
        """Called at start-up: a search that was running when the app stopped can be resumed."""
        return self.conn.execute(
            "UPDATE brand_searches SET status = 'interrupted', message = 'Stopped when the app closed — you can resume it.' "
            "WHERE status = 'running'").rowcount

    # ------------------------------------------------------------- items
    def upsert_item(self, search_id: int, asin: str, **fields) -> None:
        bad = set(fields) - ITEM_COLUMNS
        if bad:
            raise ValueError(f"Unknown item columns: {sorted(bad)}")
        fields = {k: _json(v) for k, v in fields.items()}
        existing = self.conn.execute("SELECT id FROM brand_search_items WHERE search_id = ? AND asin = ?", (search_id, asin)).fetchone()
        if existing:
            if fields:
                sets = ", ".join(f"{k} = ?" for k in fields)
                self.conn.execute(f"UPDATE brand_search_items SET {sets}, updated_at = ? WHERE id = ?",
                                  [*fields.values(), now_iso(), existing[0]])
        else:
            fields.setdefault("stage", "discovered")
            cols = ["search_id", "asin", *fields, "updated_at"]
            self.conn.execute(f"INSERT INTO brand_search_items ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                              [search_id, asin, *fields.values(), now_iso()])

    def items(self, search_id: int, stage: str | None = None) -> list[dict]:
        sql = "SELECT * FROM brand_search_items WHERE search_id = ?"
        params: list = [search_id]
        if stage:
            sql += " AND stage = ?"
            params.append(stage)
        rows = self.conn.execute(sql + " ORDER BY page, position, id", params)
        return [_decode(r, "search_snapshot", "reasons") for r in rows]

    def item(self, search_id: int, asin: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM brand_search_items WHERE search_id = ? AND asin = ?", (search_id, asin)).fetchone()
        return _decode(row, "search_snapshot", "reasons")

    def outcome_counts(self, search_id: int) -> dict:
        counts: dict[str, int] = {}
        for outcome, n in self.conn.execute(
                "SELECT COALESCE(outcome, stage), COUNT(*) FROM brand_search_items WHERE search_id = ? GROUP BY 1", (search_id,)):
            counts[outcome] = n
        counts["discovered"] = sum(counts.values())
        counts["previously_analyzed"] = self.conn.execute(
            "SELECT COUNT(*) FROM brand_search_items WHERE search_id = ? AND was_known = 1", (search_id,)).fetchone()[0]
        return counts

    # ---------------------------------------------------------- rejected
    def active_rejection(self, asin: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM rejected_products WHERE asin = ? AND active = 1", (asin.upper(),)).fetchone()
        return _decode(row, "reasons", "failed_rules", "criteria")

    def record_rejection(self, asin: str, *, product_id: int | None, brand: str | None, title: str | None, amazon_url: str | None,
                         reasons: list[str], failed_rules: list[dict], criteria: dict, criteria_fingerprint: str,
                         engine_version: str, search_id: int | None) -> None:
        self.conn.execute(
            "INSERT INTO rejected_products (asin, product_id, brand, title, amazon_url, reasons, failed_rules, criteria, "
            "criteria_fingerprint, engine_version, search_id, rejected_at, active, cleared_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL) "
            "ON CONFLICT(asin) DO UPDATE SET product_id = excluded.product_id, brand = excluded.brand, title = excluded.title, "
            "amazon_url = excluded.amazon_url, reasons = excluded.reasons, failed_rules = excluded.failed_rules, "
            "criteria = excluded.criteria, criteria_fingerprint = excluded.criteria_fingerprint, "
            "engine_version = excluded.engine_version, search_id = excluded.search_id, rejected_at = excluded.rejected_at, "
            "active = 1, cleared_at = NULL",
            (asin.upper(), product_id, brand, title, amazon_url, json.dumps(reasons), json.dumps(failed_rules),
             json.dumps(criteria), criteria_fingerprint, engine_version, search_id, now_iso()))

    def clear_rejection(self, asin: str) -> None:
        self.conn.execute("UPDATE rejected_products SET active = 0, cleared_at = ? WHERE asin = ? AND active = 1",
                          (now_iso(), asin.upper()))

    def rejected(self, *, brand_key_value: str | None = None, active_only: bool = True) -> list[dict]:
        sql = "SELECT r.* FROM rejected_products r"
        params: list = []
        clauses = []
        if active_only:
            clauses.append("r.active = 1")
        if brand_key_value:
            clauses.append("r.search_id IN (SELECT s.id FROM brand_searches s JOIN brands b ON b.id = s.brand_id WHERE b.name_key = ?)")
            params.append(brand_key_value)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = self.conn.execute(sql + " ORDER BY r.rejected_at DESC", params)
        return [_decode(r, "reasons", "failed_rules", "criteria") for r in rows]

    def rejected_under_other_criteria(self, fingerprint: str) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM rejected_products WHERE active = 1 AND criteria_fingerprint != ?",
                                 (fingerprint,)).fetchone()[0]

    # --------------------------------------------------- supplier prices
    def replace_supplier_prices(self, rows: list[dict], source_name: str) -> int:
        self.conn.execute("DELETE FROM supplier_prices")
        stamp = now_iso()
        self.conn.executemany(
            "INSERT INTO supplier_prices (asin, ean, supplier, product_name, cost, source_name, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(r.get("asin"), r.get("ean"), r.get("supplier"), r.get("product_name"), r["cost"], source_name, stamp) for r in rows])
        return len(rows)

    def supplier_price(self, asin: str | None, ean: str | None = None) -> dict | None:
        if asin:
            row = self.conn.execute("SELECT * FROM supplier_prices WHERE asin = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
                                    (asin.upper(),)).fetchone()
            if row:
                return {**dict(row), "matched_on": "ASIN"}
        if ean:
            row = self.conn.execute("SELECT * FROM supplier_prices WHERE ean = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
                                    (ean,)).fetchone()
            if row:
                return {**dict(row), "matched_on": "EAN"}
        return None

    def supplier_price_summary(self) -> dict:
        row = self.conn.execute("SELECT COUNT(*) AS n, MAX(updated_at) AS updated_at, MAX(source_name) AS source_name "
                                "FROM supplier_prices").fetchone()
        return dict(row)
