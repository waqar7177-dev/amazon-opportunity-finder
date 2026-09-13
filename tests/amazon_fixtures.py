"""Synthetic Amazon UK pages for tests.

They copy the DOM structure the parsers rely on (checked against real pages on 2026-09-13) but use a
fictional brand, so no real listing content is stored in the repository.
"""
from __future__ import annotations

from opportunity_finder.providers.amazon.browser import CollectionBlocked, FetchResult, PageNotFound
from opportunity_finder.providers.amazon.marketplace import AMAZON_UK
from opportunity_finder.providers.amazon.parsers import classify_page

PAD = "<!-- " + "padding " * 60 + "-->"  # real pages are large; tiny pages look like errors


def search_page(results: list[dict], next_page: int | None = None, total: str = "1-48 of 62 results for") -> str:
    blocks = []
    for i, r in enumerate(results, start=1):
        sponsored = '<span class="puis-sponsored-label-text">Sponsored</span>' if r.get("sponsored") else ""
        price = f'<span class="a-price"><span class="a-offscreen">£{r["price"]:.2f}</span></span>' if r.get("price") else ""
        rrp = '<span class="a-price a-text-price"><span class="a-offscreen">£99.99</span></span>'
        bought = f'<span class="a-size-base a-color-secondary">{r["bought"]} bought in past month</span>' if r.get("bought") else ""
        blocks.append(
            f'<div data-component-type="s-search-result" data-asin="{r["asin"]}" data-index="{i}" class="s-result-item">'
            f'{sponsored}<h2 aria-label="{r["title"]}" class="a-size-base-plus"><span>{r["title"]}</span></h2>'
            f'{price}{rrp}{bought}<a href="/x/dp/{r["asin"]}/ref=sr_1_{i}">link</a></div>')
    nxt = (f'<a class="s-pagination-item s-pagination-next" href="/s?k=x&page={next_page}">Next</a>' if next_page
           else '<span class="s-pagination-item s-pagination-next s-pagination-disabled">Next</span>')
    return f"<html><head><title>Amazon.co.uk</title></head><body><span>{total} \"x\"</span>{''.join(blocks)}{nxt}{PAD}</body></html>"


def product_page(asin: str, title: str, *, brand_line: str = "Brand: Brightnest", price: float | None = 23.99,
                 bsr: str | None = "3,456 in Home & Kitchen", crumbs=("Home & Kitchen", "Kitchen & Dining", "Storage"),
                 package: str | None = "24.5 x 17 x 13.5 cm; 1.02 kg", item_weight: str | None = None,
                 bought: str | None = "1K+", availability: str = "In stock", seller: str = "HomeGoods UK",
                 no_featured: bool = False) -> str:
    crumb_html = "".join(f'<li><span><a href="/b?node={i}">{c}</a></span></li>' for i, c in enumerate(crumbs))
    if price is not None:
        whole, fraction = f"{price:.2f}".split(".")
        price_html = (
            '<div id="corePriceDisplay_desktop_feature_div"><span class="a-price priceToPay">'
            f'<span class="a-offscreen"></span><span aria-hidden="true"><span class="a-price-symbol">£</span>'
            f'<span class="a-price-whole">{whole}<span class="a-price-decimal">.</span></span>'
            f'<span class="a-price-fraction">{fraction}</span></span></span>'
            '<span class="a-size-small pricePerUnit"><span class="a-price"><span class="a-offscreen">£2.67</span></span> / count</span>'
            "</div>")
    else:
        price_html = '<div id="corePriceDisplay_desktop_feature_div"></div>'
    featured = "<div>No featured offers available</div>" if no_featured else ""
    bullets = f'<li><span class="a-list-item"><span class="a-text-bold">ASIN ‏ : ‎</span><span>{asin}</span></span></li>'
    if package:
        bullets += f'<li><span class="a-list-item"><span class="a-text-bold">Package Dimensions ‏ : ‎</span><span>{package}</span></span></li>'
    rows = '<tr><th class="a-color-secondary">Brand Name</th><td>Brightnest</td></tr>' if "Brightnest" in brand_line else ""
    if bsr:
        rows += f'<tr><th>Best Sellers Rank</th><td><span>{bsr} (See Top 100 in Home &amp; Kitchen)</span> <span>12 in Food Storage</span></td></tr>'
    if item_weight:
        rows += f"<tr><th>Item Weight</th><td>{item_weight}</td></tr>"
    merchant = ('<div offer-display-feature-name="desktop-merchant-info"><div class="offer-display-feature-text">'
                f'<span class="a-size-small offer-display-feature-text-message">{seller}</span></div></div>')
    bought_html = f'<span id="social-proofing-faceout-title-tk_bought">{bought} bought in past month</span>' if bought else ""
    return (f"<html><body><div id='wayfinding-breadcrumbs_feature_div'><ul>{crumb_html}</ul></div>"
            f'<span id="productTitle"> {title} </span><a id="bylineInfo">{brand_line}</a>{bought_html}'
            f'{price_html}{featured}<div id="availability"><span>{availability}</span></div>{merchant}'
            f'<div id="detailBullets_feature_div"><ul>{bullets}</ul></div><table class="a-keyvalue">{rows}</table>{PAD}</body></html>')


def offers_page(pinned: tuple[str, str] | None, offers: list[tuple[str, str]], total: int | None = None) -> str:
    def block(tag, seller, ships):
        return (f'<div id="{tag}"><div id="aod-offer-price"><span class="a-price"><span class="a-offscreen">£23.49</span></span></div>'
                f'<div id="aod-offer-shipsFrom"><div class="a-col-left">Dispatches from</div><div class="a-col-right"><span class="a-size-small">{ships}</span></div></div>'
                f'<div id="aod-offer-soldBy"><div class="a-col-left">Sold by</div><div class="a-col-right"><a href="/seller">{seller}</a></div></div></div>')
    pinned_html = block("aod-pinned-offer", *pinned) if pinned else '<div id="aod-pinned-offer"><span>No featured offers available</span></div>'
    listing = "".join(block("aod-offer", s, sh) for s, sh in offers)
    count = len(offers) if total is None else total
    return (f'<html><body><div id="aod-container">{pinned_html}<input type="hidden" id="aod-total-offer-count" value="{count}">'
            f'<div id="aod-offer-list">{listing}</div></div>{PAD}</body></html>')


CAPTCHA = ("<html><body><h4>Enter the characters you see below</h4><form action='/errors/validateCaptcha'>"
           "<input name='field-keywords'></form>" + PAD + "</body></html>")


class FakeSource:
    """A PageSource that serves prepared pages and records every request."""

    def __init__(self, pages: dict, location_confirmed: bool | None = True):
        self.pages = dict(pages)
        self.requests: list[tuple[str, str]] = []
        self.location_confirmed = location_confirmed
        self.closed = False

    def fetch(self, url: str, kind: str) -> FetchResult:
        self.requests.append((kind, url))
        page = self.pages.get(url)
        if page is None:
            raise PageNotFound(url)
        if isinstance(page, Exception):
            raise page
        check = classify_page(page, 200)
        if check.blocked:
            raise CollectionBlocked(check.kind, check.message)
        return FetchResult(url, page, 200)

    def close(self) -> None:
        self.closed = True

    def fetched(self, kind: str) -> list[str]:
        return [u for k, u in self.requests if k == kind]


M = AMAZON_UK
FBA = "Amazon"


def brightnest_site() -> dict:
    """A small brand: 2 search pages, one qualifying product, one rejected, one incomplete, one without a
    supplier cost, one lookalike from another brand, and one unrelated result."""
    page1 = search_page([
        {"asin": "B0BRIGHT01", "title": "Brightnest Stackable Food Storage Containers Set of 9", "price": 23.99, "bought": "1K+"},
        {"asin": "B0BRIGHT02", "title": "Brightnest Glass Meal Prep Boxes 5 Pack", "price": 19.99, "bought": "50+"},
        {"asin": "B0BRIGHT03", "title": "BRIGHTNEST Bamboo Bread Bin", "sponsored": True},
        {"asin": "B0OTHER001", "title": "Replacement Lids compatible with Brightnest containers", "price": 7.99},
        {"asin": "B0NOTBRND1", "title": "Generic Digital Kitchen Scale", "price": 9.99},
    ], next_page=2)
    page2 = search_page([
        {"asin": "B0BRIGHT02", "title": "Brightnest Glass Meal Prep Boxes 5 Pack", "price": 19.99},
        {"asin": "B0BRIGHT04", "title": "Brightnest Kids Lunch Box", "price": 12.49, "bought": "100+"},
    ])
    return {
        M.search_url("Brightnest", 1): page1,
        M.search_url("Brightnest", 2): page2,
        M.product_url("B0BRIGHT01"): product_page("B0BRIGHT01", "Brightnest Stackable Food Storage Containers Set of 9",
                                                  brand_line="Visit the Brightnest Store"),
        M.offers_url("B0BRIGHT01"): offers_page(("HomeGoods UK", FBA), [("KitchenDepot", FBA), ("BargainBarn", FBA), ("ShopA", "ShopA"),
                                                                        ("ShopB", "ShopB"), ("Amazon", FBA)]),
        M.product_url("B0BRIGHT02"): product_page("B0BRIGHT02", "Brightnest Glass Meal Prep Boxes 5 Pack", price=19.99,
                                                  bsr="42,831 in Home & Kitchen", bought="50+"),
        M.offers_url("B0BRIGHT02"): offers_page(("SellerOne", FBA), [("SellerTwo", FBA), ("SellerThree", "SellerThree"), ("SellerFour", FBA)]),
        M.product_url("B0BRIGHT03"): product_page("B0BRIGHT03", "BRIGHTNEST Bamboo Bread Bin", price=None, bsr=None, bought=None,
                                                  no_featured=True, availability="Currently unavailable."),
        M.product_url("B0BRIGHT04"): product_page("B0BRIGHT04", "Brightnest Kids Lunch Box", price=12.49, bsr="8,900 in Home & Kitchen",
                                                  package="20 x 15 x 7 cm; 300 g", bought="100+"),
        M.offers_url("B0BRIGHT04"): offers_page(("LunchCo", FBA), [("TinyShop", "TinyShop"), ("MegaStore", "MegaStore")]),
        M.product_url("B0OTHER001"): product_page("B0OTHER001", "Replacement Lids compatible with Brightnest containers",
                                                  brand_line="Brand: LidCo", price=7.99),
    }
