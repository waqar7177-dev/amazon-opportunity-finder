"""The automated Brand → Winning Products pipeline, end to end against prepared pages."""
from datetime import datetime, timedelta

import pytest

from amazon_fixtures import CAPTCHA, M, FakeSource, brightnest_site, product_page
from opportunity_finder.constants import COLLECTION_FAILED, INCOMPLETE, NOT_BRAND, QUALIFIED, REJECTED, SKIPPED_REJECTED
from opportunity_finder.database.db import connect, init_db
from opportunity_finder.database.repositories import ProductRepository
from opportunity_finder.database.research_repository import ResearchRepository
from opportunity_finder.domain.product import Product
from opportunity_finder.providers.amazon.browser import FetchFailed
from opportunity_finder.providers.sourcing import ImportFileError, parse_price_list
from opportunity_finder.services.product_service import ProductService
from opportunity_finder.services.research_jobs import ResearchRunner


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "research.db"
    init_db(path)
    conn = connect(path)
    ResearchRepository(conn).replace_supplier_prices(
        [{"asin": "B0BRIGHT01", "cost": 6.00, "supplier": "Wholesale Ltd"}, {"asin": "B0BRIGHT02", "cost": 5.00}], "prices.csv")
    conn.commit()
    conn.close()
    return path


def runner_for(db, source):
    return ResearchRunner(db, lambda settings, marketplace: source, background=False)


def run(db, source, brand="Brightnest", **options):
    runner = runner_for(db, source)
    sid = runner.start(brand, **options) if not options.get("_resume") else options["_resume"]
    runner.run_pending()
    conn = connect(db)
    repo = ResearchRepository(conn)
    return sid, repo.get_search(sid), {i["asin"]: i for i in repo.items(sid)}, conn


def test_full_brand_search(db):
    source = FakeSource(brightnest_site())
    sid, search, items, conn = run(db, source)
    assert search["status"] == "completed" and search["pages_processed"] == 2

    assert items["B0BRIGHT01"]["outcome"] == QUALIFIED and items["B0BRIGHT01"]["relevance"] == "brand_verified"
    assert items["B0BRIGHT02"]["outcome"] == REJECTED
    assert "BSR 42,831 exceeds maximum 25,000" in items["B0BRIGHT02"]["reasons"]
    assert items["B0BRIGHT03"]["outcome"] == INCOMPLETE and items["B0BRIGHT03"]["sponsored"] == 1
    assert items["B0BRIGHT04"]["outcome"] == INCOMPLETE
    assert any("Sourcing price is required" in r for r in items["B0BRIGHT04"]["reasons"])
    assert items["B0OTHER001"]["outcome"] == NOT_BRAND and "LidCo" in items["B0OTHER001"]["reasons"][0]
    assert items["B0NOTBRND1"]["outcome"] == NOT_BRAND

    # Unrelated titles are never opened; the page-2 duplicate is one item.
    assert M.product_url("B0NOTBRND1") not in source.fetched("product")
    assert len(items) == 6 and len(source.fetched("search")) == 2

    products = {p.asin: p for p in ProductRepository(conn).all()}
    assert set(products) == {"B0BRIGHT01", "B0BRIGHT02", "B0BRIGHT03", "B0BRIGHT04"}
    winner = products["B0BRIGHT01"]
    assert winner.source == "amazon" and winner.sourcing_price == 6.00 and winner.supplier == "Wholesale Ltd"
    assert (winner.total_sellers, winner.fba_sellers, winner.flag_amazon_sells) == (6, 3, True)
    assert winner.monthly_sales == 1000 and winner.field_meta["monthly_sales"]["kind"] == "estimated"
    assert winner.field_meta["sourcing_price"]["source"] == "supplier_price_list"
    assert winner.fee_category == "kitchen" and winner.field_meta["fee_category"]["kind"] == "estimated"
    assert winner.restriction_status == "unknown"

    rejected = ResearchRepository(conn).active_rejection("B0BRIGHT02")
    assert rejected and rejected["failed_rules"][0]["key"] == "max_bsr" and rejected["failed_rules"][0]["value"] == 42831
    assert rejected["criteria"]["max_bsr"] == 25000
    counts = ResearchRepository(conn).outcome_counts(sid)
    assert counts[QUALIFIED] == 1 and counts[REJECTED] == 1 and counts[INCOMPLETE] == 2 and counts[NOT_BRAND] == 2
    conn.close()


def test_product_line_of_another_brand_is_not_the_brand(db):
    from amazon_fixtures import offers_page, search_page
    site = brightnest_site()
    site[M.search_url("Brightnest", 2)] = search_page([
        {"asin": "B0SUBLINE1", "title": "Glowco BRIGHTNEST 360 Moisture Absorber Refill", "price": 4.99},
        {"asin": "B0BRANDFLD", "title": "Brightnest Home Stand Mixer", "price": 89.00},
    ])
    site[M.product_url("B0SUBLINE1")] = product_page("B0SUBLINE1", "Glowco BRIGHTNEST 360 Moisture Absorber Refill",
                                                    brand_line="Visit the Glowco Store", price=4.99)
    site[M.product_url("B0BRANDFLD")] = product_page("B0BRANDFLD", "Brightnest Home Stand Mixer", brand_line="Brand: Nordic Brightnest",
                                                    price=89.00)
    site[M.offers_url("B0BRANDFLD")] = offers_page(("A", "Amazon"), [("B", "Amazon"), ("C", "C")])
    source = FakeSource(site)
    sid, _, items, conn = run(db, source)
    assert items["B0SUBLINE1"]["outcome"] == NOT_BRAND and "Glowco" in items["B0SUBLINE1"]["reasons"][0]
    assert M.offers_url("B0SUBLINE1") not in source.fetched("offers")
    assert items["B0BRANDFLD"]["relevance"] == "brand_verified" and items["B0BRANDFLD"]["outcome"] != NOT_BRAND
    conn.close()

    # A product stored earlier under another brand is not re-counted when reused on the next search.
    conn = connect(db)
    conn.execute("UPDATE products SET brand = 'Glowco', field_meta = json_set(COALESCE(field_meta, '{}'), '$.brand', json('{}')) "
                 "WHERE asin = 'B0BRIGHT01'")
    conn.commit()
    conn.close()
    _, _, items2, conn = run(db, FakeSource(site))
    assert items2["B0BRIGHT01"]["outcome"] == NOT_BRAND
    conn.close()


def test_missing_data_is_not_fabricated(db):
    source = FakeSource({**brightnest_site(), M.offers_url("B0BRIGHT03"): FetchFailed("offers timed out")})
    _, _, _, conn = run(db, source)
    bread_bin = ProductRepository(conn).find_by_asin("B0BRIGHT03")[0]
    assert bread_bin.selling_price is None and bread_bin.bsr is None and bread_bin.monthly_sales is None
    assert bread_bin.total_sellers is None and bread_bin.fba_sellers is None and bread_bin.sourcing_price is None
    missing = {m["field"] for m in ProductService(conn).get(bread_bin.id).evaluation["missing"]}
    assert {"selling_price", "bsr", "monthly_sales", "total_sellers", "fba_sellers", "sourcing_price"} <= missing
    assert bread_bin.field_meta["monthly_sales"]["note"].startswith("Amazon shows no")
    conn.close()


def test_second_search_skips_rejected_and_reuses_fresh_products(db):
    run(db, FakeSource(brightnest_site()))[3].close()
    source = FakeSource(brightnest_site())
    sid, search, items, conn = run(db, source)
    assert search["status"] == "completed"
    assert items["B0BRIGHT02"]["outcome"] == SKIPPED_REJECTED
    assert M.product_url("B0BRIGHT02") not in source.fetched("product")
    assert M.product_url("B0BRIGHT01") not in source.fetched("product")  # checked minutes ago -> reused
    assert items["B0BRIGHT01"]["outcome"] == QUALIFIED and items["B0BRIGHT01"]["was_known"] == 1
    assert len(ProductRepository(conn).all()) == 4  # no duplicate records
    counts = ResearchRepository(conn).outcome_counts(sid)
    assert counts[SKIPPED_REJECTED] == 1 and counts["previously_analyzed"] == 4
    conn.close()


def test_explicit_reevaluation_rechecks_rejected(db):
    run(db, FakeSource(brightnest_site()))[3].close()
    site = brightnest_site()
    site[M.product_url("B0BRIGHT02")] = product_page("B0BRIGHT02", "Brightnest Glass Meal Prep Boxes 5 Pack", price=19.99,
                                                    bsr="12,000 in Home & Kitchen", bought="50+")
    source = FakeSource(site)
    sid, _, items, conn = run(db, source, reevaluate_rejected=True)
    assert M.product_url("B0BRIGHT02") in source.fetched("product")
    assert items["B0BRIGHT02"]["outcome"] == QUALIFIED
    repo = ResearchRepository(conn)
    assert repo.active_rejection("B0BRIGHT02") is None
    assert repo.rejected(active_only=False)[0]["cleared_at"]
    conn.close()


def test_block_keeps_results_and_resume_continues(db):
    site = brightnest_site()
    site[M.product_url("B0BRIGHT03")] = CAPTCHA
    first = FakeSource(site)
    sid, search, items, conn = run(db, first)
    assert search["status"] == "blocked" and "temporarily blocked automated collection" in search["message"]
    assert items["B0BRIGHT01"]["outcome"] == QUALIFIED and items["B0BRIGHT02"]["outcome"] == REJECTED
    assert items["B0BRIGHT03"]["stage"] == "discovered" and items["B0BRIGHT04"]["stage"] == "discovered"
    assert ProductRepository(conn).find_by_asin("B0BRIGHT03") == []  # a CAPTCHA page never becomes product data
    conn.close()

    second = FakeSource(brightnest_site())
    runner = runner_for(db, second)
    assert runner.resume(sid)
    runner.run_pending()
    conn = connect(db)
    repo = ResearchRepository(conn)
    assert repo.get_search(sid)["status"] == "completed"
    assert second.fetched("search") == []  # discovery was already complete
    assert M.product_url("B0BRIGHT01") not in second.fetched("product")
    assert {i["asin"]: i["outcome"] for i in repo.items(sid)}["B0BRIGHT04"] == INCOMPLETE
    conn.close()


def test_malformed_product_page_is_a_collection_failure(db):
    site = brightnest_site()
    site[M.product_url("B0BRIGHT04")] = "<html><body>" + "unexpected layout " * 40 + "</body></html>"
    _, search, items, conn = run(db, FakeSource(site))
    assert search["status"] == "completed"
    assert items["B0BRIGHT04"]["outcome"] == COLLECTION_FAILED and "could not be read" in items["B0BRIGHT04"]["error"]
    assert ProductRepository(conn).find_by_asin("B0BRIGHT04") == []
    conn.close()


def test_unconfirmed_location_does_not_use_prices(db):
    _, _, _, conn = run(db, FakeSource(brightnest_site(), location_confirmed=False))
    winner = ProductRepository(conn).find_by_asin("B0BRIGHT01")[0]
    assert winner.selling_price is None and "not confirmed" in winner.field_meta["selling_price"]["note"]
    conn.close()


def test_user_entered_values_are_never_overwritten(db):
    conn = connect(db)
    ProductService(conn).create(Product(asin="B0BRIGHT01", title="My notes title", sourcing_price=7.50, supplier="My supplier",
                                        restriction_status="ungated", monthly_sales=400, notes="keep"))
    conn.close()
    _, _, items, conn = run(db, FakeSource(brightnest_site()))
    product = ProductRepository(conn).find_by_asin("B0BRIGHT01")
    assert len(product) == 1
    p = product[0]
    assert (p.sourcing_price, p.supplier, p.restriction_status, p.notes) == (7.50, "My supplier", "ungated", "keep")
    assert p.title == "Brightnest Stackable Food Storage Containers Set of 9"  # Amazon-owned field refreshed
    assert p.selling_price == 23.99 and items["B0BRIGHT01"]["was_known"] == 1
    conn.close()


def test_stale_known_product_is_recollected(db):
    run(db, FakeSource(brightnest_site()))[3].close()
    conn = connect(db)
    old = (datetime.now() - timedelta(hours=30)).replace(microsecond=0).isoformat()
    conn.execute("UPDATE products SET amazon_checked_at = ? WHERE asin = 'B0BRIGHT01'", (old,))
    conn.commit()
    conn.close()
    source = FakeSource(brightnest_site())
    run(db, source)[3].close()
    assert M.product_url("B0BRIGHT01") in source.fetched("product")


def test_cancel_and_interrupted_state(db):
    source = FakeSource(brightnest_site())
    runner = runner_for(db, source)
    sid = runner.start("Brightnest")
    runner._cancel.add(sid)
    runner.run_pending()
    conn = connect(db)
    repo = ResearchRepository(conn)
    assert repo.get_search(sid)["status"] == "cancelled"
    repo.update_search(sid, status="running")
    conn.commit()
    assert repo.mark_interrupted() == 1 and repo.get_search(sid)["status"] == "interrupted"
    conn.commit()
    conn.close()


def test_history_persists_after_restart(db):
    sid = run(db, FakeSource(brightnest_site()))[0]
    conn = connect(db)  # a fresh connection, as after an app restart
    repo = ResearchRepository(conn)
    history = repo.brand_history()
    assert history[0]["name"] == "Brightnest" and history[0]["last_search_id"] == sid and history[0]["last_analyzed_at"]
    assert repo.active_rejection("B0BRIGHT02") is not None
    assert repo.rejected_under_other_criteria(ProductService(conn).settings.criteria_fingerprint()) == 0
    conn.close()


def test_supplier_price_list_parsing():
    csv = ("ASIN,EAN,Unit Cost,Supplier,Description\n"
           "B0BRIGHT01,,6.00,Wholesale Ltd,Containers\n"
           ",5012345678900,£3.20,,Lunch box\n"
           "BADASIN,,1,,x\n"
           "B0BRIGHT01,,7.00,,duplicate\n"
           "B0BRIGHT02,,,,no cost\n").encode()
    rows, problems = parse_price_list("prices.csv", csv)
    assert [(r["asin"], r["ean"], r["cost"]) for r in rows] == [("B0BRIGHT01", None, 6.0), (None, "5012345678900", 3.2)]
    assert [n for n, _ in problems] == [4, 5, 6]
    with pytest.raises(ImportFileError, match="cost column"):
        parse_price_list("p.csv", b"ASIN,Name\nB0BRIGHT01,x\n")
