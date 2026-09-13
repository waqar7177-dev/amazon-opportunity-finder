from flask import Blueprint, g, render_template

from ..app_factory import get_conn, get_service
from ..constants import QUALIFIED, REJECTED, SEARCH_STATUS_LABELS, SEARCH_STATUS_TONE
from ..database.research_repository import ResearchRepository
from ..services.ranking import rank

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index():
    """Deliberately minimal: analyze a brand, see recent searches, see winners."""
    g.active_nav = "dashboard"
    repo = ResearchRepository(get_conn())
    items = get_service().items()
    recent = []
    for s in repo.recent_searches(6):
        counts = repo.outcome_counts(s["id"])
        recent.append({**s, "winners": counts.get(QUALIFIED, 0), "rejected": counts.get(REJECTED, 0),
                       "discovered": counts.get("discovered", 0)})
    active = repo.active_search()
    stats = {
        "brands": len(repo.brand_history()),
        "products": len(items),
        "winners": sum(1 for i in items if i["evaluation"]["status"] == QUALIFIED),
        "rejected": sum(1 for i in items if i["evaluation"]["status"] == REJECTED),
    }
    return render_template("dashboard.html", recent=recent, winners=rank(items)[:8], active=active, stats=stats,
                           status_labels=SEARCH_STATUS_LABELS, status_tone=SEARCH_STATUS_TONE)
