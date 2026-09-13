"""Smart Paste: pull likely product facts out of text copied from an Amazon UK page.

This never fetches anything. It reads only the text the user pasted, suggests
values with a confidence level and the snippet it came from, and leaves the
final decision to the user. Nothing extracted here is saved without review.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

INVISIBLE = dict.fromkeys(map(ord, "‎‏​‌‍﻿⁠"), None)

HIGH, MEDIUM, LOW = "high", "medium", "low"


@dataclass
class Extracted:
    value: object
    confidence: str
    evidence: str = ""
    note: str = ""


@dataclass
class PriceCandidate:
    value: float
    context: str
    score: int
    occurrences: int = 1


@dataclass
class ParseResult:
    fields: dict[str, Extracted] = field(default_factory=dict)
    price_candidates: list[PriceCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def found_any(self) -> bool:
        return bool(self.fields)

    def values(self) -> dict:
        return {k: v.value for k, v in self.fields.items()}

    def to_dict(self) -> dict:
        return {
            "fields": {k: asdict(v) for k, v in self.fields.items()},
            "price_candidates": [asdict(c) for c in self.price_candidates],
            "warnings": self.warnings,
            "info": self.info,
        }


# ---------------------------------------------------------------- helpers
def normalise(text: str) -> str:
    text = (text or "").translate(INVISIBLE).replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"GBP\s*(\d)", r"£\1", text)
    # "£\n12\n.\n99" (Amazon's split price markup) -> "£12.99"
    text = re.sub(r"£\s*(\d[\d,]*)\s*\.\s*(\d{2})(?!\d)", r"£\1.\2", text)
    return text


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.split("\n")]


def _next_value(lines: list[str], index: int, max_len: int = 80) -> str | None:
    for ln in lines[index + 1:index + 4]:
        if ln:
            return ln if len(ln) <= max_len else None
    return None


def _snippet(text: str, limit: int = 110) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _to_int(raw: str) -> int | None:
    digits = raw.replace(",", "").strip()
    return int(digits) if digits.isdigit() else None


def _grams(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit.startswith("kg") or unit.startswith("kilo"):
        return value * 1000
    if unit in {"lb", "lbs"} or unit.startswith("pound"):
        return value * 453.592
    if unit == "oz" or unit.startswith("ounce"):
        return value * 28.3495
    return value


# ------------------------------------------------------------------- ASIN
ASIN_LABEL = re.compile(r"\bASIN\b\s*[:：\t]?\s*([A-Z0-9]{10})\b", re.IGNORECASE)
ASIN_URL = re.compile(r"/(?:dp|gp/product|gp/aw/d|product-reviews)/([A-Z0-9]{10})(?=[/?#\s]|$)", re.IGNORECASE)
ASIN_BARE = re.compile(r"\b(B0[A-Z0-9]{8})\b")


def _valid_asin(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{10}", value)) and any(ch.isdigit() for ch in value)


def extract_asin(text: str, result: ParseResult) -> None:
    labeled = [m.group(1).upper() for m in ASIN_LABEL.finditer(text) if _valid_asin(m.group(1).upper())]
    from_url = [m.group(1).upper() for m in ASIN_URL.finditer(text) if _valid_asin(m.group(1).upper())]
    bare = list(dict.fromkeys(m.group(1) for m in ASIN_BARE.finditer(text)))

    if labeled:
        value, conf, evidence = labeled[0], HIGH, f"ASIN: {labeled[0]}"
    elif from_url:
        value, conf, evidence = from_url[0], HIGH, f"/dp/{from_url[0]}"
    elif bare:
        value, conf, evidence = bare[0], MEDIUM if len(bare) == 1 else LOW, bare[0]
    else:
        return

    distinct = list(dict.fromkeys(labeled + from_url + bare))
    note = ""
    if len(distinct) > 1:
        conf = LOW if conf != HIGH else MEDIUM
        others = ", ".join(a for a in distinct if a != value)
        note = f"Other ASIN-like codes were also found ({others})."
        result.warnings.append(f"Several ASIN-like codes found. {value} is suggested — check it matches the product.")
    result.fields["asin"] = Extracted(value, conf, evidence, note)


# -------------------------------------------------------------------- URL
AMAZON_URL = re.compile(r"https?://(?:www\.|smile\.)?amazon\.([a-z.]{2,6})/[^\s\"'<>]*", re.IGNORECASE)


def extract_url(text: str, result: ParseResult) -> None:
    match = AMAZON_URL.search(text)
    asin = result.fields.get("asin")
    if match:
        domain = match.group(1).lower()
        if domain != "co.uk":
            result.warnings.append(f"The pasted link is for amazon.{domain}, not amazon.co.uk. Fees and prices here are for the UK.")
        url_asin = ASIN_URL.search(match.group(0))
        if domain == "co.uk" and url_asin:
            canonical = f"https://www.amazon.co.uk/dp/{url_asin.group(1).upper()}"
            result.fields["amazon_url"] = Extracted(canonical, HIGH, _snippet(match.group(0)), "Shortened to the clean /dp/ link.")
        else:
            result.fields["amazon_url"] = Extracted(match.group(0).rstrip(".,)"), MEDIUM, _snippet(match.group(0)))
    elif asin is not None:
        result.fields["amazon_url"] = Extracted(f"https://www.amazon.co.uk/dp/{asin.value}", MEDIUM, "",
                                                "Built from the ASIN — no link was in the pasted text.")


# ------------------------------------------------------------------ price
PRICE = re.compile(r"£\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?")

PRICE_RULES = [
    (re.compile(r"\b(rrp|list price|was:?|typical price|recommended retail)\b", re.I), -40, "reference price"),
    (re.compile(r"/\s?(100\s?(g|ml)|kg|l|litre|count|unit|each|item)\b|\bper (100|kg|litre|count|unit)", re.I), -50, "unit price"),
    (re.compile(r"\b(delivery|dispatch|postage|shipping)\b", re.I), -40, "delivery"),
    (re.compile(r"\b(save|saving|coupon|voucher|discount of|off)\b", re.I), -30, "saving"),
    (re.compile(r"\b(subscribe|s&s)\b", re.I), -20, "subscribe & save"),
    (re.compile(r"\b(gift card|credit|sign up|prime membership|reward)\b", re.I), -30, "promotion"),
    (re.compile(r"\bfrom\s*£", re.I), -10, "lowest offer"),
    (re.compile(r"\b(price|buy new|deal price|our price)\b", re.I), 30, "price label"),
    (re.compile(r"-\s?\d{1,2}%|\bwith \d+ percent savings\b", re.I), 25, "current discounted price"),
]


def extract_prices(text: str, result: ParseResult) -> None:
    lines = text.split("\n")
    seen: dict[float, PriceCandidate] = {}
    first = True
    order: list[float] = []
    for idx, line in enumerate(lines):
        for m in PRICE.finditer(line):
            whole = m.group(1).replace(",", "")
            pence = (m.group(2) or "0").ljust(2, "0")
            value = round(int(whole) + int(pence) / 100, 2)
            if value <= 0:
                continue
            # Score from the text right around the price, plus the line before it
            # ("RRP:" and "Price:" labels often sit on their own line).
            local = line[max(0, m.start() - 40): m.end() + 30]
            prev = lines[idx - 1].strip() if idx > 0 else ""
            score = 10
            for pattern, points, _ in PRICE_RULES:
                if pattern.search(local) or (points < 0 and len(prev) <= 25 and pattern.search(prev) and not PRICE.search(prev)):
                    score += points
            if first and score >= 10:
                score += 15
            first = False
            context = _snippet((prev + " " if len(prev) <= 25 and prev and not PRICE.search(prev) else "") + line.strip())
            if value in seen:
                cand = seen[value]
                cand.occurrences += 1
                if score > cand.score:
                    cand.score, cand.context = score, context
            else:
                seen[value] = PriceCandidate(value, context, score)
                order.append(value)

    candidates = [seen[v] for v in order]
    for cand in candidates:
        if cand.occurrences > 1:
            cand.score += 10
    result.price_candidates = sorted(candidates, key=lambda c: (-c.score, order.index(c.value)))

    if not candidates:
        if re.search(r"[$€]\s?\d", text):
            result.warnings.append("No £ prices were found, only other currencies. This may not be an Amazon UK page.")
        return
    best = result.price_candidates[0]
    if best.score < 0:
        result.warnings.append("Prices were found, but none looks like the selling price (they look like delivery, "
                               "savings or reference prices). Enter the selling price yourself.")
        return
    if len(candidates) == 1:
        conf = HIGH if best.score >= 25 else MEDIUM
    else:
        runner_up = result.price_candidates[1].score
        conf = MEDIUM if best.score - runner_up >= 20 else LOW
        listed = ", ".join(f"£{c.value:,.2f}" for c in result.price_candidates[:6])
        result.warnings.append(f"Several prices found ({listed}). £{best.value:,.2f} is suggested — "
                               "please verify the current selling price.")
    result.fields["selling_price"] = Extracted(best.value, conf, best.context,
                                               "Suggested as the most likely selling price. Not guaranteed — verify it.")


# -------------------------------------------------------------------- BSR
BSR_LABELED = re.compile(r"Best\s*Sellers?\s*Rank\s*[:：\t]?\s*(?:#\s*)?([\d,]+)\s+in\s+([^\n(]+)", re.I)
BSR_LINE = re.compile(r"^#?\s*([\d,]+)\s+in\s+([A-Z][^\n(]{2,80}?)\s*(?:\(|$)")


def extract_bsr(text: str, result: ParseResult) -> None:
    match = BSR_LABELED.search(text)
    confidence = HIGH
    if not match:
        for line in _lines(text):
            m = BSR_LINE.match(line)
            if m and "see top 100" in line.lower():
                match, confidence = m, MEDIUM
                break
    if not match:
        return
    rank = _to_int(match.group(1))
    category = match.group(2).strip().rstrip(" :-")
    if rank is None or rank <= 0:
        return
    result.fields["bsr"] = Extracted(rank, confidence, _snippet(match.group(0)))
    if category:
        result.fields["bsr_category"] = Extracted(category, confidence, _snippet(match.group(0)))
        result.fields["category"] = Extracted(category, MEDIUM, _snippet(match.group(0)),
                                              "Main Best Sellers Rank category.")
    tail = text[match.end(): match.end() + 400]
    subs = [f"#{m.group(1)} in {m.group(2).strip()}" for m in re.finditer(r"\n\s*#?\s*([\d,]+)\s+in\s+([^\n(]+)", tail)][:3]
    if subs:
        result.info.append("Sub-category ranks: " + "; ".join(subs) + ".")


def extract_breadcrumb(text: str, result: ParseResult) -> None:
    if "category" in result.fields:
        return
    joined = re.sub(r"\n\s*›\s*\n", " › ", text)
    for line in _lines(joined):
        if "›" in line and 3 < len(line) < 200:
            first = line.split("›")[0].strip()
            if first and len(first) < 60:
                result.fields["category"] = Extracted(first, LOW, _snippet(line), "Taken from the category breadcrumb.")
                return


# ------------------------------------------------------------------ brand
BRAND_STORE = re.compile(r"Visit the (.{1,60}?) Store\b")
BRAND_LABEL = re.compile(r"^\s*Brand(?:\s*name)?\s*(?:[:：]\s*|\t+\s*)(.{1,80})$", re.I | re.M)
MANUFACTURER_LABEL = re.compile(r"^\s*Manufacturer\s*(?:[:：]\s*|\t+\s*)(.{1,80})$", re.I | re.M)


def extract_brand(text: str, result: ParseResult) -> None:
    lines = _lines(text)
    store = BRAND_STORE.search(text)
    label = BRAND_LABEL.search(text)
    if label:
        result.fields["brand"] = Extracted(_clean_brand(label.group(1)), HIGH, _snippet(label.group(0)))
    elif store:
        result.fields["brand"] = Extracted(_clean_brand(store.group(1)), HIGH, _snippet(store.group(0)))
    else:
        for i, line in enumerate(lines):
            if line.lower() in {"brand", "brand name"}:
                value = _next_value(lines, i, 60)
                if value:
                    result.fields["brand"] = Extracted(_clean_brand(value), MEDIUM, f"Brand {value}")
                    return
        manufacturer = MANUFACTURER_LABEL.search(text)
        if manufacturer:
            result.fields["brand"] = Extracted(_clean_brand(manufacturer.group(1)), LOW, _snippet(manufacturer.group(0)),
                                               "Taken from Manufacturer — the brand may differ.")


def _clean_brand(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" :;,.-")


# ------------------------------------------------------------------ title
NOISE = re.compile(
    r"skip to|sign in|account & lists|returns|basket|deliver(ing)? to|update location|today's deals|customer service|"
    r"search amazon|back to results|sponsored|keep shopping|about this item|gift card|prime video|registry|"
    r"out of 5 stars|ratings?\b|bought in past month|£|visit the|see more|click to|roll over|amazon's choice|"
    r"best seller|in stock|add to basket|buy now|share|report an issue|select delivery location",
    re.I,
)


def _title_like(line: str) -> bool:
    return 15 <= len(line) <= 300 and len(line.split()) >= 3 and not NOISE.search(line) and "›" not in line


def extract_title(text: str, result: ParseResult) -> None:
    page_title = re.search(r"Amazon\.co\.uk\s*:\s*(.{10,300}?)\s*:\s*[A-Z][\w&,' ]{2,60}\s*$", text, re.M)
    if page_title and _title_like(page_title.group(1)):
        result.fields["title"] = Extracted(page_title.group(1).strip(), MEDIUM, _snippet(page_title.group(0)),
                                           "Taken from the page title.")
        return
    lines = _lines(text)
    anchors = [i for i, ln in enumerate(lines)
               if BRAND_STORE.search(ln) or re.match(r"^Brand\s*:", ln, re.I) or re.search(r"out of 5 stars", ln, re.I)]
    for anchor in anchors[:3]:
        for j in range(anchor - 1, max(-1, anchor - 4), -1):
            if lines[j] and _title_like(lines[j]):
                result.fields["title"] = Extracted(lines[j], MEDIUM, _snippet(lines[j]),
                                                   "The line just above the brand / rating.")
                return
    for line in lines[:60]:
        if _title_like(line) and len(line) >= 25:
            result.fields["title"] = Extracted(line, LOW, _snippet(line), "Best guess — check the product title.")
            return


# ---------------------------------------------------------------- sellers
SHIP_LINE = re.compile(r"^(?:dispatches|dispatched|ships|shipped)\s+from(\s+and\s+sold\s+by)?\s*[:\t]?\s*(.*)$", re.I)
SOLD_LINE = re.compile(r"^sold\s+by\s*[:\t]?\s*(.*)$", re.I)
SOLD_FULFILLED = re.compile(r"sold by\s+(.+?)\s+and\s+fulfilled by\s+amazon", re.I)
NEW_OFFERS = re.compile(r"\bNew\s*\((\d+)\)\s*from|\b(\d+)\s+(?:new\s+)?offers?\s+from", re.I)
AMAZON_SELLER = re.compile(r"^amazon(\.co\.uk)?(\s+(eu|uk|export|media)\b.*)?$", re.I)


def extract_sellers(text: str, result: ParseResult) -> None:
    lines = _lines(text)
    ships: list[tuple[int, str]] = []
    solds: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        combined = SOLD_FULFILLED.search(line)
        if combined:
            solds.append((i, combined.group(1).strip()))
            ships.append((i, "Amazon"))
            continue
        ship = SHIP_LINE.match(line)
        if ship:
            value = ship.group(2).strip() or _next_value(lines, i) or ""
            ships.append((i, value))
            if ship.group(1):
                solds.append((i, value))
            continue
        sold = SOLD_LINE.match(line)
        if sold:
            value = sold.group(1).strip() or _next_value(lines, i) or ""
            if value:
                solds.append((i, value))

    offers: list[tuple[str, bool]] = []
    used: set[int] = set()
    for idx, seller in solds:
        best = None
        for s_pos, (s_idx, s_val) in enumerate(ships):
            if s_pos in used or abs(s_idx - idx) > 4:
                continue
            if best is None or abs(s_idx - idx) < abs(ships[best][0] - idx):
                best = s_pos
        fba = False
        if best is not None:
            used.add(best)
            fba = "amazon" in ships[best][1].lower()
        offers.append((_clean_brand(seller), fba))

    amazon_offer = any(AMAZON_SELLER.match(name) for name, _ in offers)
    if amazon_offer:
        result.fields["flag_amazon_sells"] = Extracted(True, HIGH if len(offers) >= 1 else MEDIUM,
                                                       "Sold by Amazon", "Amazon appears as a seller on this listing.")

    count_match = NEW_OFFERS.search(text)
    stated = None
    if count_match:
        stated = int(count_match.group(1) or count_match.group(2))

    if len(offers) >= 2:
        sellers: dict[str, bool] = {}
        for name, fba in offers:
            key = name.lower()
            sellers[key] = sellers.get(key, False) or fba
        total = len(sellers)
        fba_count = sum(1 for name, fba in sellers.items() if fba and not AMAZON_SELLER.match(name))
        evidence = f"{len(offers)} offers found in the pasted offers list"
        note = "Counted from the offers you pasted. Amazon itself is counted as a seller but not as an FBA seller."
        conf = MEDIUM
        if stated and stated > total:
            result.warnings.append(f"Amazon states {stated} offers but only {total} sellers were in the pasted text — "
                                   "seller counts may be incomplete. Paste the full offers list or enter them yourself.")
            total, conf = stated, LOW
        result.fields["total_sellers"] = Extracted(total, conf, evidence, note)
        result.fields["fba_sellers"] = Extracted(fba_count, conf, evidence, note)
    elif stated:
        result.fields["total_sellers"] = Extracted(stated, LOW, _snippet(count_match.group(0)),
                                                   "Amazon's “New (N) from” offer count — may not match the number of sellers.")
        result.info.append("FBA sellers can only be counted from the full offers list (“Other sellers on Amazon”).")
    elif solds:
        result.info.append("Only the Buy Box seller was found. Paste the “Other sellers on Amazon” list to count sellers.")


# ---------------------------------------------------------- monthly sales
BOUGHT = re.compile(r"(\d+(?:[.,]\d+)?)\s*([KkMm])?\s*\+?\s*bought in (?:the )?past month", re.I)


def extract_monthly_sales(text: str, result: ParseResult) -> None:
    m = BOUGHT.search(text)
    if not m:
        return
    number = float(m.group(1).replace(",", "."))
    multiplier = {"k": 1000, "m": 1_000_000}.get((m.group(2) or "").lower(), 1)
    value = int(number * multiplier)
    result.fields["monthly_sales"] = Extracted(value, LOW, _snippet(m.group(0)),
                                               "Amazon's “bought in past month” badge is a rounded lower bound, "
                                               "not an exact sales figure.")


# ----------------------------------------------------- weight & dimensions
DIMS = re.compile(
    r"(Package|Product|Item)\s+Dimensions?(?:\s*L\s*x\s*W\s*x\s*H)?\s*[:：\t]?\s*"
    r"([\d.]+)\s*x\s*([\d.]+)\s*x\s*([\d.]+)\s*(cm|centimetres|centimeters|mm|millimetres|millimeters|inches|in)\b"
    r"(?:\s*;\s*([\d.,]+)\s*(g|grams|kg|kilograms|lbs?|pounds|oz|ounces)\b)?",
    re.I,
)
WEIGHT = re.compile(r"(Package|Item|Product)\s+Weight\s*[:：\t]?\s*([\d.,]+)\s*(g|grams|kg|kilograms|lbs?|pounds|oz|ounces)\b", re.I)


def extract_dimensions(text: str, result: ParseResult) -> None:
    dims = sorted(DIMS.finditer(text), key=lambda m: 0 if m.group(1).lower() == "package" else 1)
    if dims:
        m = dims[0]
        factor = {"mm": 0.1, "millimetres": 0.1, "millimeters": 0.1, "inches": 2.54, "in": 2.54}.get(m.group(5).lower(), 1)
        values = [round(float(m.group(i)) * factor, 1) for i in (2, 3, 4)]
        note = "Package dimensions from the listing." if m.group(1).lower() == "package" else \
            "Product (not package) dimensions — the packaged size can be larger."
        for key, value in zip(("length_cm", "width_cm", "height_cm"), values):
            result.fields[key] = Extracted(value, MEDIUM, _snippet(m.group(0)), note)
        if m.group(6):
            grams = round(_grams(float(m.group(6).replace(",", "")), m.group(7)), 1)
            result.fields["weight_g"] = Extracted(grams, MEDIUM, _snippet(m.group(0)), note)
    weights = sorted(WEIGHT.finditer(text), key=lambda m: 0 if m.group(1).lower() == "package" else 1)
    if weights and ("weight_g" not in result.fields or weights[0].group(1).lower() == "package"):
        m = weights[0]
        grams = round(_grams(float(m.group(2).replace(",", "")), m.group(3)), 1)
        result.fields["weight_g"] = Extracted(grams, MEDIUM, _snippet(m.group(0)), f"{m.group(1).title()} weight from the listing.")


# ------------------------------------------------------------------- main
EXTRACTORS = [
    ("ASIN", extract_asin), ("link", extract_url), ("price", extract_prices), ("Best Sellers Rank", extract_bsr),
    ("category", extract_breadcrumb), ("brand", extract_brand), ("title", extract_title),
    ("sellers", extract_sellers), ("monthly sales", extract_monthly_sales), ("dimensions", extract_dimensions),
]

MAX_CHARS = 400_000


def parse_amazon_text(raw: str | None) -> ParseResult:
    result = ParseResult()
    text = normalise(raw or "")
    if not text.strip():
        result.warnings.append("Nothing was pasted. Copy the Amazon UK product page text and paste it in.")
        return result
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        result.warnings.append("The pasted text was very long, so only the first part was read.")
    for name, extractor in EXTRACTORS:
        try:
            extractor(text, result)
        except Exception:  # noqa: BLE001 - one broken extractor must not break the others
            result.warnings.append(f"The {name} could not be read from this text.")
    if not result.found_any:
        result.warnings.append("Nothing recognisable was found. On the Amazon UK product page press Ctrl+A then Ctrl+C, "
                               "and paste everything here.")
    return result
