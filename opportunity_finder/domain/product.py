"""The product record: everything a seller enters or imports about one listing.

Values are None when unknown. None is never silently turned into a number —
the evaluator decides what a missing value means and says so.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

from ..constants import FBA, FLAG_KEYS, RESTRICTION_UNKNOWN, SOURCE_MANUAL

# Columns stored in the products table that hold user/provider data
# (as opposed to cached evaluation results).
DATA_FIELDS = [
    "asin", "title", "brand", "category", "fee_category", "amazon_url",
    "selling_price", "bsr", "bsr_category", "monthly_sales", "total_sellers", "fba_sellers",
    "sourcing_price", "supplier", "shipping_prep", "other_costs",
    "weight_g", "length_cm", "width_cm", "height_cm",
    "fulfilment", "referral_fee_override", "fba_fee_override",
    "restriction_status", *FLAG_KEYS, "notes", "source",
]

# Values that describe the Amazon listing itself; a change to any of them refreshes
# "Amazon data last checked" and records a history snapshot.
MARKET_FIELDS = ["selling_price", "bsr", "monthly_sales", "total_sellers", "fba_sellers"]
SNAPSHOT_FIELDS = MARKET_FIELDS + ["sourcing_price"]


@dataclass
class Product:
    id: int | None = None
    asin: str | None = None
    title: str | None = None
    brand: str | None = None
    category: str | None = None
    fee_category: str = "everything_else"
    amazon_url: str | None = None

    selling_price: float | None = None
    bsr: int | None = None
    bsr_category: str | None = None
    monthly_sales: int | None = None
    total_sellers: int | None = None
    fba_sellers: int | None = None

    sourcing_price: float | None = None
    supplier: str | None = None
    shipping_prep: float | None = None
    other_costs: float | None = None

    weight_g: float | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None

    fulfilment: str = FBA
    referral_fee_override: float | None = None
    fba_fee_override: float | None = None

    restriction_status: str = RESTRICTION_UNKNOWN
    flag_hazmat: bool = False
    flag_battery: bool = False
    flag_liquid: bool = False
    flag_fragile: bool = False
    flag_seasonal: bool = False
    flag_amazon_sells: bool = False
    flag_ip_concern: bool = False

    notes: str | None = None
    source: str = SOURCE_MANUAL
    archived: bool = False

    created_at: str | None = None
    updated_at: str | None = None
    amazon_checked_at: str | None = None
    evaluated_at: str | None = None

    # Cached evaluation, filled from the database row when present.
    evaluation: dict | None = field(default=None, repr=False)

    @classmethod
    def from_mapping(cls, data: dict) -> "Product":
        names = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in names and k != "evaluation"}
        for key in FLAG_KEYS + ["archived"]:
            if key in kwargs:
                kwargs[key] = bool(kwargs[key])
        product = cls(**kwargs)
        if data.get("fee_category") in (None, ""):
            product.fee_category = "everything_else"
        if not product.fulfilment:
            product.fulfilment = FBA
        if not product.restriction_status:
            product.restriction_status = RESTRICTION_UNKNOWN
        return product

    def data_dict(self) -> dict:
        full = asdict(self)
        return {k: full[k] for k in DATA_FIELDS}

    @property
    def display_name(self) -> str:
        if self.title:
            return self.title
        if self.asin:
            return f"ASIN {self.asin}"
        return f"Product #{self.id}" if self.id else "Untitled product"

    @property
    def flags(self) -> list[str]:
        return [key for key in FLAG_KEYS if getattr(self, key)]
