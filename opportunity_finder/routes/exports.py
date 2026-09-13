import io
from datetime import datetime

from flask import Blueprint, request, send_file

from ..app_factory import get_service
from ..services.excel_export import build_csv, build_workbook
from ..services.product_query import ProductQuery, run_query
from ..services.ranking import rank
from ..services.target_plan import build_target_plan

bp = Blueprint("exports", __name__)


def _scope():
    service = get_service()
    everything = service.items(include_archived=True)
    active = [i for i in everything if not i["product"].archived]
    plan = build_target_plan(active, service.settings)
    rank(active)  # sets rank numbers on the shared item dicts
    scope = request.args.get("scope", "all")
    if scope == "filtered":
        chosen = run_query(everything, ProductQuery.from_args(request.args))["all"]
    elif scope == "selected":
        ids = {int(x) for x in request.args.getlist("id") if x.isdigit()}
        chosen = [i for i in everything if i["product"].id in ids]
    else:
        chosen = active
    return chosen, plan, service.settings


def _stamp():
    return datetime.now().strftime("%Y-%m-%d-%H%M")


@bp.get("/export/excel")
def excel():
    items, plan, settings = _scope()
    data = build_workbook(items, plan, settings)
    return send_file(io.BytesIO(data), as_attachment=True, download_name=f"amazon-uk-opportunities-{_stamp()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.get("/export/csv")
def csv():
    items, _, _ = _scope()
    return send_file(io.BytesIO(build_csv(items)), as_attachment=True, mimetype="text/csv",
                     download_name=f"amazon-uk-products-{_stamp()}.csv")
