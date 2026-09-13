from collections import Counter

from flask import Blueprint, g, render_template, request

from ..app_factory import get_service
from ..constants import HIGH_RISK, INCOMPLETE, NEEDS_VERIFICATION, REJECTED
from ..services.evaluator import FIELD_LABELS
from ..services.qualification import describe_rules
from ..services.ranking import SCORE_COMPONENTS, rank
from ..services.target_plan import build_target_plan

bp = Blueprint("opportunities", __name__)


def _score(item):
    return (item["evaluation"].get("score") or {}).get("total") or -1


@bp.get("/opportunities")
def index():
    g.active_nav = "opportunities"
    service = get_service()
    items = service.items()
    settings = service.settings
    review = sorted((i for i in items if i["evaluation"]["status"] in (HIGH_RISK, NEEDS_VERIFICATION)), key=_score, reverse=True)
    return render_template("opportunities.html", ranked=rank(items), plan=build_target_plan(items, settings),
                           review=review, settings=settings, score_components=SCORE_COMPONENTS,
                           rules=describe_rules(settings))


@bp.get("/rejected")
def rejected():
    g.active_nav = "rejected"
    service = get_service()
    items = service.items()
    tab = request.args.get("tab", "rejected")
    tab = tab if tab in ("rejected", "incomplete", "history") else "rejected"
    from ..app_factory import get_conn
    from ..database.research_repository import ResearchRepository

    research = ResearchRepository(get_conn())
    history = research.rejected()
    current_fp = service.settings.criteria_fingerprint()
    rejected_items = sorted((i for i in items if i["evaluation"]["status"] == REJECTED), key=lambda i: i["product"].display_name.lower())
    incomplete_items = sorted((i for i in items if i["evaluation"]["status"] == INCOMPLETE), key=lambda i: i["product"].display_name.lower())

    failing = Counter(r["label"] for i in rejected_items for r in i["evaluation"]["rules"] if r["status"] == "fail")
    missing = Counter(m["label"] for i in incomplete_items for m in i["evaluation"]["missing"])
    return render_template("rejected.html", tab=tab, rejected=rejected_items, incomplete=incomplete_items,
                           failing=failing.most_common(), missing=missing.most_common(), rules=describe_rules(service.settings),
                           field_labels=FIELD_LABELS, history=history, current_fp=current_fp,
                           changed_rules=sum(1 for h in history if h["criteria_fingerprint"] != current_fp))
