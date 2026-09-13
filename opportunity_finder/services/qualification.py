"""Qualification rules. The single place that decides pass / fail / missing per rule.

A missing value is reported as missing — it never passes and it is never guessed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ..domain.product import Product
from ..domain.settings import Settings
from ..formatting import fmt_int, fmt_money, fmt_pct
from .calculator import ProfitResult

PASS, FAIL, MISSING, NOT_APPLICABLE = "pass", "fail", "missing", "not_applicable"


@dataclass
class RuleResult:
    key: str
    label: str
    status: str
    message: str
    value: float | int | None
    threshold: float | int

    def to_dict(self) -> dict:
        return asdict(self)


# (key, label, setting, comparison, formatter, missing message)
RULES = [
    ("min_total_sellers", "Total sellers", "min_total_sellers", ">=", fmt_int,
     "Total seller count is missing — add it to check the minimum sellers rule."),
    ("min_fba_sellers", "FBA sellers", "min_fba_sellers", ">=", fmt_int,
     "FBA seller count is missing — add it to check the minimum FBA sellers rule."),
    ("max_bsr", "Best Sellers Rank", "max_bsr", "<", fmt_int,
     "Best Sellers Rank is missing — add it to check the BSR rule."),
    ("min_monthly_sales", "Estimated monthly sales", "min_monthly_sales", ">=", fmt_int,
     "Estimated monthly sales are missing — add them to check the sales rule."),
    ("min_net_profit", "Net profit per unit", "min_net_profit", ">", fmt_money,
     "Net profit can't be calculated yet — see the missing data list."),
    ("min_roi", "ROI", "min_roi", ">=", fmt_pct,
     "ROI can't be calculated yet — see the missing data list."),
]

RULE_DESCRIPTIONS = {
    "min_total_sellers": "Total sellers ≥ {v}",
    "min_fba_sellers": "FBA sellers ≥ {v}",
    "max_bsr": "Best Sellers Rank < {v}",
    "min_monthly_sales": "Estimated monthly sales ≥ {v}",
    "min_net_profit": "Net profit per unit > {v}",
    "min_roi": "ROI ≥ {v}",
}


def describe_rules(settings: Settings) -> list[dict]:
    out = []
    for key, label, setting, _, fmt, _ in RULES:
        value = getattr(settings, setting)
        out.append({"key": key, "label": label, "text": RULE_DESCRIPTIONS[key].format(v=fmt(value))})
    return out


def _value_for(key: str, product: Product, profit: ProfitResult):
    return {
        "min_total_sellers": product.total_sellers,
        "min_fba_sellers": product.fba_sellers,
        "max_bsr": product.bsr,
        "min_monthly_sales": product.monthly_sales,
        "min_net_profit": profit.net_profit,
        "min_roi": profit.roi_pct,
    }[key]


def evaluate_rules(product: Product, profit: ProfitResult, settings: Settings) -> list[RuleResult]:
    results = []
    for key, label, setting, op, fmt, missing_msg in RULES:
        threshold = getattr(settings, setting)
        value = _value_for(key, product, profit)

        if key == "min_roi" and value is None and profit.net_profit is not None and product.sourcing_price == 0:
            results.append(RuleResult(key, label, NOT_APPLICABLE,
                                      "ROI can't be calculated with a £0 sourcing price — confirm the sourcing price.",
                                      None, threshold))
            continue
        if value is None:
            results.append(RuleResult(key, label, MISSING, missing_msg, None, threshold))
            continue

        passed = {">=": value >= threshold, ">": value > threshold, "<": value < threshold}[op]
        results.append(RuleResult(key, label, PASS if passed else FAIL,
                                  _message(key, label, value, threshold, passed, fmt), value, threshold))
    return results


def _message(key, label, value, threshold, passed, fmt) -> str:
    v, t = fmt(value), fmt(threshold)
    if key == "max_bsr":
        return f"BSR {v} is below the maximum {t}" if passed else f"BSR {v} exceeds maximum {t}" if value > threshold \
            else f"BSR {v} is not below the maximum {t}"
    if key == "min_net_profit":
        return f"Net profit {v} per unit is above the minimum {t}" if passed \
            else f"Net profit {v} per unit is not above the minimum {t}"
    if key == "min_monthly_sales":
        return f"Monthly sales {v} meet the minimum {t}" if passed else f"Monthly sales {v} below minimum {t}"
    if key == "min_roi":
        return f"ROI {v} meets the minimum {t}" if passed else f"ROI {v} below minimum {t}"
    return f"{label} {v} meets the minimum {t}" if passed else f"{label} {v} below minimum {t}"
