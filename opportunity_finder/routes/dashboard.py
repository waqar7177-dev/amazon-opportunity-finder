from flask import Blueprint, g, render_template

from ..app_factory import get_service
from ..constants import HIGH_RISK, INCOMPLETE, NEEDS_VERIFICATION, QUALIFIED, REJECTED, RISK_HIGH, STATUSES
from ..numbers import money, round_to
from ..services.ranking import rank
from ..services.target_plan import build_target_plan

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index():
    g.active_nav = "dashboard"
    service = get_service()
    items = service.items()
    settings = service.settings
    by_status = {s: [i for i in items if i["evaluation"]["status"] == s] for s in STATUSES}
    qualified = by_status[QUALIFIED]

    def total(key):
        return money(sum(i["evaluation"]["profit"][key] or 0 for i in qualified))

    rois = [i["evaluation"]["profit"]["roi_pct"] for i in qualified if i["evaluation"]["profit"]["roi_pct"] is not None]
    profits = [i["evaluation"]["profit"]["net_profit"] for i in qualified if i["evaluation"]["profit"]["net_profit"] is not None]
    conservative = total("conservative_monthly_profit")
    target = settings.monthly_profit_target
    stats = {
        "total": len(items),
        "qualified": len(qualified),
        "rejected": len(by_status[REJECTED]),
        "incomplete": len(by_status[INCOMPLETE]),
        "needs_verification": len(by_status[NEEDS_VERIFICATION]),
        "high_risk_status": len(by_status[HIGH_RISK]),
        "high_risk": sum(1 for i in items if i["evaluation"]["risk"]["level"] == RISK_HIGH),
        "conservative": conservative,
        "theoretical": total("theoretical_monthly_profit"),
        "target": target,
        "progress_pct": round(min(conservative / target * 100, 100), 1) if target else 0,
        "remaining": money(max(0.0, target - conservative)),
        "avg_roi": round_to(sum(rois) / len(rois), 1) if rois else None,
        "avg_profit": money(sum(profits) / len(profits)) if profits else None,
    }
    recent = sorted(items, key=lambda i: i["product"].updated_at or "", reverse=True)[:5]
    return render_template(
        "dashboard.html",
        stats=stats,
        by_status=by_status,
        top=rank(items)[:5],
        plan=build_target_plan(items, settings),
        recent=recent,
        settings=settings,
    )
