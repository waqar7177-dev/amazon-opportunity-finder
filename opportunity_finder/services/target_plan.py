"""Target profit plan: which ranked opportunities could together reach the monthly target.

It walks the ranking best-first and adds each product's conservative (ESTIMATED)
monthly profit until the running total reaches the target. It is a planning aid,
not a promise of income.
"""
from __future__ import annotations

from ..constants import NEEDS_VERIFICATION, QUALIFIED
from ..domain.settings import Settings
from ..numbers import money
from .ranking import rank


def build_target_plan(items: list[dict], settings: Settings) -> dict:
    statuses = (QUALIFIED, NEEDS_VERIFICATION) if settings.include_needs_verification_in_plan else (QUALIFIED,)
    ranked = rank(items, statuses)
    target = settings.monthly_profit_target
    selected, total, investment = [], 0.0, 0.0
    skipped_no_profit = 0

    for item in ranked:
        profit = item["evaluation"]["profit"]
        monthly = profit["conservative_monthly_profit"]
        if monthly is None or monthly <= 0:
            skipped_no_profit += 1
            continue
        if total >= target:
            break
        total = money(total + monthly)
        investment = money(investment + (profit["monthly_stock_investment"] or 0))
        product = item["product"]
        selected.append({
            "product_id": product.id,
            "name": product.display_name,
            "asin": product.asin,
            "rank": item["rank"],
            "status": item["evaluation"]["status"],
            "score": item["evaluation"]["score"]["total"] if item["evaluation"].get("score") else None,
            "conservative_units": profit["conservative_units"],
            "conservative_monthly_profit": monthly,
            "monthly_stock_investment": profit["monthly_stock_investment"],
            "running_total": total,
        })

    achieved = total >= target and target > 0
    return {
        "target": target,
        "selected": selected,
        "selected_ids": {s["product_id"] for s in selected},
        "total": money(total),
        "achieved": achieved,
        "shortfall": money(max(0.0, target - total)),
        "progress_pct": round(min(total / target * 100, 100), 1) if target > 0 else 0.0,
        "stock_investment": money(investment),
        "candidates": len(ranked),
        "skipped_no_profit": skipped_no_profit,
        "statuses": statuses,
    }
