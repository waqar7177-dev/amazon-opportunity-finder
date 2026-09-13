"""Search, filter, sort and paginate evaluated products (server-side, so URLs are shareable/bookmarkable)."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from urllib.parse import urlencode

from ..constants import RISK_LEVELS, STATUSES
from ..numbers import parse_number, parse_whole

PER_PAGE_CHOICES = (10, 25, 50, 100)
RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
STATUS_ORDER = {s: i for i, s in enumerate(STATUSES)}


def _p(item):
    return item["product"]


def _e(item):
    return item["evaluation"]


SORTS = {
    "score": lambda i: (_e(i).get("score") or {}).get("total"),
    "asin": lambda i: (_p(i).asin or "").lower() or None,
    "title": lambda i: (_p(i).display_name or "").lower(),
    "brand": lambda i: (_p(i).brand or "").lower() or None,
    "price": lambda i: _p(i).selling_price,
    "bsr": lambda i: _p(i).bsr,
    "sellers": lambda i: _p(i).total_sellers,
    "fba_sellers": lambda i: _p(i).fba_sellers,
    "sales": lambda i: _p(i).monthly_sales,
    "sourcing": lambda i: _p(i).sourcing_price,
    "fees": lambda i: _e(i)["fees"]["total_fees"],
    "profit": lambda i: _e(i)["profit"]["net_profit"],
    "roi": lambda i: _e(i)["profit"]["roi_pct"],
    "cons_units": lambda i: _e(i)["profit"]["conservative_units"],
    "cons_profit": lambda i: _e(i)["profit"]["conservative_monthly_profit"],
    "risk": lambda i: RISK_ORDER.get(_e(i)["risk"]["level"]),
    "status": lambda i: STATUS_ORDER.get(_e(i)["status"]),
    "checked": lambda i: _p(i).amazon_checked_at,
    "updated": lambda i: _p(i).updated_at,
}


@dataclass
class ProductQuery:
    q: str = ""
    status: str = ""
    risk: str = ""
    category: str = ""
    roi_min: float | None = None
    roi_max: float | None = None
    bsr_min: int | None = None
    bsr_max: int | None = None
    view: str = "active"  # active | archived | all
    sort: str = "score"
    direction: str = "desc"
    page: int = 1
    per_page: int = 25
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_args(cls, args, default_per_page: int = 25) -> "ProductQuery":
        q = cls(per_page=default_per_page)
        q.q = (args.get("q") or "").strip()[:200]
        q.status = args.get("status", "") if args.get("status", "") in STATUSES else ""
        q.risk = args.get("risk", "") if args.get("risk", "") in RISK_LEVELS else ""
        q.category = (args.get("category") or "").strip()[:200]
        q.view = args.get("view", "active") if args.get("view") in ("active", "archived", "all") else "active"
        q.sort = args.get("sort", "score") if args.get("sort") in SORTS else "score"
        q.direction = "asc" if args.get("dir") == "asc" else "desc"
        for name, label in (("roi_min", "Minimum ROI"), ("roi_max", "Maximum ROI")):
            value, err = parse_number(args.get(name), label, allow_negative=True)
            setattr(q, name, value)
            if err:
                q.errors.append(err)
        for name, label in (("bsr_min", "Minimum BSR"), ("bsr_max", "Maximum BSR")):
            value, err = parse_whole(args.get(name), label, minimum=0)
            setattr(q, name, value)
            if err:
                q.errors.append(err)
        page, _ = parse_whole(args.get("page"), "Page", minimum=1)
        q.page = page or 1
        per_page, _ = parse_whole(args.get("per_page"), "Per page", minimum=1)
        q.per_page = per_page if per_page in PER_PAGE_CHOICES else default_per_page
        return q

    @property
    def active_filters(self) -> int:
        return sum(bool(x) or x == 0 for x in (self.q, self.status, self.risk, self.category)) + sum(
            v is not None for v in (self.roi_min, self.roi_max, self.bsr_min, self.bsr_max)) + (self.view != "active")

    def args(self, **changes) -> dict:
        data = {k: v for k, v in asdict(self).items() if k != "errors"}
        data["dir"] = data.pop("direction")
        data.update(changes)
        return {k: v for k, v in data.items() if v not in (None, "") and not (k == "view" and v == "active")
                and not (k == "page" and v == 1) and not (k == "sort" and v == "score" and data.get("dir") == "desc")
                and not (k == "dir" and v == "desc")}

    def url_args(self, **changes) -> str:
        return urlencode(self.args(**changes))

    def sort_args(self, key: str) -> str:
        direction = "asc" if (self.sort == key and self.direction == "desc") else "desc"
        if self.sort != key and key in ("asin", "title", "brand", "bsr", "fees", "risk", "status", "sourcing"):
            direction = "asc"
        return self.url_args(sort=key, dir=direction, page=1)


def filter_items(items: list[dict], query: ProductQuery) -> list[dict]:
    out = []
    needle = query.q.lower()
    for item in items:
        p, e = item["product"], item["evaluation"]
        if query.view == "active" and p.archived:
            continue
        if query.view == "archived" and not p.archived:
            continue
        if needle and not any(needle in (v or "").lower() for v in (p.asin, p.title, p.brand, p.supplier, p.category, p.notes)):
            continue
        if query.status and e["status"] != query.status:
            continue
        if query.risk and e["risk"]["level"] != query.risk:
            continue
        if query.category and (p.category or "").lower() != query.category.lower():
            continue
        roi = e["profit"]["roi_pct"]
        if query.roi_min is not None and (roi is None or roi < query.roi_min):
            continue
        if query.roi_max is not None and (roi is None or roi > query.roi_max):
            continue
        if query.bsr_min is not None and (p.bsr is None or p.bsr < query.bsr_min):
            continue
        if query.bsr_max is not None and (p.bsr is None or p.bsr > query.bsr_max):
            continue
        out.append(item)
    return out


def sort_items(items: list[dict], sort: str, direction: str) -> list[dict]:
    key = SORTS.get(sort, SORTS["score"])
    present = [i for i in items if key(i) is not None]
    absent = [i for i in items if key(i) is None]
    present.sort(key=lambda i: (key(i), -(i["product"].id or 0)), reverse=(direction == "desc"))
    return present + absent  # blanks always last


def run_query(items: list[dict], query: ProductQuery) -> dict:
    filtered = sort_items(filter_items(items, query), query.sort, query.direction)
    total = len(filtered)
    pages = max(1, math.ceil(total / query.per_page))
    query.page = min(query.page, pages)
    start = (query.page - 1) * query.per_page
    return {"items": filtered[start:start + query.per_page], "all": filtered, "total": total, "pages": pages,
            "start": start + 1 if total else 0, "end": min(start + query.per_page, total)}
