"""Excel workbook for one brand search — reuses the product sheet writer from excel_export."""
from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font

from ..constants import (APP_NAME, COLLECTION_FAILED, ESTIMATE_DISCLAIMER, FEE_DISCLAIMER, HIGH_RISK, INCOMPLETE,
                         NEEDS_VERIFICATION, NOT_BRAND, OUTCOME_LABELS, QUALIFIED, REJECTED, SEARCH_STATUS_LABELS,
                         SKIPPED_REJECTED)
from ..formatting import parse_iso
from .excel_export import DATE, GBP, INT, _core_columns, _tail_columns, _tone, _write_table, safe_text
from .ranking import rank


def build_brand_workbook(search: dict, report: dict, generated_at: datetime | None = None) -> bytes:
    """``report`` comes from routes.research.build_report: counts, winners (ranked items), rejected, incomplete,
    review, skipped (items), failures (items), not_brand (items), criteria."""
    generated_at = generated_at or datetime.now()
    wb = Workbook()
    ctx = {"plan_ids": set()}

    ws = wb.active
    ws.title = "Summary"
    _summary(ws, search, report, generated_at)

    ws = wb.create_sheet("Winning Products")
    cols = ([("Rank", 7, INT, lambda i, c: i.get("rank")), ("Opportunity Score", 10, INT,
             lambda i, c: (i["evaluation"].get("score") or {}).get("total"))]
            + _core_columns() + _tail_columns())
    _write_table(ws, cols, rank(report["winners"]), ctx, "No winning products in this search.", freeze="E2")

    ws = wb.create_sheet("Rejected")
    cols = _core_columns() + [("Rejected because", 50, None, lambda i, c: "\n".join(i["evaluation"]["summary"]))] + _tail_columns()
    _write_table(ws, cols, report["rejected"], ctx, "No products were rejected in this search.")

    ws = wb.create_sheet("Incomplete")
    cols = _core_columns()[:11] + [("Missing data", 60, None, lambda i, c: "\n".join(m["message"] for m in i["evaluation"]["missing"]))] \
        + _tail_columns()
    _write_table(ws, cols, report["incomplete"], ctx, "No products with missing data.")

    if report["review"]:
        ws = wb.create_sheet("Needs Review")
        cols = [("Status", 18, None, lambda i, c: i["evaluation"]["status_label"])] + _core_columns() + [
            ("Reasons", 50, None, lambda i, c: "\n".join(i["evaluation"]["summary"]))] + _tail_columns()
        _write_table(ws, cols, report["review"], ctx, "Nothing needs review.", freeze="D2")

    ws = wb.create_sheet("Skipped Previously Rejected")
    cols = [
        ("ASIN", 13, None, lambda i, c: i["asin"]),
        ("Product", 46, None, lambda i, c: i.get("title")),
        ("Previously rejected because", 60, None, lambda i, c: "\n".join(i.get("reasons") or [])),
        ("Amazon URL", 34, None, lambda i, c: f"https://www.amazon.co.uk/dp/{i['asin']}"),
    ]
    _write_table(ws, cols, report["skipped"], ctx, "No previously rejected products were skipped.", freeze="C2")

    ws = wb.create_sheet("Collection Errors")
    cols = [
        ("ASIN", 13, None, lambda i, c: i["asin"]),
        ("Product", 46, None, lambda i, c: i.get("title")),
        ("Problem", 60, None, lambda i, c: i.get("error") or "\n".join(i.get("reasons") or [])),
        ("Amazon URL", 34, None, lambda i, c: f"https://www.amazon.co.uk/dp/{i['asin']}"),
    ]
    _write_table(ws, cols, report["failures"], ctx, "No collection errors.", freeze="C2")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _summary(ws, search: dict, report: dict, generated_at: datetime) -> None:
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 30
    ws.append([f"{APP_NAME} — Brand report"])
    ws["A1"].font = Font(bold=True, size=15)
    ws.append(["ESTIMATES ONLY. " + ESTIMATE_DISCLAIMER + " " + FEE_DISCLAIMER])
    ws["A2"].font = Font(italic=True, color="B45309")
    ws.append([])
    c = report["counts"]
    started = parse_iso(search.get("started_at") or search.get("created_at"))
    rows = [
        ("Brand", safe_text(search["query"]), None),
        ("Marketplace", "Amazon UK", None),
        ("Analyzed", started, "dd mmm yyyy hh:mm"),
        ("Search status", SEARCH_STATUS_LABELS.get(search["status"], search["status"]), None),
        ("Search result pages scanned", search.get("pages_processed") or 0, INT),
        ("Products discovered", c.get("discovered", 0), INT),
        ("Previously analyzed", c.get("previously_analyzed", 0), INT),
        ("Previously rejected — skipped", c.get(SKIPPED_REJECTED, 0), INT),
        ("New products analyzed", report["new_analyzed"], INT),
        ("Winning (qualified)", c.get(QUALIFIED, 0), INT),
        ("Rejected", c.get(REJECTED, 0), INT),
        ("Incomplete data", c.get(INCOMPLETE, 0), INT),
        ("Needs verification", c.get(NEEDS_VERIFICATION, 0), INT),
        ("High risk", c.get(HIGH_RISK, 0), INT),
        ("Not this brand", c.get(NOT_BRAND, 0), INT),
        ("Collection failures", c.get(COLLECTION_FAILED, 0), INT),
        ("Conservative monthly profit — winners (EST)", report["winners_conservative_profit"], GBP),
        ("Report generated", generated_at.replace(microsecond=0), "dd mmm yyyy hh:mm"),
    ]
    for label, value, fmt in rows:
        ws.append([label, value])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
        if fmt:
            ws.cell(ws.max_row, 2).number_format = fmt
        if label == "Search status":
            _tone(ws.cell(ws.max_row, 2), "ok" if search["status"] == "completed" else "warn")
    ws.append([])
    ws.append(["Qualification rules used"])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    for rule in report["rules"]:
        ws.append([rule["text"]])
    ws.append([])
    ws.append(["Monthly sales come only from Amazon's “bought in past month” badge (a lower bound). Sourcing costs come only "
               "from your supplier price list. Nothing missing is guessed."])
    ws.cell(ws.max_row, 1).font = Font(italic=True, color="6B7280")


__all__ = ["build_brand_workbook", "OUTCOME_LABELS", "DATE"]
