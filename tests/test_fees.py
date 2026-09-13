from datetime import date

import pytest

from opportunity_finder.constants import FBM
from opportunity_finder.fees.engine import (FeeInputs, FeeOptions, estimate_fees, estimate_referral_fee, in_peak_season,
                                            load_fee_table)

NON_PEAK = date(2026, 9, 13)
PEAK = date(2026, 11, 1)


def fees(on=NON_PEAK, options=None, **kw):
    return estimate_fees(FeeInputs(**kw), options or FeeOptions(), on)


# ----------------------------------------------------------- fee table sanity
def test_fee_table_is_well_formed():
    table = load_fee_table()
    keys = [c["key"] for c in table["referral_categories"]]
    assert len(keys) == len(set(keys))
    assert "everything_else" in keys
    for cat in table["referral_categories"]:
        assert cat["type"] in {"flat", "whole_price", "marginal"}
        if cat["type"] != "flat":
            assert cat["bands"][-1][0] is None, cat["key"]
    for key in table["low_price_fba"]["reduced_threshold_categories"] + table["selected_category_parcels"]["categories"]:
        assert key in keys, key


# --------------------------------------------------------------- referral fee
@pytest.mark.parametrize("price,category,expected", [
    (20.00, "everything_else", 3.00),
    (24.99, "everything_else", 3.75),        # 3.7485 rounds half-up to 3.75
    (1.00, "everything_else", 0.25),         # 15p raised to the 25p minimum
    (1.00, "books", 0.15),                   # books have no minimum
    (9.99, "beauty_health_personal_care", 0.80),
    (10.01, "beauty_health_personal_care", 1.50),
    (15.00, "clothing_accessories", 0.75),
    (18.00, "clothing_accessories", 1.80),
    (25.00, "clothing_accessories", 3.75),
    (200.00, "furniture", 28.75),            # 15% of 175 + 10% of 25
    (100.00, "consumer_electronics", 7.00),
    (12.00, "unknown_category_key", 1.80),   # unknown key falls back to 15%
])
def test_referral_fee(price, category, expected):
    fee, text = estimate_referral_fee(price, category)
    assert fee == pytest.approx(expected)
    assert text


def test_decimal_and_extremely_high_prices():
    assert estimate_referral_fee(0.99, "everything_else")[0] == 0.25
    assert estimate_referral_fee(99_999.99, "everything_else")[0] == pytest.approx(15_000.00)


# ----------------------------------------------------------------- FBA fees
def test_small_parcel_uses_dimensional_weight_and_full_breakdown():
    r = fees(selling_price=24.99, weight_g=400, length_cm=20, width_cm=15, height_cm=8)
    assert r.size_tier == "small_parcel"
    assert r.dimensional_weight_g == pytest.approx(480)
    assert r.shipping_weight_g == pytest.approx(480)
    assert r.referral_fee == 3.75
    assert r.fba_fee == 3.04
    assert r.fuel_surcharge == 0.05
    assert r.digital_services_fee == 0.14
    assert r.total_fees == 6.98
    assert r.confidence == "high"


def test_low_price_fba_applies_under_20_pounds():
    r = fees(selling_price=9.99, weight_g=50, length_cm=20, width_cm=15, height_cm=1)
    assert r.fba_program == "low_price"
    assert r.size_tier == "light_envelope"
    assert r.fba_fee == 1.52


def test_low_price_threshold_is_10_pounds_in_kitchen():
    r = fees(selling_price=15.00, fee_category="kitchen", weight_g=50, length_cm=20, width_cm=15, height_cm=1)
    assert r.fba_program == "standard"
    assert r.fba_fee == 1.89


def test_low_price_can_be_switched_off():
    r = fees(options=FeeOptions(apply_low_price_fba=False), selling_price=9.99, weight_g=50,
             length_cm=20, width_cm=15, height_cm=1)
    assert r.fba_program == "standard" and r.fba_fee == 1.89


def test_standard_envelope():
    r = fees(selling_price=25, weight_g=300, length_cm=30, width_cm=20, height_cm=2)
    assert (r.size_tier, r.fba_fee) == ("standard_envelope", 2.16)


def test_small_parcel_at_dimensional_weight_limit():
    r = fees(selling_price=25, weight_g=500, length_cm=35, width_cm=25, height_cm=12)
    assert r.size_tier == "small_parcel"
    assert r.shipping_weight_g == pytest.approx(2100)
    assert r.fba_fee == 3.27


def test_standard_parcel():
    r = fees(selling_price=40, weight_g=2000, length_cm=40, width_cm=30, height_cm=20)
    assert (r.size_tier, r.shipping_weight_g, r.fba_fee) == ("standard_parcel", 4800, 3.56)


def test_small_oversize_per_kg():
    r = fees(selling_price=60, weight_g=1500, length_cm=50, width_cm=40, height_cm=30)
    assert r.size_tier == "small_oversize"
    assert r.fba_fee == pytest.approx(3.49 + 12 * 0.25)


def test_special_oversize_by_length():
    r = fees(selling_price=120, weight_g=20_000, length_cm=180, width_cm=20, height_cm=20)
    assert (r.size_tier, r.fba_fee) == ("special_oversize", 16.22)


def test_selected_category_parcel_table():
    r = fees(selling_price=25, fee_category="clothing_accessories", weight_g=250, length_cm=30, width_cm=20, height_cm=8)
    assert r.fba_program == "selected_category"
    assert r.size_tier == "small_parcel_2"
    assert r.fba_fee == pytest.approx(2.87 + 2 * 0.02)


def test_weight_only_is_flagged_and_conservative():
    r = fees(selling_price=25, weight_g=800)
    assert r.tier_basis == "weight_only"
    assert r.confidence == "low"
    assert r.size_tier == "standard_parcel"
    assert r.fba_fee == 3.06
    assert any("Dimensions are missing" in w for w in r.warnings)


def test_missing_weight_means_no_fee_total():
    r = fees(selling_price=25)
    assert r.fba_fee is None
    assert r.total_fees is None
    assert "weight_g" in r.missing


def test_missing_price_means_no_referral_fee():
    r = fees(weight_g=400, length_cm=20, width_cm=15, height_cm=8)
    assert r.referral_fee is None and r.total_fees is None
    assert "selling_price" in r.missing


def test_fbm_has_no_fba_fee():
    r = fees(selling_price=20, fulfilment=FBM)
    assert r.fba_fee == 0 and r.fba_source == "not_applicable"
    assert r.total_fees == pytest.approx(3.00 + 0.06)


def test_fba_fee_override_skips_estimate_and_add_ons():
    r = fees(selling_price=20, fba_fee_override=3.10, dangerous_goods=True)
    assert r.fba_source == "override" and r.fba_fee == 3.10
    assert r.fuel_surcharge == 0 and r.dangerous_goods_fee == 0
    assert r.total_fees == pytest.approx(6.10 + 0.12)


def test_referral_override():
    r = fees(selling_price=20, referral_fee_override=1.11, fulfilment=FBM)
    assert r.referral_fee == 1.11 and r.referral_source == "override"


def test_peak_season_fee():
    r = fees(on=PEAK, selling_price=24.99, weight_g=400, length_cm=20, width_cm=15, height_cm=8)
    assert r.peak_applied and r.fba_fee == 3.15
    r_off = fees(on=PEAK, options=FeeOptions(apply_peak_fees=False), selling_price=24.99, weight_g=400,
                 length_cm=20, width_cm=15, height_cm=8)
    assert not r_off.peak_applied and r_off.fba_fee == 3.04


@pytest.mark.parametrize("day,expected", [
    (date(2026, 10, 14), False), (date(2026, 10, 15), True), (date(2026, 12, 31), True),
    (date(2027, 1, 14), True), (date(2027, 1, 15), False), (date(2026, 7, 1), False),
])
def test_peak_window(day, expected):
    assert in_peak_season(day, load_fee_table()) is expected


def test_fuel_surcharge_starts_17_april_2026():
    before = fees(on=date(2026, 4, 16), selling_price=24.99, weight_g=400, length_cm=20, width_cm=15, height_cm=8)
    after = fees(on=date(2026, 4, 17), selling_price=24.99, weight_g=400, length_cm=20, width_cm=15, height_cm=8)
    assert before.fuel_surcharge == 0 and after.fuel_surcharge == 0.05


def test_dangerous_goods_fee():
    r = fees(selling_price=24.99, weight_g=400, length_cm=20, width_cm=15, height_cm=8, dangerous_goods=True)
    assert r.dangerous_goods_fee == 0.10


def test_vat_on_fees_for_non_registered_sellers():
    r = fees(options=FeeOptions(vat_on_fees=True), selling_price=24.99, weight_g=400, length_cm=20, width_cm=15, height_cm=8)
    assert r.vat_on_fees == pytest.approx(round((6.84 + 0.14) * 0.2, 2))
    assert r.total_fees == pytest.approx(6.98 + r.vat_on_fees)


def test_digital_services_fee_can_be_switched_off():
    r = fees(options=FeeOptions(apply_digital_services_fee=False), selling_price=24.99, weight_g=400,
             length_cm=20, width_cm=15, height_cm=8)
    assert r.digital_services_fee == 0 and r.total_fees == 6.84
