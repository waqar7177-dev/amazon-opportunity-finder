"""Data access. SQL lives here and nowhere else."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from ..domain.product import DATA_FIELDS, SNAPSHOT_FIELDS, Product
from ..domain.settings import Settings

EVAL_COLUMNS = [
    "status", "risk_level", "risk_score", "opportunity_score", "net_profit", "roi", "total_fees",
    "conservative_units", "conservative_profit", "theoretical_profit", "eval_json", "eval_fingerprint", "evaluated_at",
]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _row_to_product(row: sqlite3.Row) -> Product:
    data = dict(row)
    if isinstance(data.get("field_meta"), str):
        try:
            data["field_meta"] = json.loads(data["field_meta"])
        except ValueError:
            data["field_meta"] = None
    product = Product.from_mapping(data)
    if data.get("eval_json"):
        try:
            product.evaluation = json.loads(data["eval_json"])
        except (TypeError, ValueError):
            product.evaluation = None
    product._fingerprint = data.get("eval_fingerprint")  # type: ignore[attr-defined]
    return product


class SettingsRepository:
    KEY = "app_settings"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def load(self) -> Settings:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (self.KEY,)).fetchone()
        if not row:
            return Settings.defaults()
        try:
            return Settings.from_dict(json.loads(row["value"]))
        except (TypeError, ValueError):
            return Settings.defaults()

    def save(self, settings: Settings) -> None:
        self.conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (self.KEY, json.dumps(settings.to_dict()), now_iso()),
        )

    def reset(self) -> Settings:
        self.conn.execute("DELETE FROM settings WHERE key = ?", (self.KEY,))
        return Settings.defaults()

    def updated_at(self) -> str | None:
        row = self.conn.execute("SELECT updated_at FROM settings WHERE key = ?", (self.KEY,)).fetchone()
        return row["updated_at"] if row else None


class ProductRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ------------------------------------------------------------- reads
    def get(self, product_id: int) -> Product | None:
        row = self.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return _row_to_product(row) if row else None

    def all(self, include_archived: bool = False) -> list[Product]:
        sql = "SELECT * FROM products"
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY id"
        return [_row_to_product(r) for r in self.conn.execute(sql)]

    def count(self, include_archived: bool = False) -> int:
        sql = "SELECT COUNT(*) FROM products" + ("" if include_archived else " WHERE archived = 0")
        return self.conn.execute(sql).fetchone()[0]

    def categories(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != '' AND archived = 0 "
            "ORDER BY category COLLATE NOCASE")
        return [r[0] for r in rows]

    def find_by_asin(self, asin: str, exclude_id: int | None = None) -> list[Product]:
        return self._find("UPPER(asin) = UPPER(?)", (asin,), exclude_id)

    def find_by_url(self, url: str, exclude_id: int | None = None) -> list[Product]:
        return self._find("LOWER(RTRIM(amazon_url, '/')) = LOWER(RTRIM(?, '/'))", (url,), exclude_id)

    def find_by_title_brand(self, title: str, brand: str | None, exclude_id: int | None = None) -> list[Product]:
        if brand:
            return self._find("LOWER(TRIM(title)) = LOWER(TRIM(?)) AND LOWER(TRIM(COALESCE(brand, ''))) = LOWER(TRIM(?))",
                              (title, brand), exclude_id)
        return self._find("LOWER(TRIM(title)) = LOWER(TRIM(?)) AND (brand IS NULL OR TRIM(brand) = '')", (title,), exclude_id)

    def _find(self, where: str, params: tuple, exclude_id: int | None) -> list[Product]:
        sql = f"SELECT * FROM products WHERE {where}"
        if exclude_id is not None:
            sql += " AND id != ?"
            params = (*params, exclude_id)
        return [_row_to_product(r) for r in self.conn.execute(sql + " ORDER BY id", params)]

    # ------------------------------------------------------------ writes
    def insert(self, product: Product) -> int:
        stamp = now_iso()
        data = product.data_dict()
        data["created_at"] = product.created_at or stamp
        data["updated_at"] = stamp
        data["amazon_checked_at"] = product.amazon_checked_at or stamp
        data["archived"] = int(product.archived)
        cols = list(data)
        cur = self.conn.execute(
            f"INSERT INTO products ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [_db_value(data[c]) for c in cols],
        )
        return cur.lastrowid

    def update(self, product_id: int, product: Product, amazon_checked: bool) -> None:
        data = product.data_dict()
        data["updated_at"] = now_iso()
        if amazon_checked:
            data["amazon_checked_at"] = data["updated_at"]
        sets = ", ".join(f"{c} = ?" for c in data)
        self.conn.execute(f"UPDATE products SET {sets} WHERE id = ?", [*map(_db_value, data.values()), product_id])

    def set_archived(self, product_id: int, archived: bool) -> None:
        self.conn.execute("UPDATE products SET archived = ?, updated_at = ? WHERE id = ?",
                          (int(archived), now_iso(), product_id))

    def delete(self, product_id: int) -> bool:
        return self.conn.execute("DELETE FROM products WHERE id = ?", (product_id,)).rowcount > 0

    def save_evaluation(self, product_id: int, evaluation: dict, fingerprint: str) -> None:
        p = evaluation["profit"]
        values = {
            "status": evaluation["status"],
            "risk_level": evaluation["risk"]["level"],
            "risk_score": evaluation["risk"]["score"],
            "opportunity_score": evaluation["score"]["total"] if evaluation.get("score") else None,
            "net_profit": p["net_profit"],
            "roi": p["roi_pct"],
            "total_fees": evaluation["fees"]["total_fees"],
            "conservative_units": p["conservative_units"],
            "conservative_profit": p["conservative_monthly_profit"],
            "theoretical_profit": p["theoretical_monthly_profit"],
            "eval_json": json.dumps(evaluation),
            "eval_fingerprint": fingerprint,
            "evaluated_at": now_iso(),
        }
        sets = ", ".join(f"{c} = ?" for c in values)
        self.conn.execute(f"UPDATE products SET {sets} WHERE id = ?", [*values.values(), product_id])

    # ----------------------------------------------------------- history
    def add_snapshot(self, product_id: int, product: Product, source: str) -> None:
        values = [getattr(product, f) for f in SNAPSHOT_FIELDS]
        last = self.conn.execute(
            f"SELECT {', '.join(SNAPSHOT_FIELDS)} FROM product_snapshots WHERE product_id = ? "
            "ORDER BY captured_at DESC, id DESC LIMIT 1", (product_id,)).fetchone()
        if last is not None and list(last) == values:
            return
        self.conn.execute(
            f"INSERT INTO product_snapshots (product_id, captured_at, source, {', '.join(SNAPSHOT_FIELDS)}) "
            f"VALUES (?, ?, ?, {', '.join('?' for _ in SNAPSHOT_FIELDS)})",
            [product_id, now_iso(), source, *values],
        )

    def snapshots(self, product_id: int, limit: int = 50) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM product_snapshots WHERE product_id = ? ORDER BY captured_at DESC, id DESC "
                                 "LIMIT ?", (product_id, limit))
        return [dict(r) for r in rows]

    def add_evaluation_record(self, product_id: int, evaluation: dict, trigger: str) -> None:
        p = evaluation["profit"]
        self.conn.execute(
            "INSERT INTO evaluations (product_id, evaluated_at, trigger, status, risk_level, opportunity_score, "
            "net_profit, roi, conservative_profit, summary_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (product_id, now_iso(), trigger, evaluation["status"], evaluation["risk"]["level"],
             evaluation["score"]["total"] if evaluation.get("score") else None,
             p["net_profit"], p["roi_pct"], p["conservative_monthly_profit"], json.dumps(evaluation["summary"])),
        )

    def last_evaluation_record(self, product_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM evaluations WHERE product_id = ? ORDER BY evaluated_at DESC, id DESC LIMIT 1",
                                (product_id,)).fetchone()
        return dict(row) if row else None

    def evaluation_history(self, product_id: int, limit: int = 30) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM evaluations WHERE product_id = ? ORDER BY evaluated_at DESC, id DESC LIMIT ?",
                                 (product_id, limit))
        out = []
        for r in rows:
            item = dict(r)
            item["summary"] = json.loads(item.pop("summary_json") or "[]")
            out.append(item)
        return out


def _db_value(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


__all__ = ["ProductRepository", "SettingsRepository", "DATA_FIELDS", "now_iso"]
