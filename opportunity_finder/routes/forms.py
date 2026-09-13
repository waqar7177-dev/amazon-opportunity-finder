"""Helpers shared by the product form views."""
from __future__ import annotations

import json
from urllib.parse import urlparse

from flask import request

from ..constants import FLAG_KEYS, FULFILMENT_LABELS, RESTRICTION_LABELS, RISK_FLAGS
from ..domain.product import DATA_FIELDS, Product
from ..fees.engine import describe_referral_category, referral_categories

MONEY_FIELDS = {"selling_price", "sourcing_price", "shipping_prep", "other_costs", "referral_fee_override", "fba_fee_override"}


def _plain_number(value) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def product_to_form(product: Product) -> dict:
    values = {}
    for name in DATA_FIELDS:
        value = getattr(product, name)
        if name in FLAG_KEYS:
            values[name] = bool(value)
        elif value is None:
            values[name] = ""
        elif name in MONEY_FIELDS:
            values[name] = f"{value:.2f}"
        else:
            values[name] = _plain_number(value)
    return values


def submitted_form() -> dict:
    values = {name: request.form.get(name, "") for name in DATA_FIELDS if name not in FLAG_KEYS}
    values.update({name: bool(request.form.get(name)) for name in FLAG_KEYS})
    return values


def extracted_from_form() -> dict:
    try:
        data = json.loads(request.form.get("extracted_json") or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def form_context(values: dict, errors: dict | None = None, warnings: dict | None = None, **extra) -> dict:
    return {
        "values": values,
        "errors": errors or {},
        "warnings": warnings or {},
        "fee_categories": [{**c, "rate_text": describe_referral_category(c)} for c in referral_categories()],
        "restriction_labels": RESTRICTION_LABELS,
        "fulfilment_labels": FULFILMENT_LABELS,
        "risk_flags": RISK_FLAGS,
        **extra,
    }


def safe_next(default: str) -> str:
    target = request.form.get("next") or request.args.get("next") or ""
    parsed = urlparse(target)
    if target.startswith("/") and not target.startswith("//") and not parsed.netloc:
        return target
    return default
