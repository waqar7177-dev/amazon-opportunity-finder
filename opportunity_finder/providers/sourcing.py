"""Sourcing provider: the user's own supplier price list.

A brand name never reveals a trade price, so costs come from a price list the user imports once
(CSV / XLSX with ASIN or EAN and a unit cost). Brand research looks each product up by ASIN, then by
EAN. A product without a match stays "Sourcing cost required" — no cost is ever guessed.
"""
from __future__ import annotations

import re

from ..numbers import is_blank, parse_number
from ..services.import_service import ImportFileError, read_upload

ALIASES = {
    "asin": {"asin"},
    "ean": {"ean", "barcode", "gtin", "upc", "ean13", "ean code"},
    "cost": {"cost", "unit cost", "price", "trade price", "wholesale price", "buy price", "cost price", "sourcing price",
             "net price", "cost per unit"},
    "supplier": {"supplier", "vendor", "supplier name"},
    "product_name": {"product", "product name", "description", "title", "name", "item"},
}
ASIN_RE = re.compile(r"^(B0[A-Z0-9]{8}|\d{9}[\dX])$")


def _norm(header) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(header or "").lower()).strip()


def map_columns(headers: list[str]) -> dict[str, int]:
    mapping = {}
    for index, header in enumerate(headers):
        name = _norm(header)
        for key, names in ALIASES.items():
            if name in names and key not in mapping:
                mapping[key] = index
    return mapping


def parse_price_list(filename: str, data: bytes) -> tuple[list[dict], list[tuple[int, str]]]:
    """Return (valid rows, [(row_number, problem)]). Raises ImportFileError for file-level problems."""
    table = read_upload(filename, data)
    cols = map_columns(table.headers)
    if "cost" not in cols:
        raise ImportFileError("The price list needs a cost column (for example “Cost” or “Unit cost”).")
    if "asin" not in cols and "ean" not in cols:
        raise ImportFileError("The price list needs an ASIN or EAN column to match products.")
    rows, problems, seen = [], [], set()
    for offset, raw in enumerate(table.rows):
        number = offset + 2

        def cell(key):
            return raw[cols[key]] if key in cols and cols[key] < len(raw) else ""

        asin = re.sub(r"\s+", "", str(cell("asin"))).upper() or None
        ean = re.sub(r"\D", "", str(cell("ean"))) or None
        if asin and not ASIN_RE.match(asin):
            problems.append((number, f"“{asin}” is not a valid ASIN."))
            continue
        if ean and not 8 <= len(ean) <= 14:
            problems.append((number, f"“{cell('ean')}” is not a valid EAN/barcode."))
            continue
        if not asin and not ean:
            problems.append((number, "No ASIN or EAN."))
            continue
        cost, err = parse_number(cell("cost"), "Cost")
        if err or cost is None:
            problems.append((number, err or "No cost."))
            continue
        key = asin or ean
        if key in seen:
            problems.append((number, f"{key} appears more than once; the first row was kept."))
            continue
        seen.add(key)
        rows.append({"asin": asin, "ean": ean, "cost": cost,
                     "supplier": None if is_blank(cell("supplier")) else str(cell("supplier")).strip()[:200],
                     "product_name": None if is_blank(cell("product_name")) else str(cell("product_name")).strip()[:300]})
    return rows, problems


__all__ = ["parse_price_list", "map_columns", "ImportFileError"]
