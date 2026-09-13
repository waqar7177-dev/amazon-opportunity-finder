"""Brand research: start, progress, report, export, history, supplier prices, skip list."""
from __future__ import annotations

import io
import re

from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, send_file, url_for

from ..app_factory import get_conn, get_runner, get_service
from ..constants import (COLLECTION_FAILED, HIGH_RISK, INCOMPLETE, NEEDS_VERIFICATION, NOT_BRAND, OUTCOME_LABELS,
                         OUTCOME_STYLE, QUALIFIED, REJECTED, SEARCH_STATUS_LABELS, SEARCH_STATUS_TONE, SKIPPED_REJECTED,
                         SOURCE_AMAZON)
from ..database.research_repository import ResearchRepository, now_iso
from ..numbers import money
from ..providers.sourcing import ImportFileError, parse_price_list
from ..services.brand_export import build_brand_workbook
from ..services.product_service import ProductNotFound
from ..services.qualification import describe_rules
from ..services.ranking import rank

bp = Blueprint("research", __name__)

EVALUATED = (QUALIFIED, REJECTED, INCOMPLETE, NEEDS_VERIFICATION, HIGH_RISK)


def _repo() -> ResearchRepository:
    return ResearchRepository(get_conn())


def _search_or_404(search_id: int) -> dict:
    search = _repo().get_search(search_id)
    if search is None:
        abort(404)
    return search


def progress_payload(search: dict, counts: dict) -> dict:
    total = search["progress_total"] or 0
    done = min(search["progress_done"] or 0, total) if total else 0
    return {
        "id": search["id"], "brand": search["query"], "status": search["status"],
        "status_label": SEARCH_STATUS_LABELS.get(search["status"], search["status"]),
        "phase": search["phase"], "message": search["message"] or "", "done": done, "total": total,
        "percent": round(done / total * 100) if total else (100 if search["status"] == "completed" else 0),
        "pages": search["pages_processed"] or 0, "finished": search["status"] not in ("queued", "running"),
        "counts": {k: counts.get(k, 0) for k in ("discovered", QUALIFIED, REJECTED, INCOMPLETE, SKIPPED_REJECTED,
                                                  COLLECTION_FAILED, NOT_BRAND)},
    }


def build_report(search: dict) -> dict:
    repo = _repo()
    service = get_service()
    items = repo.items(search["id"])
    counts = repo.outcome_counts(search["id"])
    groups: dict[str, list] = {k: [] for k in EVALUATED}
    for item in items:
        if item["outcome"] in EVALUATED and item["product_id"]:
            try:
                product = service.get(item["product_id"])
            except ProductNotFound:
                continue
            status = product.evaluation["status"]  # current evaluation (settings may have changed since)
            groups[status].append({"product": product, "evaluation": product.evaluation, "item": item})
    needs_cost = [i for i in groups[INCOMPLETE] if any(m["field"] == "sourcing_price" for m in i["evaluation"]["missing"])]
    other_missing = [i for i in groups[INCOMPLETE] if i not in needs_cost]
    winners = rank([dict(i) for i in groups[QUALIFIED]])
    return {
        "items": items,
        "counts": counts,
        "winners": winners,
        "rejected": groups[REJECTED],
        "incomplete": groups[INCOMPLETE],
        "needs_cost": needs_cost,
        "other_missing": other_missing,
        "review": groups[HIGH_RISK] + groups[NEEDS_VERIFICATION],
        "skipped": [i for i in items if i["outcome"] == SKIPPED_REJECTED],
        "failures": [i for i in items if i["outcome"] == COLLECTION_FAILED],
        "not_brand": [i for i in items if i["outcome"] == NOT_BRAND],
        "new_analyzed": sum(1 for i in items if i["outcome"] in EVALUATED and not i["was_known"]),
        "winners_conservative_profit": money(sum(w["evaluation"]["profit"]["conservative_monthly_profit"] or 0 for w in winners)),
        "rules": describe_rules(service.settings),
    }


# ------------------------------------------------------------------ start
@bp.post("/research/start")
def start():
    brand = re.sub(r"\s+", " ", request.form.get("brand", "")).strip()
    store_url = request.form.get("store_url", "").strip() or None
    back = request.form.get("next") or url_for("dashboard.index")
    if not brand:
        flash("Enter a brand name to analyze.", "warn")
        return redirect(back if back.startswith("/") else url_for("dashboard.index"))
    if len(brand) > 80:
        flash("Keep the brand name under 80 characters.", "warn")
        return redirect(url_for("dashboard.index"))
    if store_url and not re.match(r"^https://www\.amazon\.co\.uk/stores/", store_url):
        flash("The store link must be an Amazon UK brand store address (https://www.amazon.co.uk/stores/…). "
              "You can also leave it empty.", "warn")
        return redirect(url_for("dashboard.index"))
    runner = get_runner()
    search_id = runner.start(brand, store_url=store_url, reevaluate_rejected=bool(request.form.get("reevaluate_rejected")))
    if current_app.config.get("RESEARCH_SYNC"):
        runner.run_pending()
    return redirect(url_for(".search", search_id=search_id))


@bp.post("/research/<int:search_id>/resume")
def resume(search_id: int):
    _search_or_404(search_id)
    runner = get_runner()
    if runner.resume(search_id):
        if current_app.config.get("RESEARCH_SYNC"):
            runner.run_pending()
        flash("Resuming — products already analyzed are not collected again.", "ok")
    else:
        flash("This search is already running or complete.", "info")
    return redirect(url_for(".search", search_id=search_id))


@bp.post("/research/<int:search_id>/cancel")
def cancel(search_id: int):
    _search_or_404(search_id)
    get_runner().cancel(search_id)
    flash("Stopping after the current product. Everything collected so far is kept.", "info")
    return redirect(url_for(".search", search_id=search_id))


# ----------------------------------------------------------------- report
@bp.get("/research/<int:search_id>")
def search(search_id: int):
    g.active_nav = "brands"
    s = _search_or_404(search_id)
    report = build_report(s)
    return render_template("research/search.html", search=s, report=report, progress=progress_payload(s, report["counts"]),
                           outcome_labels=OUTCOME_LABELS, outcome_style=OUTCOME_STYLE, status_labels=SEARCH_STATUS_LABELS,
                           status_tone=SEARCH_STATUS_TONE, supplier=_repo().supplier_price_summary())


@bp.get("/api/research/<int:search_id>")
def progress(search_id: int):
    s = _search_or_404(search_id)
    return jsonify(progress_payload(s, _repo().outcome_counts(search_id)))


@bp.get("/research/<int:search_id>/export.xlsx")
def export(search_id: int):
    s = _search_or_404(search_id)
    data = build_brand_workbook(s, build_report(s))
    name = re.sub(r"[^A-Za-z0-9]+", "-", s["query"]).strip("-").lower() or "brand"
    current_app.logger.info("Brand export generated for search %s", search_id)
    return send_file(io.BytesIO(data), as_attachment=True, download_name=f"brand-report-{name}-{now_iso()[:10]}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------------------------------------------------------- history
@bp.get("/brands")
def brands():
    g.active_nav = "brands"
    repo = _repo()
    rows = []
    for brand in repo.brand_history():
        last = repo.get_search(brand["last_search_id"]) if brand["last_search_id"] else None
        rows.append({"brand": brand, "last": last, "counts": repo.outcome_counts(last["id"]) if last else {}})
    return render_template("research/brands.html", rows=rows, status_labels=SEARCH_STATUS_LABELS, status_tone=SEARCH_STATUS_TONE)


@bp.post("/research/rejected/<asin>/allow")
def allow_recheck(asin: str):
    _repo().clear_rejection(asin)
    get_conn().commit()
    flash(f"{asin.upper()} will be checked again the next time its brand is analyzed.", "ok")
    return redirect(url_for("opportunities.rejected", tab="history"))


# -------------------------------------------------------- supplier prices
@bp.route("/supplier-prices", methods=["GET", "POST"])
def supplier_prices():
    g.active_nav = "brands"
    repo = _repo()
    problems: list = []
    if request.method == "POST":
        upload = request.files.get("file")
        if not upload or not upload.filename:
            flash("Choose a CSV or Excel price list.", "warn")
        else:
            try:
                rows, problems = parse_price_list(upload.filename, upload.read())
            except ImportFileError as exc:
                flash(str(exc), "bad")
                rows = None
            if rows is not None:
                if not rows:
                    flash("No usable prices were found in that file — nothing was changed.", "bad")
                else:
                    repo.replace_supplier_prices(rows, upload.filename)
                    get_conn().commit()
                    updated = apply_supplier_prices()
                    flash(f"Price list saved: {len(rows)} prices. {updated} researched product(s) re-evaluated with the new costs.", "ok")
                    if not problems:
                        return redirect(url_for(".supplier_prices"))
    prices = [dict(r) for r in get_conn().execute("SELECT * FROM supplier_prices ORDER BY asin, ean LIMIT 300")]
    return render_template("research/supplier_prices.html", summary=repo.supplier_price_summary(), prices=prices, problems=problems)


@bp.get("/supplier-prices/template.csv")
def supplier_template():
    data = "ASIN,EAN,Unit cost,Supplier,Product name\nB0EXAMPLE1,5012345678900,6.50,Example Wholesale Ltd,Example product\n"
    return send_file(io.BytesIO(("﻿" + data).encode("utf-8")), as_attachment=True, mimetype="text/csv",
                     download_name="supplier-price-list-template.csv")


def apply_supplier_prices() -> int:
    """Give researched products the costs from the new price list (never over a cost the user typed)."""
    from ..domain.product import Product
    from ..services.evaluator import FIELD_LABELS  # noqa: F401 - keeps import graph explicit

    repo, service = _repo(), get_service()
    count = 0
    for product in service.repo.all(include_archived=True):
        if product.source != SOURCE_AMAZON or not product.asin:
            continue
        meta = dict(product.field_meta or {})
        if meta.get("sourcing_price", {}).get("source") in ("manual", "import", "smart_paste"):
            continue
        price = repo.supplier_price(product.asin)
        new_cost = price["cost"] if price else None
        if new_cost == product.sourcing_price:
            continue
        updated = Product.from_mapping({**product.__dict__})
        updated.sourcing_price = new_cost
        updated.supplier = price.get("supplier") if price else None
        meta["sourcing_price"] = {"source": "supplier_price_list", "at": now_iso(), "kind": "raw", "certainty": "verified",
                                  "note": f"Matched on ASIN in {price['source_name']}." if price else "No longer in your price list."}
        updated.field_meta = meta
        stored = service.update(product.id, updated, commit=False)
        settings = service.settings
        if stored.evaluation["status"] == REJECTED:
            ev = stored.evaluation
            repo.record_rejection(stored.asin, product_id=stored.id, brand=stored.brand, title=stored.title,
                                  amazon_url=stored.amazon_url, reasons=ev["summary"],
                                  failed_rules=[r for r in ev["rules"] if r["status"] == "fail"], criteria=settings.criteria(),
                                  criteria_fingerprint=settings.criteria_fingerprint(), engine_version="price-list",
                                  search_id=stored.last_brand_search_id)
        count += 1
    get_conn().commit()
    return count
