"""Opportunity Score (0–100) and ranking.

Not a black box: six components, each with a published maximum and a plain rule.
Priority follows the brief — ROI weighs most, then profit per unit and monthly
profit, then sales, competition and risk.
"""
from __future__ import annotations

from ..constants import QUALIFIED, RISK_HIGH, RISK_LOW, RISK_MEDIUM
from ..domain.product import Product
from ..domain.settings import Settings
from ..formatting import fmt_int, fmt_money, fmt_pct
from .calculator import ProfitResult

ROI_FULL_AT = 50.0          # % ROI for full ROI points
PROFIT_FULL_AT = 10.0       # £ net profit per unit for full points
MONTHLY_FULL_SHARE = 0.25   # conservative monthly profit of 25% of the target earns full points
SALES_FULL_AT = 500         # estimated monthly sales for full points

SCORE_COMPONENTS = [
    {"key": "roi", "label": "ROI", "max": 25, "rule": f"Full points at {ROI_FULL_AT:g}% ROI or more, scaled down to 0 at 0%."},
    {"key": "profit", "label": "Net profit per unit", "max": 20, "rule": f"Full points at £{PROFIT_FULL_AT:g} per unit or more, 0 at £0."},
    {"key": "monthly_profit", "label": "Conservative monthly profit", "max": 20,
     "rule": "Full points when one product covers a quarter of your monthly target."},
    {"key": "sales", "label": "Estimated monthly sales", "max": 15, "rule": f"Full points at {SALES_FULL_AT} sales a month or more."},
    {"key": "competition", "label": "Competition", "max": 10,
     "rule": "10 with 1–2 FBA sellers, 8 below medium competition, 5 at medium, 2 at high, 0 at 5+ above high; −5 if Amazon sells."},
    {"key": "risk", "label": "Risk", "max": 10, "rule": "LOW 10, MEDIUM 5, HIGH 0."},
]


def _scaled(value: float | None, full_at: float, maximum: float) -> float:
    if value is None or value <= 0 or full_at <= 0:
        return 0.0
    return round(min(value / full_at, 1.0) * maximum, 1)


def competition_points(fba_sellers: int | None, amazon_sells: bool, settings: Settings) -> float:
    if fba_sellers is None:
        return 0.0
    if fba_sellers < settings.competition_medium_from:
        points = 10.0 if fba_sellers <= 2 else 8.0
    elif fba_sellers < settings.competition_high_from:
        points = 5.0
    elif fba_sellers < settings.competition_high_from + 5:
        points = 2.0
    else:
        points = 0.0
    if amazon_sells:
        points = max(0.0, points - 5)
    return points


def opportunity_score(product: Product, profit: ProfitResult, risk_level: str, settings: Settings) -> dict | None:
    """Return the score with a per-component explanation, or None when profit is unknown."""
    if profit.net_profit is None:
        return None
    target_share = settings.monthly_profit_target * MONTHLY_FULL_SHARE
    risk_points = {RISK_LOW: 10.0, RISK_MEDIUM: 5.0, RISK_HIGH: 0.0}[risk_level]
    values = {
        "roi": (_scaled(profit.roi_pct, ROI_FULL_AT, 25),
                fmt_pct(profit.roi_pct) if profit.roi_pct is not None else "not calculable"),
        "profit": (_scaled(profit.net_profit, PROFIT_FULL_AT, 20), fmt_money(profit.net_profit)),
        "monthly_profit": (_scaled(profit.conservative_monthly_profit, target_share, 20),
                           fmt_money(profit.conservative_monthly_profit) + " (EST)"),
        "sales": (_scaled(product.monthly_sales, SALES_FULL_AT, 15), fmt_int(product.monthly_sales) + " / month"),
        "competition": (competition_points(product.fba_sellers, product.flag_amazon_sells, settings),
                        f"{fmt_int(product.fba_sellers)} FBA sellers" + (", Amazon sells" if product.flag_amazon_sells else "")),
        "risk": (risk_points, risk_level),
    }
    components = []
    for spec in SCORE_COMPONENTS:
        points, value_text = values[spec["key"]]
        components.append({**spec, "points": points, "value_text": value_text})
    total = round(sum(c["points"] for c in components))
    return {"total": int(max(0, min(100, total))), "components": components}


def rank_key(item: dict):
    """Sort key for an evaluated product dict (higher is better)."""
    ev = item["evaluation"]
    p = ev["profit"]
    score = ev["score"]["total"] if ev.get("score") else -1
    return (
        -score,
        -(p["roi_pct"] if p["roi_pct"] is not None else float("-inf")),
        -(p["net_profit"] if p["net_profit"] is not None else float("-inf")),
        -(p["conservative_monthly_profit"] if p["conservative_monthly_profit"] is not None else float("-inf")),
        -(item["product"].monthly_sales or 0),
        item["product"].id or 0,
    )


def rank(items: list[dict], statuses: tuple[str, ...] = (QUALIFIED,)) -> list[dict]:
    """Filter to ``statuses`` and order best first. Items are {"product": Product, "evaluation": dict}."""
    chosen = [i for i in items if i["evaluation"]["status"] in statuses]
    ranked = sorted(chosen, key=rank_key)
    for position, item in enumerate(ranked, start=1):
        item["rank"] = position
    return ranked
