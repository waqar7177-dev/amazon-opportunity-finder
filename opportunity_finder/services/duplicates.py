"""Duplicate detection: ASIN first, then Amazon URL, then title + brand."""
from __future__ import annotations

from dataclasses import dataclass

from ..database.repositories import ProductRepository
from ..domain.product import Product


@dataclass
class DuplicateMatch:
    product: Product
    matched_on: str  # asin | url | title_brand

    @property
    def reason(self) -> str:
        return {
            "asin": f"Same ASIN ({self.product.asin})",
            "url": "Same Amazon URL",
            "title_brand": "Same title and brand",
        }[self.matched_on]


def find_duplicates(repo: ProductRepository, candidate: Product, exclude_id: int | None = None) -> list[DuplicateMatch]:
    if candidate.asin:
        return [DuplicateMatch(p, "asin") for p in repo.find_by_asin(candidate.asin, exclude_id)]
    if candidate.amazon_url:
        found = repo.find_by_url(candidate.amazon_url, exclude_id)
        if found:
            return [DuplicateMatch(p, "url") for p in found]
    if candidate.title:
        return [DuplicateMatch(p, "title_brand") for p in repo.find_by_title_brand(candidate.title, candidate.brand, exclude_id)]
    return []


def identity_key(product: Product) -> str | None:
    """Key used to spot duplicates inside one import file."""
    if product.asin:
        return f"asin:{product.asin.upper()}"
    if product.amazon_url:
        return f"url:{product.amazon_url.lower().rstrip('/')}"
    if product.title:
        return f"tb:{product.title.strip().lower()}|{(product.brand or '').strip().lower()}"
    return None
