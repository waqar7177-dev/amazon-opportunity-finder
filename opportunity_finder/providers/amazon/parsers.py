"""Parse Amazon HTML (search results, product page, All Offers Display) into plain data.

Pure functions of an HTML string — no network — so they are tested against fixture pages.
Every parser returns None for anything it cannot find; nothing is ever filled in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from ...parsers.amazon_text import _grams

INVISIBLE = re.compile(r"[​‌‍‎‏﻿]")
ASIN_RE = re.compile(r"^(B0[A-Z0-9]{8}|\d{9}[\dX])$")
AMAZON_SELLER = re.compile(r"^amazon(\.co\.uk|\.com)?(\s+(eu|uk|export|media)\b.*)?$", re.I)
BOUGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([KkMm])?\s*\+\s*bought in (?:the )?past month", re.I)
GBP_RE = re.compile(r"£\s*(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d{1,2}))?")


def clean(text: str | None) -> str:
    return INVISIBLE.sub("", re.sub(r"\s+", " ", text or "")).strip()


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


def gbp(text: str | None) -> float | None:
    """A £ amount, or None — prices in any other currency are ignored, never converted."""
    m = GBP_RE.search(text or "")
    if not m:
        return None
    return round(int(m.group(1).replace(",", "")) + int((m.group(2) or "0").ljust(2, "0")) / 100, 2)


def bought_lower_bound(text: str | None) -> tuple[int | None, str | None]:
    m = BOUGHT_RE.search(text or "")
    if not m:
        return None, None
    value = float(m.group(1)) * {"k": 1000, "m": 1_000_000}.get((m.group(2) or "").lower(), 1)
    return int(value), clean(m.group(0))


# ------------------------------------------------------------ page health
@dataclass
class PageCheck:
    kind: str  # ok | captcha | challenge | throttled | not_found | signin | empty
    message: str = ""

    @property
    def blocked(self) -> bool:
        return self.kind in ("captcha", "challenge", "signin")


def classify_page(html: str, status: int | None = None, url: str = "") -> PageCheck:
    """Decide whether a response is real content or a block / error page. Checked before any parsing,
    so a CAPTCHA page can never be read as product data."""
    body = html or ""
    low = body.lower()
    if "validatecaptcha" in low or "type the characters you see" in low or "enter the characters you see below" in low:
        return PageCheck("captcha", "Amazon asked for a CAPTCHA.")
    if "/ap/signin" in (url or "") or ('name="signIn"' in body and "ap_email" in body):
        return PageCheck("signin", "Amazon asked to sign in.")
    if ("gokuprops" in low or "awswafcookiedomainlist" in low) and len(body) < 20_000:
        return PageCheck("challenge", "Amazon showed a bot-check page instead of content.")
    if status in (429, 503) or "sorry! something went wrong" in low or "api-services-support@amazon.com" in low:
        return PageCheck("throttled", "Amazon is limiting requests right now.")
    if status == 404 or "looking for something?" in low and "we're sorry. the web address you entered" in low:
        return PageCheck("not_found", "The page does not exist.")
    if len(body.strip()) < 200:
        return PageCheck("empty", "Amazon returned an empty page.")
    return PageCheck("ok")


# ---------------------------------------------------------------- search
@dataclass
class SearchResult:
    asin: str
    title: str
    page: int
    position: int
    price: float | None = None
    bought_lower_bound: int | None = None
    bought_text: str | None = None
    sponsored: bool = False


@dataclass
class SearchPage:
    results: list[SearchResult]
    has_next: bool
    total_text: str | None = None


def parse_search_page(html: str, page: int = 1) -> SearchPage:
    soup = soup_of(html)
    results, seen = [], set()
    for el in soup.select('div[data-component-type="s-search-result"][data-asin]'):
        asin = (el.get("data-asin") or "").strip().upper()
        if not ASIN_RE.match(asin) or asin in seen:
            continue
        seen.add(asin)
        h2 = el.find("h2")
        title = clean(h2.get("aria-label") or h2.get_text(" ")) if h2 else ""
        price_el = el.select_one(".a-price:not(.a-text-price) .a-offscreen")
        lower, text = bought_lower_bound(el.get_text(" "))
        sponsored = bool(el.select_one(".puis-sponsored-label-text, .s-sponsored-label-text")) or bool(
            re.search(r"\bSponsored\b", el.get_text(" ")))
        results.append(SearchResult(asin=asin, title=title, page=page, position=len(results) + 1,
                                    price=gbp(price_el.get_text()) if price_el else None,
                                    bought_lower_bound=lower, bought_text=text, sponsored=sponsored))
    nxt = soup.select_one("a.s-pagination-next")
    total = soup.find(string=re.compile(r"results for"))
    return SearchPage(results=results, has_next=bool(nxt and nxt.get("href")), total_text=clean(str(total)) if total else None)


def parse_store_page(html: str) -> list[str]:
    """ASINs linked from an Amazon brand store page, in page order."""
    found = re.findall(r"/dp/(B0[A-Z0-9]{8})", html or "") + re.findall(r'data-asin="(B0[A-Z0-9]{8})"', html or "")
    return list(dict.fromkeys(found))


# --------------------------------------------------------------- product
@dataclass
class ProductPage:
    asin: str | None = None
    title: str | None = None
    brand: str | None = None
    brand_source: str | None = None  # byline | store | details | manufacturer
    manufacturer: str | None = None
    price: float | None = None
    price_note: str | None = None
    availability: str | None = None
    breadcrumbs: list[str] = field(default_factory=list)
    bsr: int | None = None
    bsr_category: str | None = None
    weight_g: float | None = None
    weight_source: str | None = None
    weight_note: str | None = None
    dims_cm: tuple[float, float, float] | None = None
    dims_source: str | None = None
    bought_lower_bound: int | None = None
    bought_text: str | None = None
    buybox_seller: str | None = None
    buybox_ships_from: str | None = None
    no_featured_offer: bool = False
    other_offers_count: int | None = None

    @property
    def category(self) -> str | None:
        return self.breadcrumbs[0] if self.breadcrumbs else self.bsr_category


def _detail_pairs(soup: BeautifulSoup) -> list[tuple[str, str]]:
    pairs = []
    for li in soup.select("#detailBullets_feature_div li"):
        text = clean(li.get_text(" "))
        if ":" in text:
            key, value = text.split(":", 1)
            pairs.append((clean(key), clean(value)))
    for tr in soup.select("table.a-keyvalue tr, #productDetails_detailBullets_sections1 tr, "
                          "#productDetails_techSpec_section_1 tr, #productDetails_techSpec_section_2 tr"):
        th, td = tr.find("th"), tr.find("td")
        if th and td:
            pairs.append((clean(th.get_text(" ")), clean(td.get_text(" "))))
    return pairs


def _first(pairs, pattern):
    rx = re.compile(pattern, re.I)
    return next((v for k, v in pairs if rx.fullmatch(k)), None)


def _weight(text: str | None) -> float | None:
    m = re.search(r"([\d.,]+)\s*(g|grams?|kg|kilograms?|lbs?|pounds?|oz|ounces?)\b", text or "", re.I)
    if not m:
        return None
    try:
        return round(_grams(float(m.group(1).replace(",", "")), m.group(2)), 1)
    except ValueError:
        return None


def _dims(text: str | None) -> tuple[float, float, float] | None:
    m = re.search(r"([\d.]+)\s*x\s*([\d.]+)\s*x\s*([\d.]+)\s*(cm|mm|centimetres|millimetres|inches|in)\b", text or "", re.I)
    if not m:
        return None
    factor = {"mm": 0.1, "millimetres": 0.1, "inches": 2.54, "in": 2.54}.get(m.group(4).lower(), 1)
    try:
        return tuple(round(float(m.group(i)) * factor, 1) for i in (1, 2, 3))  # type: ignore[return-value]
    except ValueError:
        return None


def _price_to_pay(soup: BeautifulSoup) -> float | None:
    core = soup.select_one("#corePriceDisplay_desktop_feature_div, #corePrice_feature_div, #apex_desktop")
    if core is not None:
        pay = core.select_one(".priceToPay, .apex-pricetopay-value")
        if pay is not None:
            whole, fraction = pay.select_one(".a-price-whole"), pay.select_one(".a-price-fraction")
            symbol = pay.select_one(".a-price-symbol")
            if whole is not None and (symbol is None or "£" in symbol.get_text()):
                digits = re.sub(r"[^\d]", "", whole.get_text())
                cents = re.sub(r"[^\d]", "", fraction.get_text()) if fraction else "00"
                if digits:
                    return round(int(digits) + int((cents or "0").ljust(2, "0")[:2]) / 100, 2)
            value = gbp(pay.select_one(".a-offscreen").get_text()) if pay.select_one(".a-offscreen") else None
            if value is not None:
                return value
        for off in core.select(".a-price:not(.a-text-price) .a-offscreen"):
            if off.find_parent(class_=re.compile("pricePerUnit")):
                continue
            value = gbp(off.get_text())
            if value is not None:
                return value
    field_el = soup.select_one("input#twister-plus-price-data-price")
    if field_el is not None and field_el.get("value"):
        try:
            return round(float(field_el["value"]), 2)
        except ValueError:
            return None
    return None


def parse_product_page(html: str, asin_hint: str | None = None) -> ProductPage:
    soup = soup_of(html)
    p = ProductPage()
    pairs = _detail_pairs(soup)
    page_text = clean(soup.get_text(" "))

    asin = _first(pairs, r"ASIN")
    p.asin = (asin or asin_hint or "").strip().upper() or None
    title = soup.select_one("#productTitle")
    p.title = clean(title.get_text(" ")) if title else None

    byline = clean(soup.select_one("#bylineInfo").get_text(" ")) if soup.select_one("#bylineInfo") else ""
    brand_detail = _first(pairs, r"Brand( Name)?")
    p.manufacturer = _first(pairs, r"Manufacturer")
    m = re.match(r"^Brand:\s*(.+)$", byline, re.I)
    store = re.search(r"Visit the (.+?) Store", byline, re.I)
    if m:
        p.brand, p.brand_source = clean(m.group(1)), "byline"
    elif store:
        p.brand, p.brand_source = clean(store.group(1)), "store"
    elif brand_detail:
        p.brand, p.brand_source = brand_detail, "details"
    elif p.manufacturer:
        p.brand, p.brand_source = p.manufacturer, "manufacturer"

    p.price = _price_to_pay(soup)
    if p.price is None and re.search(r"No featured offers available|Currently unavailable", page_text, re.I):
        p.price_note = "No Buy Box price is shown for this listing."
    elif p.price is None and re.search(r"\b(PKR|USD|EUR|INR)\s?[\d,]", page_text):
        p.price_note = "Prices were shown in another currency — the UK delivery location was not applied."
    availability = soup.select_one("#availability")
    p.availability = clean(availability.get_text(" ")) or None if availability else None
    if re.search(r"No featured offers available", page_text, re.I):
        p.no_featured_offer = True

    crumbs = soup.select("#wayfinding-breadcrumbs_feature_div li a, #wayfinding-breadcrumbs_feature_div a")
    p.breadcrumbs = [c for c in dict.fromkeys(clean(a.get_text(" ")) for a in crumbs) if c]

    rank_text = _first(pairs, r"Best Sellers Rank") or ""
    rank = re.search(r"#?\s*([\d,]+)\s+in\s+([^(]+?)\s*(?:\(|$)", rank_text)
    if rank:
        p.bsr = int(rank.group(1).replace(",", ""))
        p.bsr_category = clean(rank.group(2))

    package_dims = _first(pairs, r"Package Dimensions|Item Package Dimensions.*")
    product_dims = _first(pairs, r"Product Dimensions|Item Dimensions.*|Dimensions")
    if package_dims and _dims(package_dims):
        p.dims_cm, p.dims_source = _dims(package_dims), "package"
    elif product_dims and _dims(product_dims):
        p.dims_cm, p.dims_source = _dims(product_dims), "product"

    candidates = [
        ("item package weight", _weight(_first(pairs, r"Item Package Weight|Package Weight"))),
        ("package dimensions", _weight(package_dims.split(";", 1)[1]) if package_dims and ";" in package_dims else None),
        ("product dimensions", _weight(product_dims.split(";", 1)[1]) if product_dims and ";" in product_dims else None),
        ("item weight", _weight(_first(pairs, r"Item Weight|Weight"))),
    ]
    found = [(src, w) for src, w in candidates if w]
    if found:
        # The heaviest value is used: under-stating weight would under-state the FBA fee.
        src, weight = max(found, key=lambda sw: sw[1])
        p.weight_g, p.weight_source = weight, src
        if len({round(w) for _, w in found}) > 1 and max(w for _, w in found) > 1.25 * min(w for _, w in found):
            p.weight_note = "Amazon lists different weights for this item; the heaviest was used."

    p.bought_lower_bound, p.bought_text = bought_lower_bound(page_text)

    merchant = soup.select_one("[offer-display-feature-name='desktop-merchant-info'] .offer-display-feature-text-message")
    fulfiller = soup.select_one("[offer-display-feature-name='desktop-fulfiller-info'] .offer-display-feature-text-message")
    if merchant is not None:
        p.buybox_seller = clean(merchant.get_text(" ")) or None
        p.buybox_ships_from = clean(fulfiller.get_text(" ")) if fulfiller is not None else p.buybox_seller
    elif soup.select_one("#sellerProfileTriggerId"):
        p.buybox_seller = clean(soup.select_one("#sellerProfileTriggerId").get_text(" "))

    olp = re.search(r"Other sellers on Amazon\s*(\d+)\s+options?", page_text, re.I)
    if olp:
        p.other_offers_count = int(olp.group(1))
    return p


# ----------------------------------------------------------------- offers
@dataclass
class Offer:
    seller: str | None
    ships_from: str | None
    price: float | None = None

    @property
    def is_amazon(self) -> bool:
        return bool(self.seller and AMAZON_SELLER.match(self.seller))

    @property
    def fba(self) -> bool:
        return bool(self.ships_from and AMAZON_SELLER.match(self.ships_from))


@dataclass
class OffersPage:
    pinned: Offer | None
    offers: list[Offer]
    other_count: int | None

    @property
    def complete(self) -> bool:
        return self.other_count is None or len(self.offers) >= self.other_count

    def all_offers(self) -> list[Offer]:
        return ([self.pinned] if self.pinned else []) + self.offers

    @property
    def total_sellers(self) -> int:
        names = {(o.seller or f"offer-{i}").lower() for i, o in enumerate(self.all_offers())}
        counted = len(names)
        if not self.complete:
            counted = (1 if self.pinned else 0) + (self.other_count or 0)
        return counted

    @property
    def fba_sellers(self) -> int:
        return len({(o.seller or "").lower() for o in self.all_offers() if o.fba and not o.is_amazon})

    @property
    def amazon_sells(self) -> bool:
        return any(o.is_amazon for o in self.all_offers())


def _offer(block) -> Offer | None:
    ships = block.select_one("#aod-offer-shipsFrom .a-col-right")
    sold = block.select_one("#aod-offer-soldBy .a-col-right a, #aod-offer-soldBy .a-col-right .a-size-small")
    if ships is None and sold is None:
        return None
    price_el = block.select_one(".a-price:not(.a-text-price) .a-offscreen")
    return Offer(seller=clean(sold.get_text(" ")) if sold else None, ships_from=clean(ships.get_text(" ")) if ships else None,
                 price=gbp(price_el.get_text()) if price_el else None)


def parse_offers_page(html: str) -> OffersPage:
    soup = soup_of(html)
    pinned_el = soup.select_one("#aod-pinned-offer")
    pinned = _offer(pinned_el) if pinned_el is not None else None
    offers = [o for o in (_offer(b) for b in soup.select("#aod-offer-list #aod-offer, #aod-offer")) if o]
    unique, seen = [], set()
    for o in offers:  # the same block can match both selectors
        key = (o.seller, o.ships_from, o.price)
        if key not in seen:
            seen.add(key)
            unique.append(o)
    total_el = soup.select_one("#aod-total-offer-count")
    other_count = None
    if total_el is not None and str(total_el.get("value", "")).isdigit():
        other_count = int(total_el["value"])
    return OffersPage(pinned=pinned, offers=unique, other_count=other_count)
