"""Profit, ROI and the conservative sales model.

Formulas (shown in the UI tooltips too):

    Net profit per unit = Selling price − Sourcing price − Referral fee − FBA fee
                          − Shipping/prep − Other costs
                          (− digital services fee, surcharges and VAT when enabled in Settings)
    ROI %               = Net profit ÷ Sourcing price × 100
    Net margin %        = Net profit ÷ Selling price × 100
    Theoretical monthly revenue = Estimated monthly sales × Selling price       (ESTIMATED)
    Theoretical monthly profit  = Estimated monthly sales × Net profit           (ESTIMATED)
    Conservative units          = floor(Estimated monthly sales × Capture rate)  (ESTIMATED)
    Conservative monthly profit = Conservative units × Net profit                (ESTIMATED)
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from ..domain.product import Product
from ..domain.settings import VAT_REGISTERED, Settings
from ..fees.engine import FeeResult, load_fee_table
from ..numbers import money, round_to

FORMULAS = {
    "net_profit": "Selling price − Sourcing price − Referral fee − FBA fee − Shipping/prep − Other costs "
                  "(plus digital services fee, surcharges and VAT when switched on in Settings)",
    "roi": "Net profit ÷ Sourcing price × 100",
    "margin": "Net profit ÷ Selling price × 100",
    "theoretical_revenue": "Estimated monthly sales × Selling price",
    "theoretical_profit": "Estimated monthly sales × Net profit per unit",
    "capture_rate": "Default capture rate, reduced as FBA competition rises (and when Amazon sells the listing)",
    "conservative_units": "Estimated monthly sales × Capture rate, rounded down",
    "conservative_profit": "Conservative units × Net profit per unit",
    "stock_investment": "Conservative units × (Sourcing price + Shipping/prep + Other costs)",
    "max_sourcing_price": "Highest sourcing price that still meets your minimum profit and minimum ROI",
}


@dataclass
class CaptureResult:
    rate_pct: float | None
    tier: str | None  # low | medium | high
    explanation: str


@dataclass
class ProfitResult:
    selling_price: float | None = None
    output_vat: float = 0.0
    sourcing_price: float | None = None
    shipping_prep: float = 0.0
    other_costs: float = 0.0
    total_fees: float | None = None
    net_profit: float | None = None
    roi_pct: float | None = None
    margin_pct: float | None = None
    theoretical_monthly_revenue: float | None = None
    theoretical_monthly_profit: float | None = None
    capture_rate_pct: float | None = None
    capture_tier: str | None = None
    capture_explanation: str = ""
    conservative_units: int | None = None
    conservative_monthly_revenue: float | None = None
    conservative_monthly_profit: float | None = None
    monthly_stock_investment: float | None = None
    max_sourcing_price: float | None = None
    missing: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


MISSING_MESSAGES = {
    "selling_price": "Amazon selling price is required before profitability can be calculated.",
    "sourcing_price": "Sourcing price is required before profit and ROI can be calculated.",
    "weight_g": "Product weight (or an FBA fee from Seller Central) is required to estimate the FBA fee.",
    "monthly_sales": "Estimated monthly sales are required for monthly profit estimates.",
    "fba_sellers": "FBA seller count is required to choose a capture rate.",
}


def capture_rate(fba_sellers: int | None, amazon_sells: bool, settings: Settings) -> CaptureResult:
    if fba_sellers is None:
        return CaptureResult(None, None, "FBA seller count is missing, so no capture rate can be chosen.")
    if fba_sellers >= settings.competition_high_from:
        rate, tier = settings.capture_rate_high, "high"
        why = f"{fba_sellers} FBA sellers is high competition ({settings.competition_high_from}+), so {rate:g}%"
    elif fba_sellers >= settings.competition_medium_from:
        rate, tier = settings.capture_rate_medium, "medium"
        why = (f"{fba_sellers} FBA sellers is medium competition "
               f"({settings.competition_medium_from}–{settings.competition_high_from - 1}), so {rate:g}%")
    else:
        rate, tier = settings.capture_rate_low, "low"
        why = f"{fba_sellers} FBA sellers is low competition (under {settings.competition_medium_from}), so {rate:g}%"
    if amazon_sells and settings.amazon_sells_capture_pct < 100:
        adjusted = rate * settings.amazon_sells_capture_pct / 100
        why += f"; Amazon sells this listing, so {settings.amazon_sells_capture_pct:g}% of that = {adjusted:g}%"
        rate = adjusted
    return CaptureResult(round_to(rate, 4), tier, why + ".")


def calculate(product: Product, fees: FeeResult, settings: Settings) -> ProfitResult:
    r = ProfitResult(selling_price=product.selling_price, sourcing_price=product.sourcing_price,
                     total_fees=fees.total_fees)
    r.shipping_prep = product.shipping_prep or 0.0
    r.other_costs = product.other_costs or 0.0
    if product.shipping_prep is None:
        r.notes.append("Shipping / prep not entered — counted as £0.00.")
    if product.other_costs is None:
        r.notes.append("Other costs not entered — counted as £0.00.")

    if product.selling_price is None:
        r.missing.append(_missing("selling_price"))
    if product.sourcing_price is None:
        r.missing.append(_missing("sourcing_price"))
    if fees.total_fees is None:
        for key in fees.missing:
            if key != "selling_price":
                r.missing.append(_missing(key))

    vat_rate = load_fee_table()["surcharges"]["vat_rate_pct"]
    if product.selling_price is not None and settings.vat_mode == VAT_REGISTERED:
        r.output_vat = money(product.selling_price * vat_rate / (100 + vat_rate))
        r.notes.append("VAT registered: output VAT is deducted from each sale. Enter sourcing costs excluding VAT.")

    capture = capture_rate(product.fba_sellers, product.flag_amazon_sells, settings)
    r.capture_rate_pct, r.capture_tier, r.capture_explanation = capture.rate_pct, capture.tier, capture.explanation

    if product.selling_price is None or fees.total_fees is None:
        return r

    net_before_sourcing = product.selling_price - r.output_vat - fees.total_fees - r.shipping_prep - r.other_costs
    r.max_sourcing_price = _max_sourcing_price(net_before_sourcing, settings)

    if product.sourcing_price is None:
        return r

    r.net_profit = money(net_before_sourcing - product.sourcing_price)
    if product.sourcing_price > 0:
        r.roi_pct = round_to(r.net_profit / product.sourcing_price * 100, 2)
    if product.selling_price > 0:
        r.margin_pct = round_to(r.net_profit / product.selling_price * 100, 2)

    if product.monthly_sales is not None:
        r.theoretical_monthly_revenue = money(product.monthly_sales * product.selling_price)
        r.theoretical_monthly_profit = money(product.monthly_sales * r.net_profit)
        if capture.rate_pct is not None:
            # A tiny epsilon stops float noise (e.g. 49.999999) from dropping a whole unit.
            r.conservative_units = int(math.floor(product.monthly_sales * capture.rate_pct / 100 + 1e-9))
            r.conservative_monthly_revenue = money(r.conservative_units * product.selling_price)
            r.conservative_monthly_profit = money(r.conservative_units * r.net_profit)
            unit_cost = product.sourcing_price + r.shipping_prep + r.other_costs
            r.monthly_stock_investment = money(r.conservative_units * unit_cost)
    return r


def _max_sourcing_price(net_before_sourcing: float, settings: Settings) -> float | None:
    """Highest sourcing price s with (net − s) > min_profit and (net − s) / s ≥ min_roi."""
    by_profit = net_before_sourcing - settings.min_net_profit
    candidates = [by_profit]
    if settings.min_roi > -100:
        candidates.append(net_before_sourcing / (1 + settings.min_roi / 100))
    best = min(candidates)
    if best <= 0:
        return 0.0
    # Profit must be strictly above the minimum, so step back a penny when that bound decides.
    if best == by_profit:
        best -= 0.01
    return money(math.floor(best * 100 + 1e-9) / 100) if best > 0 else 0.0


def _missing(key: str) -> dict:
    return {"field": key, "message": MISSING_MESSAGES[key]}
