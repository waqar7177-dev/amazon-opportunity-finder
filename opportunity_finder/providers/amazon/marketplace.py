"""Marketplace definitions. Adding another Amazon store means adding one entry here — the collectors,
parsers and the evaluation engine take a Marketplace and never hard-code a domain."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote_plus


@dataclass(frozen=True)
class Marketplace:
    key: str
    label: str
    domain: str
    currency: str
    currency_symbol: str
    locale: str
    default_postcode: str
    preference_cookies: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def base_url(self) -> str:
        return f"https://www.{self.domain}"

    def search_url(self, query: str, page: int = 1) -> str:
        url = f"{self.base_url}/s?k={quote_plus(query)}"
        return url if page <= 1 else f"{url}&page={page}"

    def product_url(self, asin: str) -> str:
        return f"{self.base_url}/dp/{asin}"

    def offers_url(self, asin: str) -> str:
        # All Offers Display fragment (the "Other sellers on Amazon" panel). /gp/offer-listing is
        # disallowed in robots.txt and is never used.
        return f"{self.base_url}/gp/product/ajax/aodAjaxMain/?asin={asin}&pc=dp&experienceId=aodAjaxMain"

    def cookies(self) -> list[dict]:
        return [{"name": n, "value": v, "domain": f".{self.domain}", "path": "/"} for n, v in self.preference_cookies]


AMAZON_UK = Marketplace(
    key="amazon_uk",
    label="Amazon UK",
    domain="amazon.co.uk",
    currency="GBP",
    currency_symbol="£",
    locale="en-GB",
    default_postcode="SW1A 1AA",
    preference_cookies=(("i18n-prefs", "GBP"), ("lc-acbuk", "en_GB")),
)

MARKETPLACES = {m.key: m for m in (AMAZON_UK,)}


def get_marketplace(key: str | None) -> Marketplace:
    return MARKETPLACES.get(key or "", AMAZON_UK)
