"""Backend validation for product data — the form, Smart Paste and bulk import all use this.

The browser may validate too, but nothing is trusted until it passes here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from ..constants import (FBA, FBM, FLAG_KEYS, RESTRICTION_CHECK, RESTRICTION_LABELS, RESTRICTION_RESTRICTED,
                         RESTRICTION_UNGATED, RESTRICTION_UNKNOWN, SOURCE_LABELS, SOURCE_MANUAL)
from ..domain.product import Product
from ..fees.engine import category_by_key, referral_categories
from ..numbers import is_blank, parse_bool, parse_number, parse_whole

MAX_PRICE = 1_000_000.0
MAX_BSR = 50_000_000
MAX_SALES = 10_000_000
MAX_SELLERS = 10_000
TEXT_LIMITS = {"title": 500, "brand": 120, "category": 200, "supplier": 200, "notes": 5000, "bsr_category": 200}

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")

RESTRICTION_WORDS = {
    RESTRICTION_UNKNOWN: {"unknown", "", "?", "not checked", "n/a", "na"},
    RESTRICTION_CHECK: {"check", "check seller central", "to check", "needs check", "pending"},
    RESTRICTION_RESTRICTED: {"restricted", "gated", "yes", "blocked", "not allowed"},
    RESTRICTION_UNGATED: {"ungated", "verified", "unrestricted", "approved", "allowed", "no", "open",
                          "ungated / verified manually", "ungated/verified manually"},
}


@dataclass
class ValidationResult:
    product: Product
    errors: dict[str, str] = field(default_factory=dict)
    warnings: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def normalise_asin(raw) -> str | None:
    if is_blank(raw):
        return None
    return re.sub(r"\s+", "", str(raw)).upper()


def canonical_amazon_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url, re.I)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if m and host.endswith("amazon.co.uk"):
        return f"https://www.amazon.co.uk/dp/{m.group(1).upper()}"
    return url


def parse_restriction(raw) -> tuple[str | None, str | None]:
    text = "" if raw is None else str(raw).strip().lower()
    if text in RESTRICTION_LABELS:
        return text, None
    for key, words in RESTRICTION_WORDS.items():
        if text in words:
            return key, None
    return None, f'Restriction status "{raw}" is not recognised. Use Unknown, Check Seller Central, Restricted or Ungated.'


def parse_fulfilment(raw) -> tuple[str | None, str | None]:
    text = "" if raw is None else str(raw).strip().upper()
    if text in {"", FBA, "AMAZON", "FULFILLED BY AMAZON", "FULFILMENT BY AMAZON"}:
        return FBA, None
    if text in {FBM, "MFN", "MERCHANT", "SELF", "FULFILLED BY MERCHANT"}:
        return FBM, None
    return None, f'Fulfilment "{raw}" is not recognised. Use FBA or FBM.'


def match_fee_category(raw) -> str | None:
    """Accept a fee category key or its label (case-insensitive)."""
    if is_blank(raw):
        return "everything_else"
    text = str(raw).strip()
    if category_by_key(text):
        return text
    lowered = text.lower().replace("&", "and")
    for cat in referral_categories():
        if cat["label"].lower().replace("&", "and") == lowered:
            return cat["key"]
    return None


def validate_product(data: dict, *, base: Product | None = None, checkbox_form: bool = True) -> ValidationResult:
    """Turn raw submitted values into a Product, collecting friendly errors.

    ``checkbox_form``: an HTML form omits unticked checkboxes, so a missing flag means False.
    For imports, missing flag columns also mean False.
    """
    errors: dict[str, str] = {}
    warnings: dict[str, str] = {}
    p = Product() if base is None else Product.from_mapping(base.__dict__)

    def text(name: str) -> str | None:
        raw = data.get(name)
        if is_blank(raw):
            return None
        value = re.sub(r"[ \t]+", " ", str(raw)).strip() if name != "notes" else str(raw).strip()
        limit = TEXT_LIMITS.get(name)
        if limit and len(value) > limit:
            errors[name] = f"Keep this under {limit} characters (currently {len(value)})."
        return value

    # Identity
    asin = normalise_asin(data.get("asin"))
    if asin is not None and not ASIN_RE.match(asin):
        errors["asin"] = "An ASIN is 10 letters and numbers, for example B0ABCDE123."
    elif asin and not (asin.startswith("B0") or re.fullmatch(r"\d{9}[\dX]", asin)):
        warnings["asin"] = "Most Amazon ASINs start with B0 (books use a 10-digit ISBN). Double-check this one."
    p.asin = asin
    p.title = text("title")
    p.brand = text("brand")
    p.category = text("category")
    p.bsr_category = text("bsr_category")
    p.supplier = text("supplier")
    p.notes = text("notes")

    fee_cat = match_fee_category(data.get("fee_category"))
    if fee_cat is None:
        errors["fee_category"] = "Choose a referral fee category from the list."
        fee_cat = "everything_else"
    p.fee_category = fee_cat

    url = text("amazon_url")
    if url:
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host or "." not in host or " " in url:
            errors["amazon_url"] = "Enter a full web address, for example https://www.amazon.co.uk/dp/B0ABCDE123."
        else:
            if "amazon." in host and not host.endswith("amazon.co.uk"):
                warnings["amazon_url"] = "This link is not amazon.co.uk — fees and prices here are for the UK store."
            elif "amazon." not in host:
                warnings["amazon_url"] = "This is not an Amazon link."
            url = canonical_amazon_url(url)
            m = re.search(r"/dp/([A-Z0-9]{10})", url or "")
            if m and asin and m.group(1) != asin and "asin" not in errors:
                errors["amazon_url"] = f"The link is for ASIN {m.group(1)}, but the ASIN field says {asin}."
            elif m and not asin:
                p.asin = m.group(1)
    p.amazon_url = url

    # Numbers
    money_fields = [
        ("selling_price", "Amazon selling price", MAX_PRICE),
        ("sourcing_price", "Sourcing price", MAX_PRICE),
        ("shipping_prep", "Shipping / prep cost", MAX_PRICE),
        ("other_costs", "Other costs", MAX_PRICE),
        ("referral_fee_override", "Referral fee", MAX_PRICE),
        ("fba_fee_override", "FBA fee", MAX_PRICE),
    ]
    for name, label, maximum in money_fields:
        value, err = parse_number(data.get(name), label, maximum=maximum)
        if err:
            errors[name] = err
        setattr(p, name, value)

    whole_fields = [
        ("bsr", "Best Sellers Rank", 1, MAX_BSR),
        ("monthly_sales", "Estimated monthly sales", 0, MAX_SALES),
        ("total_sellers", "Total sellers", 0, MAX_SELLERS),
        ("fba_sellers", "FBA sellers", 0, MAX_SELLERS),
    ]
    for name, label, minimum, maximum in whole_fields:
        raw = data.get(name)
        value, err = parse_whole(raw, label, minimum=minimum, maximum=maximum)
        if err and name == "bsr" and value is None and not is_blank(raw) and str(raw).strip() in {"0", "-0"}:
            err = "Best Sellers Rank must be a positive number (1 is the best rank)."
        if err:
            errors[name] = err
        setattr(p, name, value)

    if p.total_sellers is not None and p.fba_sellers is not None and p.fba_sellers > p.total_sellers:
        errors["fba_sellers"] = f"FBA sellers ({p.fba_sellers}) can't be more than total sellers ({p.total_sellers})."

    for name, label, maximum in [("weight_g", "Weight", 1_000_000), ("length_cm", "Length", 1000),
                                 ("width_cm", "Width", 1000), ("height_cm", "Height", 1000)]:
        raw = data.get(name)
        if name == "weight_g" and is_blank(raw) and not is_blank(data.get("weight_kg")):
            kg, err = parse_number(data.get("weight_kg"), "Weight (kg)", maximum=1000)
            value = None if kg is None else round(kg * 1000, 1)
        else:
            value, err = parse_number(raw, label, maximum=maximum)
        if not err and value is not None and value <= 0:
            err = f"{label} must be more than 0."
        if err:
            errors[name] = err
        setattr(p, name, value)
    dims = [p.length_cm, p.width_cm, p.height_cm]
    if any(d is not None for d in dims) and any(d is None for d in dims) and not errors.keys() & {"length_cm", "width_cm", "height_cm"}:
        errors["length_cm"] = "Enter all three dimensions (length, width and height), or leave all three empty."

    fulfilment, err = parse_fulfilment(data.get("fulfilment"))
    if err:
        errors["fulfilment"] = err
    p.fulfilment = fulfilment or FBA

    restriction, err = parse_restriction(data.get("restriction_status"))
    if err:
        errors["restriction_status"] = err
    p.restriction_status = restriction or RESTRICTION_UNKNOWN

    for key in FLAG_KEYS:
        raw = data.get(key)
        if raw is None and not checkbox_form and base is not None:
            continue
        value, err = parse_bool(raw)
        if err:
            errors[key] = err
            value = False
        setattr(p, key, bool(value))

    source = data.get("source") or (base.source if base else SOURCE_MANUAL)
    p.source = source if source in SOURCE_LABELS else SOURCE_MANUAL

    if not (p.asin or p.title or p.amazon_url):
        errors["title"] = "Enter at least an ASIN, a product title or an Amazon URL so you can recognise this product."

    if p.selling_price is not None and p.selling_price == 0:
        errors["selling_price"] = "Amazon selling price must be more than £0."
    if p.selling_price is not None and p.selling_price > 10_000 and "selling_price" not in errors:
        warnings["selling_price"] = "That is a very high price — double-check it."
    if p.fulfilment == FBM and p.fba_fee_override:
        warnings["fba_fee_override"] = "FBM products don't pay an FBA fee, so this value is ignored."

    return ValidationResult(p, errors, warnings)
