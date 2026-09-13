"""Amazon UK fee estimation — referral fee, FBA fulfilment fee and surcharges.

Every number returned here is an ESTIMATE built from the fee table in
``uk_fee_table.json``. Update that file when Amazon changes its fees; no code
change is needed for new rates. Confirm exact fees in the Seller Central
Revenue Calculator before purchasing stock.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from ..constants import FBA, FBM
from ..numbers import money

TABLE_PATH = Path(__file__).with_name("uk_fee_table.json")


@lru_cache(maxsize=4)
def load_fee_table(path: str | None = None) -> dict:
    with open(path or TABLE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def referral_categories(table: dict | None = None) -> list[dict]:
    table = table or load_fee_table()
    cats = table["referral_categories"]
    head = [c for c in cats if c["key"] == "everything_else"]
    rest = sorted((c for c in cats if c["key"] != "everything_else"), key=lambda c: c["label"])
    return head + rest


def describe_referral_category(cat: dict) -> str:
    """Plain-English rate, e.g. '8% up to £10, 15% above £10'."""
    if cat["type"] == "flat":
        return f"{cat['rate']:g}%"
    bands = cat["bands"]
    parts = []
    for i, (limit, rate) in enumerate(bands):
        if cat["type"] == "whole_price":
            parts.append(f"{rate:g}% up to £{limit:g}" if limit is not None else f"{rate:g}% above £{bands[i - 1][0]:g}")
        else:
            parts.append(f"{rate:g}% of the first £{limit:g}" if limit is not None else f"{rate:g}% of the rest")
    return ", ".join(parts)


def category_by_key(key: str | None, table: dict | None = None) -> dict | None:
    table = table or load_fee_table()
    for cat in table["referral_categories"]:
        if cat["key"] == key:
            return cat
    return None


@dataclass
class FeeInputs:
    selling_price: float | None = None
    fee_category: str = "everything_else"
    fulfilment: str = FBA
    weight_g: float | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    dangerous_goods: bool = False
    referral_fee_override: float | None = None
    fba_fee_override: float | None = None


@dataclass
class FeeOptions:
    apply_low_price_fba: bool = True
    apply_peak_fees: bool = True
    apply_fuel_surcharge: bool = True
    apply_digital_services_fee: bool = True
    vat_on_fees: bool = False


@dataclass
class FeeResult:
    referral_fee: float | None = None
    referral_rate_text: str = ""
    referral_source: str = "missing"  # estimated | override | missing
    fba_fee: float | None = None
    fba_source: str = "missing"  # estimated | override | not_applicable | missing
    fba_program: str | None = None  # standard | low_price | selected_category
    size_tier: str | None = None
    size_tier_label: str | None = None
    tier_basis: str | None = None  # dimensions | weight_only
    shipping_weight_g: float | None = None
    dimensional_weight_g: float | None = None
    peak_applied: bool = False
    fuel_surcharge: float = 0.0
    dangerous_goods_fee: float = 0.0
    digital_services_fee: float = 0.0
    vat_on_fees: float = 0.0
    total_fees: float | None = None
    confidence: str = "none"  # manual | high | low | none
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    table_version: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ referral
def estimate_referral_fee(price: float, category_key: str | None, table: dict | None = None) -> tuple[float, str]:
    """Referral fee for one unit at ``price`` (VAT-inclusive, as listed on Amazon)."""
    table = table or load_fee_table()
    cat = category_by_key(category_key, table) or category_by_key("everything_else", table)
    kind = cat["type"]
    if kind == "flat":
        fee = price * cat["rate"] / 100
        text = f"{_pct(cat['rate'])} of the selling price"
    elif kind == "whole_price":
        rate = None
        for limit, band_rate in cat["bands"]:
            if limit is None or price <= limit:
                rate = band_rate
                break
        fee = price * rate / 100
        text = f"{_pct(rate)} of the selling price ({cat['label']} rate at £{price:,.2f})"
    elif kind == "marginal":
        fee, lower, parts = 0.0, 0.0, []
        for limit, band_rate in cat["bands"]:
            upper = price if limit is None else min(price, limit)
            if upper > lower:
                fee += (upper - lower) * band_rate / 100
                parts.append(f"{_pct(band_rate)} of £{upper - lower:,.2f}")
            if limit is None or price <= limit:
                break
            lower = limit
        text = " + ".join(parts) or "0%"
    else:  # pragma: no cover - guarded by table tests
        raise ValueError(f"Unknown referral fee type {kind!r}")

    fee = money(fee)
    min_fee = cat.get("min_fee")
    if min_fee is not None and fee < min_fee and price > 0:
        text += f" — raised to the £{min_fee:.2f} minimum"
        fee = float(min_fee)
    return fee, text


# ---------------------------------------------------------------------- FBA
def _sorted_dims(inputs: FeeInputs) -> list[float] | None:
    dims = [inputs.length_cm, inputs.width_cm, inputs.height_cm]
    if any(d is None or d <= 0 for d in dims):
        return None
    return sorted(dims, reverse=True)


def _fits(dims: list[float], max_dims: list[float] | None) -> bool:
    if max_dims is None:
        return True
    return all(d <= m + 1e-9 for d, m in zip(dims, sorted(max_dims, reverse=True)))


def _band_fee(bands: list, weight_g: float) -> float | None:
    for limit, fee in bands:
        if weight_g <= limit + 1e-9:
            return fee
    return None


def in_peak_season(on_date: date, table: dict) -> bool:
    peak = table.get("peak_season")
    if not peak:
        return False
    start = tuple(peak["start_month_day"])
    end = tuple(peak["end_month_day"])
    md = (on_date.month, on_date.day)
    if start <= end:
        return start <= md <= end
    return md >= start or md <= end  # wraps over the new year


def _low_price_fee(inputs: FeeInputs, dims: list[float], table: dict) -> tuple[dict, float] | None:
    lp = table["low_price_fba"]
    limit = lp["reduced_max_price"] if inputs.fee_category in lp["reduced_threshold_categories"] else lp["max_price"]
    if inputs.selling_price is None or inputs.selling_price > limit:
        return None
    for tier in lp["tiers"]:
        if _fits(dims, tier["max_dims"]):
            fee = _band_fee(tier["bands"], inputs.weight_g)
            if fee is not None:
                return tier, fee
    return None


def _selected_category_fee(tier: dict, weight_g: float, peak: bool) -> float:
    base = tier["peak_base_fee"] if peak else tier["base_fee"]
    step = tier["peak_per_100g"] if peak else tier["per_100g"]
    extra_steps = max(0, math.ceil((weight_g - 100) / 100 - 1e-9))
    return base + extra_steps * step


def _oversize_fee(tier: dict, weight_g: float) -> float:
    if tier["kind"] == "special":
        fee = _band_fee(tier["bands"], weight_g)
        if fee is None:
            top_limit, top_fee = tier["bands"][-1]
            fee = top_fee + math.ceil((weight_g - top_limit) / 1000 - 1e-9) * tier["per_kg_above"]
        return fee
    over = weight_g - tier["base_up_to_g"]
    steps = max(0, math.ceil(over / 1000 - 1e-9))
    return tier["base_fee"] + steps * tier["per_kg_above"]


def _standard_tier_from_dims(dims: list[float], unit_g: float, dim_g: float, table: dict) -> dict:
    std = table["standard_fba"]
    rules = std["special_oversize_rules"]
    longest, mid, short = dims
    if (unit_g > rules["min_unit_g_exclusive"] or longest > rules["longest_side_cm_exclusive"]
            or longest + 2 * (mid + short) > rules["length_plus_girth_cm_exclusive"]):
        return _tier(std, "special_oversize")
    for tier in std["tiers"]:
        if tier["kind"] == "special":
            continue
        if not _fits(dims, tier["max_dims"]):
            continue
        if unit_g > tier["max_unit_g"] or unit_g <= tier.get("min_unit_g_exclusive", -1):
            continue
        if tier["kind"] != "envelope" and dim_g > tier.get("max_dim_weight_g", math.inf):
            continue
        return tier
    return _tier(std, "special_oversize")


def _standard_tier_from_weight(unit_g: float, table: dict) -> dict:
    std = table["standard_fba"]
    if unit_g <= 11_900:
        return _tier(std, "standard_parcel")
    if unit_g <= 15_000:
        return _tier(std, "standard_oversize_light")
    if unit_g <= 23_000:
        return _tier(std, "standard_oversize_heavy")
    if unit_g <= 31_500:
        return _tier(std, "heavy_oversize")
    return _tier(std, "special_oversize")


def _tier(std: dict, key: str) -> dict:
    return next(t for t in std["tiers"] if t["key"] == key)


def estimate_fba_fee(inputs: FeeInputs, options: FeeOptions, on_date: date, table: dict, result: FeeResult) -> None:
    """Fill the FBA part of ``result``."""
    if inputs.weight_g is None or inputs.weight_g <= 0:
        result.missing.append("weight_g")
        result.fba_source = "missing"
        return

    unit_g = float(inputs.weight_g)
    dims = _sorted_dims(inputs)
    divisor = table["dimensional_weight_divisor"]
    peak_possible = options.apply_peak_fees and in_peak_season(on_date, table)
    peak_excluded = inputs.fee_category in table["peak_season"].get("excluded_categories", [])
    selected = table["selected_category_parcels"]
    is_selected_category = inputs.fee_category in selected["categories"]

    if dims is None:
        result.tier_basis = "weight_only"
        result.confidence = "low"
        result.warnings.append(
            "Dimensions are missing, so the size tier was estimated from weight alone "
            "(assumed the largest parcel tier for that weight). Add packaged dimensions for a better estimate."
        )
        tier = _standard_tier_from_weight(unit_g, table)
        result.shipping_weight_g = unit_g
        if tier["kind"] == "parcel" and is_selected_category:
            sel_tier = next(t for t in selected["tiers"] if t["key"] == "large_parcel_2")
            peak = peak_possible and not peak_excluded
            result.fba_fee = money(_selected_category_fee(sel_tier, unit_g, peak))
            result.fba_program, result.size_tier, result.size_tier_label = "selected_category", sel_tier["key"], sel_tier["label"]
            result.peak_applied = peak
        else:
            _apply_standard_fee(tier, unit_g, peak_possible and not peak_excluded, table, result)
        if options.apply_low_price_fba and inputs.selling_price is not None:
            result.notes.append("Low-Price FBA might lower this fee if the item is small enough — add dimensions to check.")
        result.fba_source = "estimated"
        return

    result.tier_basis = "dimensions"
    result.confidence = "high"
    dim_g = dims[0] * dims[1] * dims[2] / divisor * 1000
    result.dimensional_weight_g = round(dim_g, 1)

    if options.apply_low_price_fba:
        low = _low_price_fee(inputs, dims, table)
        if low is not None:
            tier, fee = low
            result.fba_fee = money(fee)
            result.fba_program, result.size_tier, result.size_tier_label = "low_price", tier["key"], tier["label"]
            result.shipping_weight_g = unit_g
            result.notes.append("Low-Price FBA rate applied (price and size are within the Low-Price FBA limits).")
            result.fba_source = "estimated"
            return

    tier = _standard_tier_from_dims(dims, unit_g, dim_g, table)
    if tier["kind"] == "parcel" and is_selected_category:
        sel_tier = next((t for t in selected["tiers"] if _fits(dims, t["max_dims"]) and unit_g <= t["max_unit_g"]), None)
        if sel_tier is not None:
            peak = peak_possible and not peak_excluded
            result.fba_fee = money(_selected_category_fee(sel_tier, unit_g, peak))
            result.fba_program, result.size_tier, result.size_tier_label = "selected_category", sel_tier["key"], sel_tier["label"]
            result.shipping_weight_g = unit_g
            result.peak_applied = peak
            result.fba_source = "estimated"
            return

    uses_dim_weight = tier["kind"] in {"parcel", "oversize"}
    shipping_g = max(unit_g, dim_g) if uses_dim_weight else unit_g
    result.shipping_weight_g = round(shipping_g, 1)
    _apply_standard_fee(tier, shipping_g, peak_possible and not peak_excluded, table, result)
    result.fba_source = "estimated"


def _apply_standard_fee(tier: dict, shipping_g: float, peak: bool, table: dict, result: FeeResult) -> None:
    result.fba_program, result.size_tier, result.size_tier_label = "standard", tier["key"], tier["label"]
    if "bands" in tier and tier["kind"] != "special":
        bands = tier["bands"]
        peak_bands = table["peak_season"]["standard_fba_bands"].get(tier["key"])
        if peak and peak_bands:
            bands = peak_bands
            result.peak_applied = True
        fee = _band_fee(bands, shipping_g)
        if fee is None:  # heavier than the tier's top band (weight-only estimate)
            fee = bands[-1][1]
            result.warnings.append("Weight is above this tier's top band; the top band fee was used.")
    else:
        fee = _oversize_fee(tier, shipping_g)
    result.fba_fee = money(fee)


# -------------------------------------------------------------------- total
def estimate_fees(inputs: FeeInputs, options: FeeOptions | None = None, on_date: date | None = None,
                  table: dict | None = None) -> FeeResult:
    options = options or FeeOptions()
    on_date = on_date or date.today()
    table = table or load_fee_table()
    result = FeeResult(table_version=table["version"])
    surcharges = table["surcharges"]

    # Referral fee
    if inputs.referral_fee_override is not None:
        result.referral_fee = money(inputs.referral_fee_override)
        result.referral_source = "override"
        result.referral_rate_text = "Entered manually (from Seller Central)"
    elif inputs.selling_price is None:
        result.missing.append("selling_price")
    else:
        result.referral_fee, result.referral_rate_text = estimate_referral_fee(inputs.selling_price, inputs.fee_category, table)
        result.referral_source = "estimated"
        if inputs.fee_category in table.get("media_categories", []):
            result.notes.append("Media categories can carry an extra closing fee that is not included here.")

    # Fulfilment fee
    if inputs.fulfilment == FBM:
        result.fba_fee = 0.0
        result.fba_source = "not_applicable"
        result.confidence = "manual" if result.referral_source == "override" else "high"
        result.notes.append("FBM: no FBA fee. Put your own postage and packaging in Shipping / prep.")
    elif inputs.fba_fee_override is not None:
        result.fba_fee = money(inputs.fba_fee_override)
        result.fba_source = "override"
        result.confidence = "manual"
        result.notes.append("FBA fee entered manually — used as the full fulfilment charge (no fuel or dangerous-goods add-ons).")
    else:
        estimate_fba_fee(inputs, options, on_date, table, result)
        if result.fba_fee is not None:
            if options.apply_fuel_surcharge and on_date >= date.fromisoformat(surcharges["fuel_logistics_from"]):
                result.fuel_surcharge = money(result.fba_fee * surcharges["fuel_logistics_pct"] / 100)
            if inputs.dangerous_goods:
                result.dangerous_goods_fee = money(surcharges["dangerous_goods_per_unit"])
                result.notes.append("Dangerous goods / lithium battery handling fee added (£0.10 per unit).")
            if result.peak_applied:
                result.notes.append(f"{table['peak_season']['label']} applied for today's date.")

    if result.referral_fee is None or result.fba_fee is None:
        result.total_fees = None
        return result

    amazon_fees = result.referral_fee + result.fba_fee + result.fuel_surcharge + result.dangerous_goods_fee
    if options.apply_digital_services_fee:
        result.digital_services_fee = money(amazon_fees * surcharges["digital_services_fee_pct"] / 100)
    if options.vat_on_fees:
        result.vat_on_fees = money((amazon_fees + result.digital_services_fee) * surcharges["vat_rate_pct"] / 100)
    result.total_fees = money(amazon_fees + result.digital_services_fee + result.vat_on_fees)
    return result


def _pct(rate: float) -> str:
    return f"{rate:g}%"
