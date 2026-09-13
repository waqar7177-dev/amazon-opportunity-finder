from amazon_fixtures import CAPTCHA, offers_page, product_page, search_page
from opportunity_finder.providers.amazon.categories import fee_category_for
from opportunity_finder.providers.amazon.marketplace import AMAZON_UK, get_marketplace
from opportunity_finder.providers.amazon.parsers import (bought_lower_bound, classify_page, gbp, parse_offers_page,
                                                         parse_product_page, parse_search_page, parse_store_page)
from opportunity_finder.services.brand_research import title_mentions_brand


def test_search_page():
    html = search_page([
        {"asin": "B0AAAAAAA1", "title": "Brightnest Box", "price": 12.5, "bought": "1K+"},
        {"asin": "B0AAAAAAA2", "title": "Other thing", "sponsored": True},
        {"asin": "B0AAAAAAA1", "title": "Brightnest Box"},  # repeated block on the same page
        {"asin": "not-an-asin", "title": "Broken"},
    ], next_page=2)
    page = parse_search_page(html, 1)
    assert [r.asin for r in page.results] == ["B0AAAAAAA1", "B0AAAAAAA2"]
    first, second = page.results
    assert (first.price, first.bought_lower_bound, first.sponsored, first.position) == (12.5, 1000, False, 1)
    assert second.price is None and second.sponsored and second.bought_lower_bound is None
    assert page.has_next and "results for" in page.total_text
    assert parse_search_page(search_page([]), 3).has_next is False


def test_product_page_complete():
    p = parse_product_page(product_page("B0BRIGHT01", "Brightnest Containers", brand_line="Visit the Brightnest Store",
                                        item_weight="900 Grams"))
    assert p.asin == "B0BRIGHT01" and p.title == "Brightnest Containers"
    assert (p.brand, p.brand_source) == ("Brightnest", "store")
    assert p.price == 23.99  # the price to pay, not the £2.67 unit price
    assert p.bsr == 3456 and p.bsr_category == "Home & Kitchen"
    assert p.breadcrumbs[:2] == ["Home & Kitchen", "Kitchen & Dining"]
    assert p.dims_cm == (24.5, 17.0, 13.5) and p.dims_source == "package"
    assert p.weight_g == 1020 and p.weight_note is None  # 1.02 kg vs 900 g is within 25%
    assert p.bought_lower_bound == 100 * 10 and p.availability == "In stock"
    assert p.buybox_seller == "HomeGoods UK"


def test_product_page_missing_values_are_none():
    p = parse_product_page(product_page("B0BRIGHT03", "Bread Bin", price=None, bsr=None, package=None, bought=None, no_featured=True))
    assert p.price is None and p.bsr is None and p.weight_g is None and p.dims_cm is None and p.bought_lower_bound is None
    assert p.no_featured_offer and "No Buy Box" in p.price_note


def test_carousel_badges_belong_to_other_products():
    only_carousel = parse_product_page(product_page("B0X", "T", bought=None, carousel_bought="10K+"))
    assert only_carousel.bought_lower_bound is None
    both = parse_product_page(product_page("B0X", "T", bought="50+", carousel_bought="10K+"))
    assert both.bought_lower_bound == 50


def test_conflicting_weights_use_heaviest_with_note():
    p = parse_product_page(product_page("B0X", "T", package="30 x 20 x 9 cm; 90 g", item_weight="1.56 Kilograms"))
    assert p.weight_g == 1560 and "heaviest" in p.weight_note


def test_other_currency_price_is_ignored():
    assert gbp("PKR 1,874.57") is None and gbp("£1,299.99") == 1299.99
    assert bought_lower_bound("2.5K+ bought in past month")[0] == 2500


def test_offers_counting():
    page = parse_offers_page(offers_page(("HomeGoods", "Amazon"), [("Kitchen", "Amazon"), ("ShopA", "ShopA"), ("Amazon", "Amazon")]))
    assert page.total_sellers == 4
    assert page.fba_sellers == 2  # Amazon's own offer is not an FBA seller
    assert page.amazon_sells and page.complete
    partial = parse_offers_page(offers_page(("A", "Amazon"), [("B", "Amazon")], total=9))
    assert not partial.complete and partial.total_sellers == 10 and partial.fba_sellers == 2
    none = parse_offers_page(offers_page(None, [], total=0))
    assert none.pinned is None and none.total_sellers == 0 and not none.amazon_sells


def test_classify_page():
    assert classify_page(CAPTCHA).kind == "captcha" and classify_page(CAPTCHA).blocked
    assert classify_page("<script>window.gokuProps = {}; awsWafCookieDomainList</script>" + "x" * 300, 202).kind == "challenge"
    assert classify_page("<html>Sorry! Something went wrong!" + "x" * 300, 503).kind == "throttled"
    assert classify_page("x" * 500, 404).kind == "not_found"
    assert classify_page("<html></html>").kind == "empty"
    assert classify_page(product_page("B0X", "T")).kind == "ok"


def test_store_page_asins():
    assert parse_store_page('<a href="/dp/B0AAAAAAA1">x</a><div data-asin="B0AAAAAAA2"></div><a href="/dp/B0AAAAAAA1">') == [
        "B0AAAAAAA1", "B0AAAAAAA2"]


def test_title_mentions_brand():
    assert title_mentions_brand("AERO Milkybar White Chocolate", "Aero")
    assert not title_mentions_brand("AeroGarden Harvest", "Aero")
    assert title_mentions_brand("LOREAL Paris Elvive Shampoo", "L'Oréal")
    assert title_mentions_brand("Dr. Oetker Baking Kit", "Dr Oetker")
    assert not title_mentions_brand("Lids compatible with Brightnest boxes", "Brightnest", at_start=True)
    assert not title_mentions_brand("", "Aero") and not title_mentions_brand("Aero", "")


def test_category_mapping():
    assert fee_category_for(["Grocery", "Food Cupboard"]) == ("grocery_gourmet", True)
    assert fee_category_for(["Home & Kitchen", "Kitchen & Dining"]) == ("kitchen", True)
    assert fee_category_for(["Home & Kitchen", "Bedding"]) == ("home_linen_rugs", True)
    assert fee_category_for(["Home & Kitchen", "Candles"]) == ("home_products", True)
    assert fee_category_for(["Mystery Category"]) == ("everything_else", False)
    assert fee_category_for([], None) == ("everything_else", False)


def test_marketplace_urls():
    assert AMAZON_UK.search_url("Dr Oetker", 2) == "https://www.amazon.co.uk/s?k=Dr+Oetker&page=2"
    assert AMAZON_UK.product_url("B0X") == "https://www.amazon.co.uk/dp/B0X"
    assert "offer-listing" not in AMAZON_UK.offers_url("B0X")
    assert get_marketplace("unknown").key == "amazon_uk"
    assert {c["name"] for c in AMAZON_UK.cookies()} == {"i18n-prefs", "lc-acbuk"}
