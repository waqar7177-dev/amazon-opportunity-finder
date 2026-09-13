"""Small JSON endpoints used by the live estimate panel on the product form."""
from flask import Blueprint, jsonify, request

from ..app_factory import get_service
from ..constants import APP_VERSION, STATUS_STYLE
from ..formatting import fmt_int, fmt_money, fmt_pct
from ..services.product_service import ProductNotFound
from ..services.validation import validate_product

bp = Blueprint("api", __name__)


@bp.get("/health")
def health():
    return jsonify({"ok": True, "version": APP_VERSION})


@bp.post("/api/preview")
def preview():
    service = get_service()
    base = None
    pid = request.form.get("product_id", "")
    if pid.isdigit():
        try:
            base = service.get(int(pid))
        except ProductNotFound:
            base = None
    validation = validate_product(request.form, base=base)
    ev = service.evaluate_product(validation.product)
    fees, profit, risk = ev["fees"], ev["profit"], ev["risk"]
    other = None
    if fees["total_fees"] is not None:
        other = round(fees["fuel_surcharge"] + fees["dangerous_goods_fee"] + fees["digital_services_fee"] + fees["vat_on_fees"], 2)
    return jsonify({
        "ok": True,
        "errors": validation.errors,
        "status": ev["status"],
        "status_label": ev["status_label"],
        "tone": STATUS_STYLE[ev["status"]]["tone"],
        "symbol": STATUS_STYLE[ev["status"]]["symbol"],
        "summary": ev["summary"][:6],
        "score": (ev.get("score") or {}).get("total"),
        "fees": {
            "referral": fmt_money(fees["referral_fee"]),
            "fba": fmt_money(fees["fba_fee"]) if fees["fba_source"] != "not_applicable" else "Not applicable (FBM)",
            "other": fmt_money(other),
            "total": fmt_money(fees["total_fees"]),
            "tier": fees["size_tier_label"] or "",
            "confidence": fees["confidence"],
            "warnings": fees["warnings"],
        },
        "profit": {
            "net": fmt_money(profit["net_profit"]),
            "net_negative": (profit["net_profit"] or 0) < 0,
            "roi": fmt_pct(profit["roi_pct"]),
            "margin": fmt_pct(profit["margin_pct"]),
            "capture": fmt_pct(profit["capture_rate_pct"]),
            "units": fmt_int(profit["conservative_units"]),
            "conservative": fmt_money(profit["conservative_monthly_profit"]),
            "theoretical": fmt_money(profit["theoretical_monthly_profit"]),
            "max_sourcing": fmt_money(profit["max_sourcing_price"]),
        },
        "risk": {"level": risk["level"], "score": risk["score"], "reasons": [r["label"] for r in risk["reasons"]]},
        "missing": [m["message"] for m in ev["missing"]],
    })
