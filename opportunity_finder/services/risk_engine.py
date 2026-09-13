"""Transparent, rule-based risk scoring.

Each factor adds points. The total decides the level, except for factors that
force HIGH on their own (a restricted listing or a possible IP complaint can
cost you the account, whatever the other numbers say). Every factor that fired
is returned with its points, so the UI never has to hide the reasoning.
"""
from __future__ import annotations

from ..constants import (RESTRICTION_CHECK, RESTRICTION_RESTRICTED, RESTRICTION_UNKNOWN, RISK_HIGH, RISK_LOW,
                         RISK_MEDIUM)
from ..domain.product import Product
from ..domain.settings import Settings
from ..formatting import fmt_pct
from .calculator import ProfitResult

RISK_FACTORS = {
    "restricted": {"label": "Product is restricted / gated", "points": 45, "forces_high": True},
    "ip_concern": {"label": "Possible IP / trademark concern", "points": 45, "forces_high": True},
    "hazmat": {"label": "Hazmat / dangerous goods", "points": 25},
    "amazon_sells": {"label": "Amazon sells this listing", "points": 25},
    "high_fba_competition": {"label": "Too many FBA sellers", "points": 20},
    "battery": {"label": "Contains a battery", "points": 15},
    "low_roi": {"label": "Low ROI", "points": 15},
    "missing_data": {"label": "Missing critical data", "points": 15},
    "medium_fba_competition": {"label": "Moderate FBA competition", "points": 10},
    "thin_margin": {"label": "Thin net margin", "points": 10},
    "restriction_unknown": {"label": "Restriction status not verified", "points": 10},
    "liquid": {"label": "Liquid", "points": 10},
    "fragile": {"label": "Fragile", "points": 10},
    "seasonal": {"label": "Seasonal demand", "points": 10},
}
HIGH_FROM = 40
MEDIUM_FROM = 20


def assess_risk(product: Product, profit: ProfitResult, settings: Settings, missing_labels: list[str]) -> dict:
    reasons: list[dict] = []

    def add(key: str, detail: str) -> None:
        factor = RISK_FACTORS[key]
        reasons.append({"key": key, "label": factor["label"], "points": factor["points"],
                        "detail": detail, "forces_high": factor.get("forces_high", False)})

    if product.restriction_status == RESTRICTION_RESTRICTED:
        add("restricted", "You marked this listing as restricted. You may not be able to sell it without approval.")
    elif product.restriction_status in (RESTRICTION_UNKNOWN, RESTRICTION_CHECK):
        add("restriction_unknown", "Check Seller Central to confirm you can sell this ASIN before buying stock.")
    if product.flag_ip_concern:
        add("ip_concern", "Brand owners can file IP complaints that suspend listings or accounts.")
    if product.flag_hazmat:
        add("hazmat", "Dangerous goods need extra review and can be blocked from FBA.")
    if product.flag_amazon_sells:
        add("amazon_sells", "Amazon usually wins most of the Buy Box when it sells a listing.")
    if product.flag_battery:
        add("battery", "Battery products can need dangerous-goods review and extra fees.")
    if product.flag_liquid:
        add("liquid", "Liquids need extra packaging and can leak in transit.")
    if product.flag_fragile:
        add("fragile", "Fragile items risk damage, returns and prep costs.")
    if product.flag_seasonal:
        add("seasonal", "Sales may drop sharply out of season; stock can get stuck.")

    if product.fba_sellers is not None:
        if product.fba_sellers >= settings.competition_high_from:
            add("high_fba_competition",
                f"{product.fba_sellers} FBA sellers (high competition starts at {settings.competition_high_from}).")
        elif product.fba_sellers >= settings.competition_medium_from:
            add("medium_fba_competition",
                f"{product.fba_sellers} FBA sellers (medium competition starts at {settings.competition_medium_from}).")

    if profit.roi_pct is not None and profit.roi_pct < settings.low_roi_threshold:
        add("low_roi", f"ROI only {fmt_pct(profit.roi_pct)} (flagged below {fmt_pct(settings.low_roi_threshold)}).")
    if profit.margin_pct is not None and profit.margin_pct < settings.thin_margin_threshold:
        add("thin_margin",
            f"Net margin {fmt_pct(profit.margin_pct)} of the selling price "
            f"(flagged below {fmt_pct(settings.thin_margin_threshold)}).")
    if missing_labels:
        add("missing_data", "Missing: " + ", ".join(missing_labels) + ".")

    score = sum(r["points"] for r in reasons)
    forced = any(r["forces_high"] for r in reasons)
    if forced or score >= HIGH_FROM:
        level = RISK_HIGH
    elif score >= MEDIUM_FROM:
        level = RISK_MEDIUM
    else:
        level = RISK_LOW
    reasons.sort(key=lambda r: (-r["forces_high"], -r["points"]))
    return {"level": level, "score": score, "forced": forced, "reasons": reasons}


def risk_model_description() -> dict:
    return {
        "factors": [{"key": k, **v} for k, v in sorted(RISK_FACTORS.items(), key=lambda kv: -kv[1]["points"])],
        "high_from": HIGH_FROM,
        "medium_from": MEDIUM_FROM,
    }
