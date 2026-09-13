"""Product lifecycle: create, update, merge, duplicate, archive, delete — and keeping evaluations fresh.

Evaluations are cached on the product row with a fingerprint of everything that
can change the result (engine version, fee table, settings, the product itself
and today's date — stale-data and peak-fee checks depend on the date). A stale
fingerprint is recomputed on read, so a settings change can never leave an old
status on screen.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import date
from typing import Callable

from ..constants import ENGINE_VERSION, FLAG_KEYS, SOURCE_MANUAL
from ..database.repositories import ProductRepository, SettingsRepository
from ..domain.product import DATA_FIELDS, MARKET_FIELDS, Product
from ..domain.settings import Settings
from ..fees.engine import load_fee_table
from .evaluator import evaluate

RECORD_TRIGGERS = {"created", "edited", "manual", "import", "merged"}


class ProductNotFound(LookupError):
    pass


class ProductService:
    def __init__(self, conn: sqlite3.Connection, today: Callable[[], date] = date.today):
        self.conn = conn
        self.repo = ProductRepository(conn)
        self.settings_repo = SettingsRepository(conn)
        self._today = today
        self._settings: Settings | None = None

    # ---------------------------------------------------------- settings
    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = self.settings_repo.load()
        return self._settings

    def save_settings(self, settings: Settings) -> int:
        self.settings_repo.save(settings)
        self._settings = settings
        changed = self.refresh(force=False)
        self.conn.commit()
        return changed

    def reset_settings(self) -> int:
        self._settings = self.settings_repo.reset()
        changed = self.refresh(force=False)
        self.conn.commit()
        return changed

    # -------------------------------------------------------- evaluation
    def fingerprint(self, product: Product) -> str:
        parts = [ENGINE_VERSION, load_fee_table()["version"], self.settings.fingerprint(),
                 product.updated_at or "", product.amazon_checked_at or "", self._today().isoformat()]
        return hashlib.sha1("|".join(parts).encode()).hexdigest()[:20]

    def evaluate_product(self, product: Product) -> dict:
        return evaluate(product, self.settings, self._today())

    def _store(self, product: Product, trigger: str) -> dict:
        evaluation = self.evaluate_product(product)
        self.repo.save_evaluation(product.id, evaluation, self.fingerprint(product))
        last = self.repo.last_evaluation_record(product.id)
        changed = last is None or (
            last["status"], last["risk_level"], last["opportunity_score"], last["net_profit"], last["conservative_profit"]
        ) != (
            evaluation["status"], evaluation["risk"]["level"],
            evaluation["score"]["total"] if evaluation.get("score") else None,
            evaluation["profit"]["net_profit"], evaluation["profit"]["conservative_monthly_profit"],
        )
        if changed or trigger in RECORD_TRIGGERS:
            self.repo.add_evaluation_record(product.id, evaluation, trigger)
        product.evaluation = evaluation
        return evaluation

    def refresh(self, force: bool = False, trigger: str = "auto") -> int:
        """Re-evaluate products whose cached result is stale (or all when ``force``)."""
        count = 0
        for product in self.repo.all(include_archived=True):
            if force or product.evaluation is None or getattr(product, "_fingerprint", None) != self.fingerprint(product):
                self._store(product, trigger)
                count += 1
        return count

    def reevaluate(self, product_id: int) -> dict:
        product = self.get(product_id)
        evaluation = self._store(product, "manual")
        self.conn.commit()
        return evaluation

    def reevaluate_all(self) -> int:
        count = self.refresh(force=True, trigger="manual")
        self.conn.commit()
        return count

    # -------------------------------------------------------------- reads
    def get(self, product_id: int) -> Product:
        product = self.repo.get(product_id)
        if product is None:
            raise ProductNotFound(product_id)
        if product.evaluation is None or getattr(product, "_fingerprint", None) != self.fingerprint(product):
            self._store(product, "auto")
            self.conn.commit()
        return product

    def items(self, include_archived: bool = False) -> list[dict]:
        if self.refresh():
            self.conn.commit()
        return [{"product": p, "evaluation": p.evaluation} for p in self.repo.all(include_archived=include_archived)]

    def history(self, product_id: int) -> dict:
        return {"snapshots": self.repo.snapshots(product_id), "evaluations": self.repo.evaluation_history(product_id)}

    # ------------------------------------------------------------- writes
    def create(self, product: Product, source: str | None = None, commit: bool = True) -> int:
        if source:
            product.source = source
        product.id = None
        new_id = self.repo.insert(product)
        stored = self.repo.get(new_id)
        self.repo.add_snapshot(new_id, stored, stored.source)
        self._store(stored, "import" if stored.source == "import" else "created")
        if commit:
            self.conn.commit()
        return new_id

    def update(self, product_id: int, incoming: Product, mark_checked: bool = False, commit: bool = True) -> Product:
        existing = self.get(product_id)
        incoming.source = existing.source if incoming.source in (None, "", SOURCE_MANUAL) else incoming.source
        market_changed = any(getattr(existing, f) != getattr(incoming, f) for f in MARKET_FIELDS)
        self.repo.update(product_id, incoming, amazon_checked=market_changed or mark_checked)
        stored = self.repo.get(product_id)
        self.repo.add_snapshot(product_id, stored, "edit")
        self._store(stored, "edited")
        if commit:
            self.conn.commit()
        return stored

    def merge(self, product_id: int, incoming: Product, provided: set[str] | None = None,
              source: str = SOURCE_MANUAL, commit: bool = True) -> Product:
        """Update an existing product with new values. Blank incoming values keep what is stored.

        ``provided`` lists the flag fields the caller really supplied (a form always supplies them;
        an import only when the column exists)."""
        existing = self.get(product_id)
        merged = Product.from_mapping({**existing.__dict__})
        for name in DATA_FIELDS:
            value = getattr(incoming, name)
            if name in FLAG_KEYS:
                if provided is None or name in provided:
                    setattr(merged, name, value)
            elif name in ("source",):
                continue
            elif name in ("fee_category", "fulfilment", "restriction_status"):
                if provided is None or name in provided:
                    setattr(merged, name, value)
            elif value not in (None, ""):
                setattr(merged, name, value)
        merged.source = source
        market_changed = any(getattr(existing, f) != getattr(merged, f) for f in MARKET_FIELDS)
        self.repo.update(product_id, merged, amazon_checked=market_changed or source != SOURCE_MANUAL)
        stored = self.repo.get(product_id)
        self.repo.add_snapshot(product_id, stored, source)
        self._store(stored, "merged")
        if commit:
            self.conn.commit()
        return stored

    def duplicate(self, product_id: int) -> int:
        original = self.get(product_id)
        copy = Product.from_mapping({k: getattr(original, k) for k in DATA_FIELDS})
        copy.title = f"{original.title} (copy)" if original.title else "(copy)"
        copy.source = SOURCE_MANUAL
        copy.amazon_checked_at = original.amazon_checked_at
        return self.create(copy)

    def set_archived(self, product_id: int, archived: bool) -> None:
        self.get(product_id)
        self.repo.set_archived(product_id, archived)
        self.conn.commit()

    def delete(self, product_id: int) -> bool:
        deleted = self.repo.delete(product_id)
        self.conn.commit()
        return deleted
