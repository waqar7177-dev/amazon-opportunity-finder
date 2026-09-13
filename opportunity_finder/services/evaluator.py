"""Evaluate one product: fees -> profit -> rules -> risk -> verification -> status -> score.

A pure function of (product, settings, date). The database layer caches its
output, but never computes any of it on its own.
"""
from __future__ import annotations

from datetime import date, datetime

from ..constants import (FBA, HIGH_RISK, INCOMPLETE, NEEDS_VERIFICATION, QUALIFIED, REJECTED, RESTRICTION_CHECK,
                         RESTRICTION_UNKNOWN, RISK_HIGH, STATUS_LABELS)
from ..domain.product import Product
from ..domain.settings import Settings
from ..fees.engine import FeeInputs, FeeOptions, estimate_fees
from ..formatting import parse_iso
from . import qualification as q
from .calculator import calculate
from .ranking import opportunity_score
from .risk_engine import assess_risk

FIELD_LABELS = {
    "selling_price": "Amazon selling price",
    "sourcing_price": "Sourcing price",
    "weight_g": "Product weight",
    "bsr": "Best Sellers Rank",
    "monthly_sales": "Estimated monthly sales",
    "total_sellers": "Total sellers",
    "fba_sellers": "FBA sellers",
}

RULE_FIELDS = {
    "min_total_sellers": "total_sellers",
    "min_fba_sellers": "fba_sellers",
    "max_bsr": "bsr",
    "min_monthly_sales": "monthly_sales",
}

OPTIONAL_FIELDS = [
    ("asin", "ASIN"), ("title", "Product title"), ("brand", "Brand"), ("category", "Category"),
    ("amazon_url", "Amazon URL"), ("supplier", "Supplier"), ("shipping_prep", "Shipping / prep cost"),
    ("weight_g", "Weight"), ("length_cm", "Dimensions"),
]


def fee_inputs_for(product: Product) -> FeeInputs:
    return FeeInputs(
        selling_price=product.selling_price,
        fee_category=product.fee_category,
        fulfilment=product.fulfilment or FBA,
        weight_g=product.weight_g,
        length_cm=product.length_cm,
        width_cm=product.width_cm,
        height_cm=product.height_cm,
        dangerous_goods=bool(product.flag_hazmat or product.flag_battery),
        referral_fee_override=product.referral_fee_override,
        fba_fee_override=product.fba_fee_override,
    )


def fee_options_for(settings: Settings) -> FeeOptions:
    return FeeOptions(
        apply_low_price_fba=settings.apply_low_price_fba,
        apply_peak_fees=settings.apply_peak_fees,
        apply_fuel_surcharge=settings.apply_fuel_surcharge,
        apply_digital_services_fee=settings.apply_digital_services_fee,
        vat_on_fees=settings.vat_on_fees,
    )


def evaluate(product: Product, settings: Settings, today: date | None = None) -> dict:
    today = today or date.today()
    fees = estimate_fees(fee_inputs_for(product), fee_options_for(settings), today)
    profit = calculate(product, fees, settings)
    rules = q.evaluate_rules(product, profit, settings)

    # Missing critical data: rule inputs plus whatever profit needs. De-duplicated, in a stable order.
    missing: dict[str, str] = {}
    for item in profit.missing:
        missing.setdefault(item["field"], item["message"])
    for rule in rules:
        if rule.status == q.MISSING and rule.key in RULE_FIELDS:
            missing.setdefault(RULE_FIELDS[rule.key], rule.message)
    missing_list = [{"field": k, "label": FIELD_LABELS.get(k, k), "message": v} for k, v in missing.items()]

    risk = assess_risk(product, profit, settings, [m["label"] for m in missing_list])
    verification = verification_checks(product, settings, today)

    failed = [r for r in rules if r.status == q.FAIL]
    if failed:
        status = REJECTED
    elif missing_list:
        status = INCOMPLETE
    elif risk["level"] == RISK_HIGH:
        status = HIGH_RISK
    elif verification:
        status = NEEDS_VERIFICATION
    else:
        status = QUALIFIED

    score = opportunity_score(product, profit, risk["level"], settings)
    return {
        "status": status,
        "status_label": STATUS_LABELS[status],
        "summary": summary_lines(status, rules, missing_list, risk, verification),
        "fees": fees.to_dict(),
        "profit": profit.to_dict(),
        "rules": [r.to_dict() for r in rules],
        "missing": missing_list,
        "risk": risk,
        "verification": verification,
        "score": score,
        "completeness": completeness(product),
        "evaluated_on": today.isoformat(),
    }


def verification_checks(product: Product, settings: Settings, today: date) -> list[str]:
    checks = []
    if product.sourcing_price == 0:
        checks.append("Sourcing price is £0 — confirm it is correct (ROI can't be calculated).")
    checked = parse_iso(product.amazon_checked_at)
    if checked is not None:
        age = (today - checked.date()).days
        if age > settings.stale_data_days:
            checks.append(f"Amazon data was last checked {age} days ago (older than {settings.stale_data_days} days) — "
                          "re-check price, BSR and sellers.")
    if settings.require_restriction_check and product.restriction_status in (RESTRICTION_UNKNOWN, RESTRICTION_CHECK):
        checks.append("Restriction status is not verified — confirm you can sell this ASIN in Seller Central.")
    return checks


def summary_lines(status: str, rules, missing_list, risk, verification) -> list[str]:
    """The short 'why' shown on cards, tables and exports."""
    if status == REJECTED:
        return [r.message for r in rules if r.status == q.FAIL]
    if status == INCOMPLETE:
        return [m["message"] for m in missing_list]
    if status == HIGH_RISK:
        return [r["detail"] if r["key"] in {"low_roi", "thin_margin", "high_fba_competition"} else r["label"]
                for r in risk["reasons"]]
    if status == NEEDS_VERIFICATION:
        return list(verification)
    return [r.message for r in rules if r.status == q.PASS]


def completeness(product: Product) -> dict:
    missing = []
    for key, label in OPTIONAL_FIELDS:
        value = getattr(product, key)
        if key == "length_cm":
            if None in (product.length_cm, product.width_cm, product.height_cm):
                missing.append(label)
        elif value in (None, ""):
            missing.append(label)
    critical = ["selling_price", "sourcing_price", "bsr", "monthly_sales", "total_sellers", "fba_sellers"]
    have = sum(getattr(product, k) is not None for k in critical) + (len(OPTIONAL_FIELDS) - len(missing))
    total = len(critical) + len(OPTIONAL_FIELDS)
    return {"pct": round(have / total * 100), "missing_optional": missing}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
