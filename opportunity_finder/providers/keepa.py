"""Keepa provider — a disabled stub in version 1.

Keepa is optional and nothing in the app depends on it. This class documents
how a future integration plugs in, without making any network calls:

1. Set ``KEEPA_API_KEY`` and ``AOF_ENABLE_KEEPA=1`` in ``.env``.
2. Implement ``fetch`` using Keepa's product endpoint for the UK domain
   (domain id 2), e.g. ``GET https://api.keepa.com/product?key=…&domain=2&asin=…&stats=90&offers=20``.
3. Map the response onto product fields with ``FIELD_MAP`` below and return a
   ``ProviderResult`` (``provenance`` = "raw" for observed values, "estimated"
   for derived ones such as monthly sales).
4. The route that calls it saves through ``ProductService.merge`` exactly like
   a bulk-import row, so evaluation, history snapshots and duplicates just work.

Until then ``fetch`` raises ``ProviderNotAvailable`` and no data leaves the machine.
"""
from __future__ import annotations

from .base import DataProvider, ProviderNotAvailable, ProviderResult

KEEPA_UK_DOMAIN_ID = 2

# Keepa product JSON -> our product fields (for the future implementation).
FIELD_MAP = {
    "selling_price": "stats.buyBoxPrice (pence; ÷100) — fall back to stats.current[NEW]",
    "bsr": "stats.current[SALES] (the SALES csv index is Keepa's sales rank)",
    "bsr_category": "categoryTree[0].name",
    "total_sellers": "stats.current[COUNT_NEW]",
    "fba_sellers": "count of offers[] where isFBA and condition == New (needs offers=)",
    "monthly_sales": "monthlySold (Amazon's 'bought in past month' lower bound) — mark as estimated",
    "flag_amazon_sells": "availabilityAmazon >= 0 or offers[].isAmazon",
    "title": "title",
    "brand": "brand",
    "weight_g": "packageWeight (grams)",
    "length_cm / width_cm / height_cm": "packageLength / packageWidth / packageHeight (mm; ÷10)",
    "history": "csv[AMAZON], csv[NEW], csv[SALES], csv[COUNT_NEW] — Keepa minutes since 2011-01-01",
}


class KeepaProvider(DataProvider):
    name = "keepa"
    label = "Keepa (optional)"
    requires_network = True

    def __init__(self, api_key: str = "", enabled: bool = False):
        self._has_key = bool(api_key)
        self._enabled = enabled

    def is_configured(self) -> bool:
        return self._has_key and self._enabled

    def status_text(self) -> str:
        if not self._has_key:
            return "Not configured — optional. Version 1 works fully without Keepa."
        if not self._enabled:
            return "A Keepa key is present but the integration is switched off (AOF_ENABLE_KEEPA=0)."
        return "Enabled in configuration, but the Keepa lookup is not implemented in version 1."

    def fetch(self, asin: str) -> ProviderResult:
        raise ProviderNotAvailable(
            "Keepa lookups are not part of version 1. Add product data manually, with Smart Paste or bulk import."
        )
