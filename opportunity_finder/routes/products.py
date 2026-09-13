"""Add, list, view, edit, duplicate, archive and delete products."""
from __future__ import annotations

import json
from dataclasses import asdict

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..app_factory import get_service
from ..constants import SOURCE_MANUAL, SOURCE_SMART_PASTE, STATUS_LABELS, STATUSES
from ..domain.product import Product
from ..parsers.amazon_text import parse_amazon_text
from ..services.duplicates import find_duplicates
from ..services.evaluator import FIELD_LABELS
from ..services.product_query import PER_PAGE_CHOICES, SORTS, ProductQuery, run_query
from ..services.product_service import ProductNotFound
from ..services.ranking import SCORE_COMPONENTS, rank
from ..services.risk_engine import risk_model_description
from ..services.target_plan import build_target_plan
from ..services.calculator import FORMULAS
from .forms import extracted_from_form, form_context, product_to_form, safe_next, submitted_form

bp = Blueprint("products", __name__)


def _load(pid: int) -> Product:
    try:
        return get_service().get(pid)
    except ProductNotFound:
        abort(404)


def _status_flash(product: Product, verb: str) -> None:
    ev = product.evaluation
    tone = {"qualified": "ok", "needs_verification": "warn", "high_risk": "bad", "rejected": "bad"}.get(ev["status"], "info")
    flash(f"{verb} “{product.display_name}” — {ev['status_label']}.", tone)


# ------------------------------------------------------------------- list
@bp.get("/products")
def list_products():
    g.active_nav = "products"
    service = get_service()
    items = service.items(include_archived=True)
    query = ProductQuery.from_args(request.args)
    result = run_query(items, query)
    active = [i for i in items if not i["product"].archived]
    counts = {s: sum(1 for i in active if i["evaluation"]["status"] == s) for s in STATUSES}
    for message in query.errors:
        flash(message, "warn")
    return render_template("products/list.html", query=query, result=result, counts=counts,
                           total_active=len(active), archived_count=len(items) - len(active),
                           categories=service.repo.categories(), per_page_choices=PER_PAGE_CHOICES, sorts=SORTS)


@bp.post("/products/bulk")
def bulk():
    service = get_service()
    ids = [int(x) for x in request.form.getlist("ids") if x.isdigit()]
    action = request.form.get("action", "")
    back = safe_next(url_for(".list_products"))
    if not ids:
        flash("Select at least one product first.", "warn")
        return redirect(back)
    if action in ("export_excel", "export_csv"):
        kind = "excel" if action == "export_excel" else "csv"
        return redirect(url_for(f"exports.{kind}", scope="selected", id=ids))
    done = 0
    for pid in ids:
        try:
            if action == "archive":
                service.set_archived(pid, True)
            elif action == "unarchive":
                service.set_archived(pid, False)
            elif action == "delete":
                if request.form.get("confirm") != "yes":
                    flash("Deleting needs confirmation. Nothing was deleted.", "warn")
                    return redirect(back)
                service.delete(pid)
            elif action == "reevaluate":
                service.reevaluate(pid)
            else:
                flash("Choose what to do with the selected products.", "warn")
                return redirect(back)
            done += 1
        except ProductNotFound:
            continue
    verb = {"archive": "Archived", "unarchive": "Restored", "delete": "Deleted", "reevaluate": "Re-evaluated"}[action]
    flash(f"{verb} {done} product{'s' if done != 1 else ''}.", "ok")
    return redirect(back)


@bp.post("/products/reevaluate-all")
def reevaluate_all():
    count = get_service().reevaluate_all()
    flash(f"Re-evaluated {count} product{'s' if count != 1 else ''} with the current settings and fee table.", "ok")
    return redirect(safe_next(url_for(".list_products")))


# -------------------------------------------------------------------- add
def _render_new(values, errors=None, warnings=None, status=200, **extra):
    g.active_nav = "add"
    method = extra.pop("method", None) or request.values.get("method", "paste")
    return render_template("products/new.html", method=method if method in ("paste", "manual") else "paste",
                           **form_context(values, errors, warnings, **extra)), status


@bp.get("/products/new")
def new_product():
    return _render_new(product_to_form(Product()))


@bp.post("/products/new/paste")
def smart_paste():
    text = request.form.get("pasted_text", "")
    result = parse_amazon_text(text)
    values = product_to_form(Product(source=SOURCE_SMART_PASTE))
    for key, extracted in result.fields.items():
        if key in values:
            values[key] = extracted.value if isinstance(extracted.value, bool) else (
                f"{extracted.value:.2f}" if key == "selling_price" else
                (str(int(extracted.value)) if isinstance(extracted.value, float) and extracted.value.is_integer()
                 else str(extracted.value)))
    extracted = {k: asdict(v) for k, v in result.fields.items()}
    return _render_new(values, method="paste", parsed=True, extracted=extracted,
                       price_candidates=result.price_candidates, parse_warnings=result.warnings,
                       parse_info=result.info, pasted_text=text,
                       status=200 if result.found_any else 422)


@bp.post("/products/new")
def create_product():
    service = get_service()
    from ..services.validation import validate_product

    action = request.form.get("duplicate_action", "")
    if action == "cancel":
        flash("Nothing was saved.", "info")
        return redirect(url_for(".new_product"))
    validation = validate_product(request.form)
    extracted = extracted_from_form()
    context = dict(method=request.form.get("method", "manual"), extracted=extracted, parsed=bool(extracted),
                   pasted_text=request.form.get("pasted_text", ""))
    if not validation.ok:
        flash("Please fix the highlighted fields — nothing was saved yet.", "bad")
        return _render_new(submitted_form(), validation.errors, validation.warnings, status=422, **context)

    product = validation.product
    product.source = SOURCE_SMART_PASTE if request.form.get("source") == SOURCE_SMART_PASTE else SOURCE_MANUAL
    if action == "update":
        target = request.form.get("duplicate_id", "")
        if target.isdigit():
            try:
                updated = service.merge(int(target), product, provided=None, source=product.source)
            except ProductNotFound:
                abort(404)
            _status_flash(updated, "Updated existing product")
            return redirect(url_for(".detail", pid=updated.id))
    if action != "create":
        duplicates = find_duplicates(service.repo, product)
        if duplicates:
            return _render_new(submitted_form(), {}, validation.warnings, status=409, duplicates=duplicates, **context)

    pid = service.create(product)
    for message in validation.warnings.values():
        flash(message, "warn")
    _status_flash(service.get(pid), "Saved")
    return redirect(url_for(".detail", pid=pid))


# ----------------------------------------------------------------- detail
@bp.get("/products/<int:pid>")
def detail(pid: int):
    g.active_nav = "products"
    service = get_service()
    product = _load(pid)
    items = service.items()
    plan = build_target_plan(items, service.settings)
    ranked = rank(items)
    position = next((i["rank"] for i in ranked if i["product"].id == pid), None)
    return render_template("products/detail.html", product=product, ev=product.evaluation, history=service.history(pid),
                           settings=service.settings, in_plan=pid in plan["selected_ids"], rank_position=position,
                           ranked_count=len(ranked), score_components=SCORE_COMPONENTS, risk_model=risk_model_description(),
                           formulas=FORMULAS, field_labels=FIELD_LABELS, status_labels=STATUS_LABELS)


# ------------------------------------------------------------------- edit
@bp.route("/products/<int:pid>/edit", methods=["GET", "POST"])
def edit(pid: int):
    g.active_nav = "products"
    service = get_service()
    product = _load(pid)
    if request.method == "GET":
        return render_template("products/edit.html", product=product, **form_context(product_to_form(product)))

    from ..services.validation import validate_product

    validation = validate_product(request.form, base=product)
    if not validation.ok:
        flash("Please fix the highlighted fields — your changes were not saved yet.", "bad")
        return render_template("products/edit.html", product=product,
                               **form_context(submitted_form(), validation.errors, validation.warnings)), 422
    if request.form.get("duplicate_action") != "save":
        duplicates = find_duplicates(service.repo, validation.product, exclude_id=pid)
        if duplicates:
            return render_template("products/edit.html", product=product, duplicates=duplicates,
                                   **form_context(submitted_form(), {}, validation.warnings)), 409
    updated = service.update(pid, validation.product, mark_checked=bool(request.form.get("mark_checked")))
    for message in validation.warnings.values():
        flash(message, "warn")
    _status_flash(updated, "Saved changes to")
    return redirect(url_for(".detail", pid=pid))


# ---------------------------------------------------------------- actions
@bp.route("/products/<int:pid>/delete", methods=["GET", "POST"])
def delete(pid: int):
    g.active_nav = "products"
    product = _load(pid)
    if request.method == "GET" or request.form.get("confirm") != "yes":
        return render_template("products/confirm_delete.html", product=product)
    get_service().delete(pid)
    flash(f"Deleted “{product.display_name}”.", "ok")
    return redirect(url_for(".list_products"))


@bp.post("/products/<int:pid>/duplicate")
def duplicate(pid: int):
    _load(pid)
    new_id = get_service().duplicate(pid)
    flash("Copy created. Change what's different, then save.", "ok")
    return redirect(url_for(".edit", pid=new_id))


@bp.post("/products/<int:pid>/archive")
def archive(pid: int):
    product = _load(pid)
    get_service().set_archived(pid, True)
    flash(f"Archived “{product.display_name}”. It is hidden from lists, the dashboard and exports.", "ok")
    return redirect(safe_next(url_for(".detail", pid=pid)))


@bp.post("/products/<int:pid>/unarchive")
def unarchive(pid: int):
    product = _load(pid)
    get_service().set_archived(pid, False)
    flash(f"Restored “{product.display_name}”.", "ok")
    return redirect(safe_next(url_for(".detail", pid=pid)))


@bp.post("/products/<int:pid>/reevaluate")
def reevaluate(pid: int):
    _load(pid)
    get_service().reevaluate(pid)
    _status_flash(get_service().get(pid), "Re-evaluated")
    return redirect(safe_next(url_for(".detail", pid=pid)))


def extracted_json(extracted: dict | None) -> str:
    return json.dumps({k: {"confidence": v.get("confidence"), "note": v.get("note", ""), "evidence": v.get("evidence", "")}
                       for k, v in (extracted or {}).items()})


@bp.app_template_global()
def extracted_payload(extracted):
    return extracted_json(extracted)
