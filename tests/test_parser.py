from opportunity_finder.parsers.amazon_text import parse_amazon_text


def test_full_product_page(fixture_text):
    r = parse_amazon_text(fixture_text("amazon_product_page.txt"))
    v = r.values()
    assert v["asin"] == "B0TESTAB12"
    assert r.fields["asin"].confidence == "high"
    assert v["title"].startswith("Brightnest Stackable Food Storage Containers Set of 9")
    assert v["brand"] == "Brightnest"
    assert v["selling_price"] == 23.99
    assert v["bsr"] == 3456
    assert v["category"] == "Home & Kitchen"
    assert v["monthly_sales"] == 1000
    assert v["weight_g"] == 1020
    assert (v["length_cm"], v["width_cm"], v["height_cm"]) == (24.5, 17, 13.5)
    assert v["flag_amazon_sells"] is True
    assert v["amazon_url"] == "https://www.amazon.co.uk/dp/B0TESTAB12"
    # Only the "New (6) from" count is present — FBA sellers must not be invented.
    assert v["total_sellers"] == 6 and r.fields["total_sellers"].confidence == "low"
    assert "fba_sellers" not in v


def test_several_prices_listed_with_warning(fixture_text):
    r = parse_amazon_text(fixture_text("amazon_product_page.txt"))
    values = [c.value for c in r.price_candidates]
    assert {23.99, 29.99, 2.67, 2.00, 21.50} <= set(values)
    assert values[0] == 23.99
    assert any("Several prices found" in w and "verify" in w for w in r.warnings)
    assert r.fields["selling_price"].confidence in {"medium", "low"}


def test_offers_panel_counts_sellers(fixture_text):
    r = parse_amazon_text(fixture_text("amazon_offers_panel.txt"))
    v = r.values()
    assert v["total_sellers"] == 4
    assert v["fba_sellers"] == 2  # KitchenDepot UK and BargainBarn; Amazon itself is not an FBA seller
    assert v["flag_amazon_sells"] is True
    assert v["asin"] == "B0TESTAB12"


def test_asin_formats():
    assert parse_amazon_text("ASIN: B0ABCDE123").values()["asin"] == "B0ABCDE123"
    assert parse_amazon_text("see https://www.amazon.co.uk/dp/B0ABCDE123?th=1").values()["asin"] == "B0ABCDE123"
    assert parse_amazon_text("code B0ABCDE123 here").values()["asin"] == "B0ABCDE123"
    assert parse_amazon_text("ASIN ‏ : ‎ 0141036133").values()["asin"] == "0141036133"


def test_conflicting_asins_warn():
    r = parse_amazon_text("ASIN: B0ABCDE123\nalso B0ZZZZZ999")
    assert r.values()["asin"] == "B0ABCDE123"
    assert any("Several ASIN" in w for w in r.warnings)


def test_price_formats():
    assert parse_amazon_text("Price: £1,299.99").values()["selling_price"] == 1299.99
    assert parse_amazon_text("Price:\n£\n12\n.\n99").values()["selling_price"] == 12.99
    assert parse_amazon_text("Deal Price: GBP 7.50").values()["selling_price"] == 7.50


def test_only_delivery_price_is_not_suggested():
    r = parse_amazon_text("FREE delivery on orders over £25 dispatched by Amazon")
    assert "selling_price" not in r.values()
    assert r.price_candidates and r.warnings


def test_non_uk_page_warns():
    r = parse_amazon_text("Price: $19.99 https://www.amazon.com/dp/B0ABCDE123")
    assert any("not amazon.co.uk" in w for w in r.warnings)
    assert any("No £ prices" in w for w in r.warnings)


def test_bsr_hash_format():
    r = parse_amazon_text("Best Sellers Rank: #12,345 in Toys & Games (See Top 100 in Toys & Games)")
    assert r.values()["bsr"] == 12345 and r.values()["category"] == "Toys & Games"


def test_brand_from_label_and_manufacturer_fallback():
    assert parse_amazon_text("Brand: Acme Tools").values()["brand"] == "Acme Tools"
    r = parse_amazon_text("Manufacturer ‏ : ‎ Acme Holdings Ltd")
    assert r.values()["brand"] == "Acme Holdings Ltd" and r.fields["brand"].confidence == "low"


def test_sold_by_and_fulfilled_by_amazon_line():
    r = parse_amazon_text("Sold by ToyShed and Fulfilled by Amazon.\nSold by Wonder Co and Fulfilled by Amazon.")
    assert r.values()["total_sellers"] == 2 and r.values()["fba_sellers"] == 2


def test_malformed_and_empty_text_fail_gracefully():
    for junk in ["", "   ", "lorem ipsum 12345 $$$ £", "£", "\x00\x01 ASIN: ", "Best Sellers Rank: in"]:
        r = parse_amazon_text(junk)
        assert r.warnings
    assert not parse_amazon_text("lorem ipsum dolor").found_any


def test_huge_text_does_not_crash():
    r = parse_amazon_text("Price: £9.99\n" + "noise line\n" * 60_000)
    assert r.values()["selling_price"] == 9.99
