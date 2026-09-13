"""Profit, ROI, capture model, qualification, status, risk, score, ranking and target plan."""
from datetime import datetime

import pytest

from conftest import TODAY, good_product
from opportunity_finder.constants import (HIGH_RISK, INCOMPLETE, NEEDS_VERIFICATION, QUALIFIED, REJECTED, RISK_HIGH,
                                          RISK_LOW, RISK_MEDIUM)
from opportunity_finder.domain.settings import VAT_REGISTERED, Settings
from opportunity_finder.services.calculator import capture_rate
from opportunity_finder.services.evaluator import evaluate
from opportunity_finder.services.ranking import rank
from opportunity_finder.services.target_plan import build_target_plan


def ev(product=None, settings=None, **overrides):
    return evaluate(product or good_product(**overrides), settings or Settings(), TODAY)


# ---------------------------------------------------------------- profit / ROI
def test_profit_roi_and_monthly_figures():
    e = ev()
    p = e["profit"]
    assert e["fees"]["total_fees"] == 6.98
    assert p["net_profit"] == 9.51
    assert p["roi_pct"] == pytest.approx(118.88, abs=0.01)
    assert p["margin_pct"] == pytest.approx(38.06, abs=0.01)
    assert p["theoretical_monthly_revenue"] == pytest.approx(7497.00)
    assert p["theoretical_monthly_profit"] == pytest.approx(2853.00)
    assert p["capture_rate_pct"] == 20
    assert p["conservative_units"] == 60
    assert p["conservative_monthly_profit"] == pytest.approx(570.60)
    assert p["monthly_stock_investment"] == pytest.approx(60 * 8.50)
    assert e["status"] == QUALIFIED


def test_decimal_prices_round_to_pence():
    e = ev(selling_price=19.995, sourcing_price=7.333)
    assert e["profit"]["net_profit"] == round(e["profit"]["net_profit"], 2)


def test_max_sourcing_price_respects_rules():
    assert ev()["profit"]["max_sourcing_price"] == 17.50
    s = Settings(min_roi=50)
    assert ev(settings=s)["profit"]["max_sourcing_price"] == 11.67


def test_vat_registered_deducts_output_vat():
    e = ev(settings=Settings(vat_mode=VAT_REGISTERED))
    assert e["profit"]["output_vat"] == 4.17
    assert e["profit"]["net_profit"] == pytest.approx(9.51 - 4.17)


def test_zero_sourcing_price_needs_verification():
    e = ev(sourcing_price=0)
    assert e["profit"]["roi_pct"] is None
    assert e["profit"]["net_profit"] == pytest.approx(17.51)
    roi_rule = next(r for r in e["rules"] if r["key"] == "min_roi")
    assert roi_rule["status"] == "not_applicable"
    assert e["status"] == NEEDS_VERIFICATION


def test_missing_amazon_price_is_not_guessed():
    e = ev(selling_price=None)
    assert e["profit"]["net_profit"] is None
    assert e["status"] == INCOMPLETE
    messages = [m["message"] for m in e["missing"]]
    assert "Amazon selling price is required before profitability can be calculated." in messages


def test_missing_bsr_is_incomplete_not_guessed():
    e = ev(bsr=None)
    assert e["status"] == INCOMPLETE
    assert any(m["field"] == "bsr" for m in e["missing"])
    assert next(r for r in e["rules"] if r["key"] == "max_bsr")["status"] == "missing"


def test_missing_supplier_does_not_block():
    e = ev(supplier=None)
    assert e["status"] == QUALIFIED
    assert "Supplier" in e["completeness"]["missing_optional"]


def test_missing_shipping_counts_as_zero_with_note():
    e = ev(shipping_prep=None)
    assert e["profit"]["net_profit"] == pytest.approx(10.01)
    assert any("Shipping / prep not entered" in n for n in e["profit"]["notes"])


# --------------------------------------------------------------- capture model
@pytest.mark.parametrize("fba,amazon,expected", [
    (0, False, 20), (4, False, 20), (5, False, 10), (9, False, 10), (10, False, 5), (40, False, 5), (3, True, 10),
])
def test_capture_rate_tiers(fba, amazon, expected):
    assert capture_rate(fba, amazon, Settings()).rate_pct == expected


def test_capture_rate_uses_settings():
    s = Settings(capture_rate_low=30, capture_rate_medium=15, capture_rate_high=2, competition_medium_from=3,
                 competition_high_from=6, amazon_sells_capture_pct=100)
    assert capture_rate(2, True, s).rate_pct == 30
    assert capture_rate(4, False, s).rate_pct == 15
    assert capture_rate(6, False, s).rate_pct == 2


def test_conservative_units_round_down():
    e = ev(monthly_sales=55, fba_sellers=10, total_sellers=12)
    assert e["profit"]["conservative_units"] == 2  # 55 x 5% = 2.75


def test_high_fba_competition_reduces_units_and_adds_risk():
    e = ev(fba_sellers=12, total_sellers=15)
    assert e["profit"]["capture_rate_pct"] == 5
    assert any(r["key"] == "high_fba_competition" for r in e["risk"]["reasons"])


# --------------------------------------------------------------- qualification
def test_rejection_reasons_match_the_brief():
    e = ev(bsr=42_831, monthly_sales=34)
    assert e["status"] == REJECTED
    assert "BSR 42,831 exceeds maximum 25,000" in e["summary"]
    assert "Monthly sales 34 below minimum 50" in e["summary"]


def test_bsr_equal_to_maximum_fails():
    e = ev(bsr=25_000)
    assert e["status"] == REJECTED


def test_very_large_bsr_rejected():
    assert ev(bsr=9_500_000)["status"] == REJECTED


def test_definite_failure_beats_missing_data():
    e = ev(bsr=None, monthly_sales=10)
    assert e["status"] == REJECTED
    assert any(m["field"] == "bsr" for m in e["missing"])


def test_no_sellers_rejected():
    e = ev(total_sellers=0, fba_sellers=0)
    assert e["status"] == REJECTED
    assert "Total sellers 0 below minimum 3" in e["summary"]


def test_zero_profit_fails_strict_minimum():
    e = ev(sourcing_price=17.51)
    assert e["profit"]["net_profit"] == 0
    assert e["status"] == REJECTED


def test_low_profit_but_high_sales_is_rejected_when_losing_money():
    e = ev(sourcing_price=18.00, monthly_sales=5000)
    assert e["profit"]["net_profit"] < 0
    assert e["status"] == REJECTED


def test_settings_change_qualification():
    assert ev(bsr=42_831)["status"] == REJECTED
    assert ev(bsr=42_831, settings=Settings(max_bsr=50_000))["status"] == QUALIFIED
    assert ev(settings=Settings(min_roi=150))["status"] == REJECTED


def test_stale_amazon_data_needs_verification():
    e = ev(amazon_checked_at=datetime(2026, 7, 1).isoformat())
    assert e["status"] == NEEDS_VERIFICATION
    assert any("last checked" in v for v in e["verification"])


def test_restriction_check_setting():
    assert ev(restriction_status="unknown")["status"] == QUALIFIED
    e = ev(restriction_status="unknown", settings=Settings(require_restriction_check=True))
    assert e["status"] == NEEDS_VERIFICATION


# ---------------------------------------------------------------------- risk
def test_clean_product_low_risk():
    e = ev()
    assert e["risk"]["level"] == RISK_LOW and e["risk"]["score"] == 0


def test_unknown_restriction_adds_points_but_stays_low():
    e = ev(restriction_status="unknown")
    assert e["risk"]["level"] == RISK_LOW and e["risk"]["score"] == 10


def test_high_risk_example_from_brief():
    # ROI 9.4%: sourcing s with (17.51 - s) / s = 0.094 -> s = 16.01
    e = ev(flag_ip_concern=True, flag_amazon_sells=True, sourcing_price=16.01)
    risk = e["risk"]
    assert risk["level"] == RISK_HIGH and risk["forced"]
    labels = [r["label"] for r in risk["reasons"]]
    assert "Possible IP / trademark concern" in labels
    assert "Amazon sells this listing" in labels
    assert any(r["detail"].startswith("ROI only 9.4%") for r in risk["reasons"])


def test_high_profit_but_high_risk_is_not_qualified():
    e = ev(flag_hazmat=True, flag_battery=True)
    assert e["profit"]["net_profit"] > 5
    assert e["risk"]["score"] == 40 and e["risk"]["level"] == RISK_HIGH
    assert e["status"] == HIGH_RISK


def test_restricted_forces_high():
    e = ev(restriction_status="restricted")
    assert e["risk"]["level"] == RISK_HIGH and e["status"] == HIGH_RISK


def test_amazon_selling_is_medium_risk():
    e = ev(flag_amazon_sells=True, restriction_status="unknown")
    assert e["risk"]["level"] == RISK_MEDIUM
    assert e["status"] == QUALIFIED
    assert e["profit"]["capture_rate_pct"] == 10


def test_missing_data_is_a_risk_reason():
    e = ev(monthly_sales=None)
    assert any(r["key"] == "missing_data" for r in e["risk"]["reasons"])


def test_thin_margin_and_low_roi():
    e = ev(sourcing_price=16.50)  # profit 1.01, ROI 6.1%, margin 4%
    keys = {r["key"] for r in e["risk"]["reasons"]}
    assert {"low_roi", "thin_margin"} <= keys


# --------------------------------------------------------------------- score
def test_score_is_transparent():
    score = ev()["score"]
    assert score["total"] == 91
    by_key = {c["key"]: c for c in score["components"]}
    assert by_key["roi"]["points"] == 25
    assert by_key["profit"]["points"] == pytest.approx(19.0)
    assert by_key["competition"]["points"] == 8
    assert sum(c["max"] for c in score["components"]) == 100
    assert all(c["rule"] for c in score["components"])


def test_score_none_without_profit():
    assert ev(sourcing_price=None)["score"] is None


def _item(product, settings=None):
    return {"product": product, "evaluation": evaluate(product, settings or Settings(), TODAY)}


def test_ranking_uses_more_than_roi():
    high_roi_low_sales = good_product(id=1, title="A", selling_price=12.00, sourcing_price=1.20, monthly_sales=50,
                                      weight_g=100, length_cm=20, width_cm=15, height_cm=2)
    balanced = good_product(id=2, title="B", monthly_sales=600)
    ranked = rank([_item(high_roi_low_sales), _item(balanced)])
    assert ranked[0]["evaluation"]["profit"]["roi_pct"] < ranked[1]["evaluation"]["profit"]["roi_pct"]
    assert [i["product"].title for i in ranked] == ["B", "A"]
    assert [i["rank"] for i in ranked] == [1, 2]


def test_ranking_only_includes_qualified():
    items = [_item(good_product(id=1)), _item(good_product(id=2, bsr=99_999)), _item(good_product(id=3, flag_ip_concern=True))]
    assert [i["product"].id for i in rank(items)] == [1]


# --------------------------------------------------------------- target plan
def _fake(pid, monthly, score, status=QUALIFIED):
    product = good_product(id=pid, title=f"Product {pid}")
    evaluation = {
        "status": status,
        "score": {"total": score, "components": []},
        "profit": {"roi_pct": 50.0, "net_profit": 5.0, "conservative_monthly_profit": monthly,
                   "conservative_units": 10, "monthly_stock_investment": 100.0},
    }
    return {"product": product, "evaluation": evaluation}


def test_target_plan_reaches_target():
    items = [_fake(1, 320, 90), _fake(2, 280, 80), _fake(3, 240, 70), _fake(4, 210, 60), _fake(5, 150, 50)]
    plan = build_target_plan(items, Settings(monthly_profit_target=1000))
    assert [s["product_id"] for s in plan["selected"]] == [1, 2, 3, 4]
    assert plan["total"] == 1050
    assert plan["achieved"] is True
    assert plan["selected"][-1]["running_total"] == 1050
    assert plan["stock_investment"] == 400


def test_target_plan_shortfall():
    plan = build_target_plan([_fake(1, 320, 90), _fake(2, 280, 80)], Settings(monthly_profit_target=1000))
    assert not plan["achieved"] and plan["shortfall"] == 400 and plan["progress_pct"] == 60


def test_target_plan_excludes_risky_and_unverified_by_default():
    items = [_fake(1, 900, 99, HIGH_RISK), _fake(2, 500, 90, NEEDS_VERIFICATION), _fake(3, 100, 50)]
    plan = build_target_plan(items, Settings())
    assert [s["product_id"] for s in plan["selected"]] == [3]
    plan2 = build_target_plan(items, Settings(include_needs_verification_in_plan=True))
    assert [s["product_id"] for s in plan2["selected"]] == [2, 3]


def test_target_plan_skips_zero_profit_and_custom_target():
    plan = build_target_plan([_fake(1, 0, 90), _fake(2, 60, 80)], Settings(monthly_profit_target=50))
    assert [s["product_id"] for s in plan["selected"]] == [2]
    assert plan["achieved"] and plan["skipped_no_profit"] == 1


def test_empty_target_plan():
    plan = build_target_plan([], Settings())
    assert plan["selected"] == [] and plan["total"] == 0 and not plan["achieved"]
