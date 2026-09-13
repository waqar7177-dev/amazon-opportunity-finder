import pytest

from opportunity_finder.numbers import parse_bool, parse_number, parse_whole
from opportunity_finder.services.validation import validate_product

BASE = {"title": "Thing", "selling_price": "19.99"}


def v(**kw):
    return validate_product({**BASE, **kw})


@pytest.mark.parametrize("field,value,message", [
    ("selling_price", "-1", "cannot be negative"),
    ("selling_price", "0", "more than £0"),
    ("selling_price", "abc", "must be a number"),
    ("sourcing_price", "-0.01", "cannot be negative"),
    ("shipping_prep", "-2", "cannot be negative"),
    ("total_sellers", "3.5", "whole number"),
    ("fba_sellers", "-1", "cannot be negative"),
    ("bsr", "0", "positive"),
    ("bsr", "12.7", "whole number"),
    ("monthly_sales", "lots", "whole number"),
    ("asin", "B0SHORT", "10 letters and numbers"),
    ("amazon_url", "not a url", "full web address"),
    ("weight_g", "0", "more than 0"),
    ("fulfilment", "drone", "not recognised"),
    ("restriction_status", "maybe", "not recognised"),
    ("fee_category", "Spaceships", "referral fee category"),
    ("flag_hazmat", "perhaps", "yes/no"),
])
def test_field_errors(field, value, message):
    result = v(**{field: value})
    assert field in result.errors and message in result.errors[field]


def test_valid_values_are_normalised():
    r = v(selling_price="£1,299.99", sourcing_price="£8", bsr="12,345", total_sellers="5", fba_sellers="2",
          asin=" b0abcde123 ", amazon_url="www.amazon.co.uk/Some-Thing/dp/B0ABCDE123/ref=sr_1_1?keywords=x",
          fee_category="Home Products", fulfilment="fbm", restriction_status="Check Seller Central",
          flag_battery="on", length_cm="10", width_cm="5", height_cm="2")
    assert r.ok, r.errors
    p = r.product
    assert (p.selling_price, p.sourcing_price, p.bsr) == (1299.99, 8.0, 12345)
    assert p.asin == "B0ABCDE123"
    assert p.amazon_url == "https://www.amazon.co.uk/dp/B0ABCDE123"
    assert p.fee_category == "home_products" and p.fulfilment == "FBM" and p.restriction_status == "check"
    assert p.flag_battery is True and p.flag_hazmat is False


def test_zero_sourcing_price_is_allowed():
    assert v(sourcing_price="0").ok


def test_url_fills_missing_asin_and_detects_mismatch():
    assert v(amazon_url="https://www.amazon.co.uk/dp/B0ABCDE123").product.asin == "B0ABCDE123"
    r = v(asin="B0ZZZZZ999", amazon_url="https://www.amazon.co.uk/dp/B0ABCDE123")
    assert "amazon_url" in r.errors and "B0ABCDE123" in r.errors["amazon_url"]


def test_fba_sellers_cannot_exceed_total():
    r = v(total_sellers="2", fba_sellers="3")
    assert "can't be more than total sellers" in r.errors["fba_sellers"]


def test_needs_some_identity():
    r = validate_product({"selling_price": "9.99"})
    assert "title" in r.errors


def test_partial_dimensions_rejected():
    r = v(length_cm="10")
    assert "all three dimensions" in r.errors["length_cm"]


def test_warnings_do_not_block():
    r = v(asin="1234567890", selling_price="25000", amazon_url="https://www.amazon.com/dp/1234567890")
    assert r.ok
    assert "amazon_url" in r.warnings and "selling_price" in r.warnings


def test_text_length_limit():
    r = v(title="x" * 501)
    assert "under 500 characters" in r.errors["title"]


def test_import_style_row_booleans_and_kg():
    r = validate_product({"asin": "B0ABCDE123", "weight_kg": "0.45", "flag_ip_concern": "Y", "flag_liquid": "0"},
                         checkbox_form=False)
    assert r.ok and r.product.weight_g == 450 and r.product.flag_ip_concern and not r.product.flag_liquid


def test_number_parsers():
    assert parse_number("£ 12.50", "Price") == (12.5, None)
    assert parse_number("", "Price") == (None, None)
    assert parse_number("nan", "Price")[1]
    assert parse_whole("1,000", "Sales") == (1000, None)
    assert parse_whole(12.0, "Sales") == (12, None)
    assert parse_whole(True, "Sales")[1]
    assert parse_bool("✓") == (True, None) and parse_bool(None) == (False, None)
