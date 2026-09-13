"""Brand → Amazon products → evaluation → Winning products.

The pipeline for one brand search:

    discover   search result pages → ASINs + titles (stop when results stop mentioning the brand)
    filter     title must name the brand; previously rejected ASINs are skipped unless re-evaluation is on
    collect    product page + All Offers Display → normalized Product with per-field provenance
    evaluate   the existing evaluator (fees, profit, rules, risk, score) — unchanged
    decide     outcome per ASIN; rejections are stored so future searches skip them

Every step writes its result to SQLite as it goes, so a search that stops (app closed, Amazon block,
error) keeps what it collected and can resume where it left off.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta
from typing import Callable

from ..constants import (COLLECTION_FAILED, ENGINE_VERSION, FBA, NOT_BRAND, REJECTED, RESTRICTION_UNKNOWN,
                         SKIPPED_REJECTED, SOURCE_AMAZON)
from ..database.repositories import ProductRepository
from ..database.research_repository import ResearchRepository, brand_key, now_iso
from ..domain.product import Product
from ..providers.amazon.browser import (BrowserUnavailable, CollectionBlocked, FetchFailed, PageNotFound, PageSource,
                                        describe_block)
from ..providers.amazon.categories import fee_category_for
from ..providers.amazon.marketplace import Marketplace
from ..providers.amazon.parsers import AMAZON_SELLER, parse_offers_page, parse_product_page, parse_search_page, parse_store_page
from .product_service import ProductService

log = logging.getLogger("opportunity_finder.research")

DONE_STAGES = {"evaluated", "skipped_rejected", "skipped_not_brand", "failed"}
# Fields that brand research owns. A value the user typed (field_meta source manual/import) is never overwritten.
AUTO_FIELDS = ["title", "brand", "category", "bsr_category", "amazon_url", "selling_price", "bsr", "monthly_sales",
               "total_sellers", "fba_sellers", "flag_amazon_sells", "weight_g", "length_cm", "width_cm", "height_cm",
               "availability", "fee_category"]
USER_SOURCES = {"manual", "import", "smart_paste"}


def _tokens(text: str) -> list[str]:
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).split()


def title_mentions_brand(title: str, brand: str, *, at_start: bool = False) -> bool:
    """Whole-word match that tolerates punctuation and spacing: "L'Oréal" matches "LOREAL Paris …";
    "Aero" does not match "AeroGarden"."""
    key = brand_key(brand)
    words = _tokens(title)
    if not key or not words:
        return False
    limit = 3 if at_start else len(words)
    for size in (1, 2, 3):
        for i in range(0, min(limit, len(words) - size + 1)):
            if "".join(words[i:i + size]) == key:
                return True
    return False


def brand_relevance(listed_brand: str | None, brand_source: str | None, title: str, brand: str) -> tuple[str, str | None]:
    """Decide whether a listing belongs to the searched brand, from its own brand field.

    Returns (relevance, reason_if_not_brand). A listing whose brand field names a different brand is not the
    brand, even when its title contains the word — "UniBond AERO 360" is UniBond, not Aero (FAILURES F16).
    A brand field that contains the searched brand as a whole word ("Nestlé Aero") counts as the brand."""
    if listed_brand and title_mentions_brand(listed_brand, brand):
        return "brand_verified", None
    if listed_brand and brand_source in ("byline", "store", "details"):
        # Amazon titles lead with the brand. "UniBond AERO 360 …" (brand UniBond) is UniBond's product line; "Aero Peppermint
        # Bar" listed under the manufacturer "Nestlé Česko s.r.o." is still Aero, but not confirmed (FAILURES F17).
        if not _title_starts_with(title, listed_brand) and _title_starts_with(title, brand):
            return "brand_uncertain", None
        return "brand_mismatch", f"Listed under the brand “{listed_brand}”, not “{brand}”."
    return "title_match", None


def _title_starts_with(title: str, name: str) -> bool:
    key, words = brand_key(name), _tokens(title)
    return bool(key) and any("".join(words[:size]) == key for size in (1, 2, 3, 4) if size <= len(words))


class StopRequested(Exception):
    pass


class BrandResearch:
    def __init__(self, conn: sqlite3.Connection, source: PageSource, marketplace: Marketplace, *,
                 now: Callable[[], datetime] = datetime.now, should_stop: Callable[[], bool] = lambda: False):
        self.conn = conn
        self.source = source
        self.marketplace = marketplace
        self.repo = ResearchRepository(conn)
        self.products = ProductRepository(conn)
        self.service = ProductService(conn)
        self._now = now
        self._should_stop = should_stop

    # ================================================================= run
    def run(self, search_id: int) -> dict:
        search = self.repo.get_search(search_id)
        if search is None:
            raise LookupError(search_id)
        settings = self.service.settings
        self.repo.update_search(search_id, status="running", phase="searching", message="Starting…", error=None,
                                started_at=search["started_at"] or now_iso(), finished_at=None,
                                criteria_fingerprint=settings.criteria_fingerprint())
        self.conn.commit()
        log.info("Brand search %s started: brand=%r reevaluate_rejected=%s", search_id, search["query"], bool(search["reevaluate_rejected"]))
        try:
            if not search["discovery_complete"]:
                self._discover(search, settings.research_max_pages)
            self._process(self.repo.get_search(search_id))
            self._finish(search_id, "completed", "Analysis complete.")
        except CollectionBlocked as exc:
            log.warning("Brand search %s stopped: Amazon block (%s)", search_id, exc.kind)
            self._finish(search_id, "blocked", describe_block(exc.kind) + " Results collected so far are kept — try again later.",
                         error=exc.kind)
        except BrowserUnavailable as exc:
            self._finish(search_id, "failed", str(exc), error="browser_unavailable")
        except StopRequested:
            self._finish(search_id, "cancelled", "Cancelled. Results collected so far are kept — you can resume later.")
        except Exception as exc:  # noqa: BLE001 - never leave a search stuck in "running"
            log.exception("Brand search %s failed", search_id)
            self._finish(search_id, "failed", "The analysis stopped because of an unexpected problem. Collected results are kept.",
                         error=type(exc).__name__)
        return self.repo.get_search(search_id)

    def _finish(self, search_id: int, status: str, message: str, error: str | None = None) -> None:
        self.repo.update_search(search_id, status=status, phase="done" if status == "completed" else status,
                                message=message, error=error, finished_at=now_iso())
        search = self.repo.get_search(search_id)
        self.repo.touch_brand(search["brand_id"])
        self.conn.commit()
        counts = self.repo.outcome_counts(search_id)
        log.info("Brand search %s %s: %s", search_id, status, {k: v for k, v in counts.items() if v})

    def _progress(self, search_id: int, **fields) -> None:
        self.repo.update_search(search_id, **fields)
        self.conn.commit()
        if self._should_stop():
            raise StopRequested()

    # ============================================================ discover
    def _discover(self, search: dict, max_pages: int) -> None:
        sid, brand = search["id"], search["query"]
        pages_without_brand = 0
        start_page = (search["pages_processed"] or 0) + 1
        for page in range(start_page, max_pages + 1):
            self._progress(sid, phase="searching", message=f"Searching Amazon… page {page}")
            result = parse_search_page(self.source.fetch(self.marketplace.search_url(brand, page), "search").html, page)
            matches = 0
            for r in result.results:
                relevant = title_mentions_brand(r.title, brand)
                matches += relevant
                if self.repo.item(sid, r.asin) is None:
                    self.repo.upsert_item(
                        sid, r.asin, title=r.title, page=page, position=r.position, sponsored=int(r.sponsored),
                        search_snapshot={"price": r.price, "bought_lower_bound": r.bought_lower_bound, "bought_text": r.bought_text},
                        relevance="title_match" if relevant else "no_title_match",
                        stage="discovered" if relevant else "skipped_not_brand", outcome=None if relevant else NOT_BRAND,
                        reasons=None if relevant else [f"The title does not name “{brand}”."])
            found = len(self.repo.items(sid))
            self._progress(sid, pages_processed=page, message=f"Searching Amazon… found {found} possible listings")
            log.info("Brand search %s: page %s processed, %s results, %s mention the brand", sid, page, len(result.results), matches)
            pages_without_brand = pages_without_brand + 1 if matches == 0 else 0
            if not result.has_next or not result.results or pages_without_brand >= 2:
                break
        if search.get("store_url"):
            self._progress(sid, message="Reading the brand store page…")
            for position, asin in enumerate(parse_store_page(self.source.fetch(search["store_url"], "store").html), start=1):
                existing = self.repo.item(sid, asin)
                if existing is None or existing["stage"] == "skipped_not_brand":
                    self.repo.upsert_item(sid, asin, page=0, position=position, relevance="brand_store", stage="discovered",
                                          outcome=None, reasons=None)
        self._progress(sid, discovery_complete=1)

    # ============================================================= process
    def _process(self, search: dict) -> None:
        sid = search["id"]
        settings = self.service.settings
        candidates = [i for i in self.repo.items(sid) if i["stage"] != "skipped_not_brand"]
        total = len(candidates)
        done = sum(1 for i in candidates if i["stage"] in DONE_STAGES)
        self._progress(sid, phase="collecting", progress_total=total, progress_done=done,
                       message=f"Checking {total} products for {search['query']}…")
        for item in candidates:
            if item["stage"] in DONE_STAGES:
                continue
            asin = item["asin"]
            self._progress(sid, phase="collecting", progress_done=done, message=f"Collecting product details… {done + 1}/{total}")
            existing = self.products.find_by_asin(asin)
            known = existing[0] if existing else None
            if known is not None:
                self.repo.upsert_item(sid, asin, was_known=1, product_id=known.id)

            rejection = self.repo.active_rejection(asin)
            if rejection and not search["reevaluate_rejected"]:
                self.repo.upsert_item(sid, asin, stage="skipped_rejected", outcome=SKIPPED_REJECTED,
                                      reasons=rejection["reasons"], product_id=rejection["product_id"] or (known.id if known else None))
                log.info("Brand search %s: %s previously rejected — skipped", sid, asin)
                done += 1
                continue

            if known is not None and not search["reevaluate_rejected"] and self._fresh(known, settings.research_refresh_hours):
                collected_brand = "brand" in (known.field_meta or {})  # brand came from an Amazon page, not typed by hand
                relevance, reason = brand_relevance(known.brand, "details" if collected_brand else None, known.title or "", search["query"])
                if reason:
                    self.repo.upsert_item(sid, asin, stage="skipped_not_brand", outcome=NOT_BRAND, relevance=relevance, reasons=[reason])
                else:
                    self.repo.upsert_item(sid, asin, relevance=relevance)
                    self._decide(sid, search, self.service.get(known.id), item)
                done += 1
                continue

            try:
                product = self._collect(sid, search, item, known)
            except (PageNotFound, FetchFailed) as exc:
                message = "The Amazon listing no longer exists." if isinstance(exc, PageNotFound) else str(exc)
                self.repo.upsert_item(sid, asin, stage="failed", outcome=COLLECTION_FAILED, error=message, reasons=[message])
                log.info("Brand search %s: collection failed for %s: %s", sid, asin, message)
                done += 1
                continue
            if product is None:  # not the brand after checking the product page
                done += 1
                continue
            self._progress(sid, phase="evaluating", message=f"Evaluating… {done + 1}/{total}")
            self._decide(sid, search, product, item)
            done += 1
        self._progress(sid, progress_done=done, phase="done")

    def _fresh(self, product: Product, hours: int) -> bool:
        if product.source != SOURCE_AMAZON or not product.amazon_checked_at:
            return False
        try:
            checked = datetime.fromisoformat(product.amazon_checked_at)
        except ValueError:
            return False
        return self._now() - checked < timedelta(hours=hours)

    # ============================================================= collect
    def _collect(self, sid: int, search: dict, item: dict, known: Product | None) -> Product | None:
        asin, brand = item["asin"], search["query"]
        page = self.source.fetch(self.marketplace.product_url(asin), "product")
        parsed = parse_product_page(page.html, asin)
        if not parsed.title:
            raise FetchFailed("The product page could not be read (unexpected layout).")

        # Brand relevance, now that the listing's own brand field is known.
        relevance, reason = brand_relevance(parsed.brand, parsed.brand_source, parsed.title, brand)
        if reason:
            self.repo.upsert_item(sid, asin, stage="skipped_not_brand", outcome=NOT_BRAND, relevance=relevance,
                                  reasons=[reason], title=parsed.title)
            log.info("Brand search %s: %s is brand %r — not analyzed", sid, asin, parsed.brand)
            return None
        self.repo.upsert_item(sid, asin, relevance=relevance, title=parsed.title)

        offers = None
        try:
            offers = parse_offers_page(self.source.fetch(self.marketplace.offers_url(asin), "offers").html)
        except (PageNotFound, FetchFailed) as exc:
            log.info("Brand search %s: offers unavailable for %s: %s", sid, asin, exc)

        at = now_iso()
        location_ok = getattr(self.source, "location_confirmed", None) is not False
        meta: dict[str, dict] = {}

        def put(name, value, source, kind="raw", certainty="verified", note=None):
            meta[name] = {"source": source, "at": at, "kind": kind, "certainty": certainty, **({"note": note} if note else {})}
            return value

        snap = item.get("search_snapshot") or {}
        values: dict = {
            "asin": asin,
            "title": put("title", parsed.title, "amazon_product_page"),
            "brand": put("brand", parsed.brand, "amazon_product_page", certainty="verified" if relevance == "brand_verified" else "uncertain",
                         note=None if relevance == "brand_verified" else "Brand field does not exactly match the searched brand."),
            "category": put("category", parsed.category, "amazon_product_page"),
            "bsr_category": put("bsr_category", parsed.bsr_category, "amazon_product_page"),
            "amazon_url": put("amazon_url", self.marketplace.product_url(asin), "amazon_product_page"),
            "selling_price": put("selling_price", parsed.price if location_ok else None, "amazon_product_page",
                                 certainty="verified" if location_ok else "uncertain", note=parsed.price_note
                                 or (None if location_ok else "UK delivery location not confirmed; price not used.")),
            "bsr": put("bsr", parsed.bsr, "amazon_product_page"),
            "availability": put("availability", parsed.availability, "amazon_product_page"),
        }
        if parsed.bought_lower_bound:
            bought, note = parsed.bought_lower_bound, f"Lower bound from Amazon's “{parsed.bought_text}” badge on the product page."
        elif snap.get("bought_lower_bound"):
            bought = snap["bought_lower_bound"]
            note = (f"Lower bound from Amazon's “{snap.get('bought_text')}” badge on the search result "
                    "(Amazon may include other sizes or variations of this listing).")
        else:
            bought = None
            note = "Amazon shows no “bought in past month” figure for this listing; no free source provides monthly sales."
        values["monthly_sales"] = put("monthly_sales", bought, "amazon_bought_badge", kind="estimated", certainty="uncertain", note=note)
        if offers is not None and (offers.pinned or offers.offers or offers.other_count is not None):
            uncertain = not offers.complete
            values["total_sellers"] = put("total_sellers", offers.total_sellers, "amazon_offers")
            values["fba_sellers"] = put("fba_sellers", offers.fba_sellers, "amazon_offers", certainty="uncertain" if uncertain else "verified",
                                        note="Counted from the first page of offers only." if uncertain else None)
            values["flag_amazon_sells"] = put("flag_amazon_sells", offers.amazon_sells, "amazon_offers")
        else:
            values["total_sellers"] = put("total_sellers", None, "amazon_offers", certainty="uncertain", note="Offers could not be read.")
            values["fba_sellers"] = put("fba_sellers", None, "amazon_offers", certainty="uncertain", note="Offers could not be read.")
            seller = parsed.buybox_seller or ""
            values["flag_amazon_sells"] = put("flag_amazon_sells", bool(AMAZON_SELLER.match(seller)), "amazon_product_page",
                                              certainty="uncertain")
        if parsed.weight_g:
            values["weight_g"] = put("weight_g", parsed.weight_g, "amazon_product_page",
                                     certainty="uncertain" if parsed.weight_note else "verified", note=parsed.weight_note)
        if parsed.dims_cm:
            note = None if parsed.dims_source == "package" else "Product (not package) dimensions — the packed size can be larger."
            for key, dim in zip(("length_cm", "width_cm", "height_cm"), sorted(parsed.dims_cm, reverse=True)):
                values[key] = put(key, dim, "amazon_product_page", certainty="verified" if not note else "uncertain", note=note)
        fee_key, mapped = fee_category_for(parsed.breadcrumbs, parsed.bsr_category)
        values["fee_category"] = put("fee_category", fee_key, "category_mapping", kind="estimated", certainty="uncertain",
                                     note=("Mapped from Amazon's category — confirm the referral fee category." if mapped
                                           else "Category not recognised — the 15% default is used; confirm in Seller Central."))

        supplier = self.repo.supplier_price(asin)
        if supplier:
            values["sourcing_price"] = put("sourcing_price", supplier["cost"], "supplier_price_list",
                                           note=f"Matched on {supplier['matched_on']} in {supplier.get('source_name') or 'your price list'}.")
            values["supplier"] = put("supplier", supplier.get("supplier"), "supplier_price_list")

        product = self._save(sid, known, values, meta)
        self.repo.upsert_item(sid, asin, stage="collected", product_id=product.id)
        self.conn.commit()
        return product

    def _save(self, sid: int, known: Product | None, values: dict, meta: dict) -> Product:
        if known is None:
            product = Product(fulfilment=FBA, restriction_status=RESTRICTION_UNKNOWN, source=SOURCE_AMAZON,
                              brand_key=brand_key(values.get("brand") or ""), field_meta=meta)
            for key, value in values.items():
                setattr(product, key, value)
            pid = self.service.create(product, source=SOURCE_AMAZON, commit=False)
        else:
            merged = Product.from_mapping({**known.__dict__})
            old_meta = dict(known.field_meta or {})
            for key, value in values.items():
                user_value = old_meta.get(key, {}).get("source") in USER_SOURCES or (
                    key not in AUTO_FIELDS and getattr(known, key) not in (None, "") and key not in old_meta)
                if user_value:
                    continue  # never overwrite something the user typed
                setattr(merged, key, value)
                old_meta[key] = meta[key]
            merged.field_meta = old_meta
            merged.brand_key = brand_key(merged.brand or "")
            merged.source = SOURCE_AMAZON
            self.service.update(known.id, merged, mark_checked=True, commit=False)
            pid = known.id
        self.conn.execute("UPDATE products SET first_discovered_at = COALESCE(first_discovered_at, ?), last_brand_search_id = ? "
                          "WHERE id = ?", (now_iso(), sid, pid))
        return self.service.get(pid)

    # ============================================================== decide
    def _decide(self, sid: int, search: dict, product: Product, item: dict) -> None:
        ev = product.evaluation
        status = ev["status"]
        if status == REJECTED:
            failed = [r for r in ev["rules"] if r["status"] == "fail"]
            settings = self.service.settings
            self.repo.record_rejection(product.asin, product_id=product.id, brand=product.brand or search["query"],
                                       title=product.title, amazon_url=product.amazon_url, reasons=ev["summary"],
                                       failed_rules=failed, criteria=settings.criteria(),
                                       criteria_fingerprint=settings.criteria_fingerprint(), engine_version=ENGINE_VERSION,
                                       search_id=sid)
        elif search["reevaluate_rejected"]:
            self.repo.clear_rejection(product.asin)
        self.repo.upsert_item(sid, product.asin, stage="evaluated", outcome=status, product_id=product.id,
                              reasons=ev["summary"], title=product.title)
        self.conn.commit()
        log.info("Brand search %s: %s evaluated as %s", sid, product.asin, status)
