"""Data provider interface.

The rest of the app never cares where product data came from. A provider turns
its source (a form, pasted text, an import row, or one day an API such as Keepa)
into plain product field values plus provenance. Calculations, rules and risk
only ever see a ``Product``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ProviderNotAvailable(RuntimeError):
    """The provider is disabled, not configured, or not implemented in this version."""


@dataclass
class ProviderResult:
    provider: str
    values: dict                          # product field -> value (only fields the provider knows)
    provenance: dict = field(default_factory=dict)  # field -> "raw" | "estimated" | free text
    fetched_at: str | None = None
    history: dict | None = None           # e.g. {"selling_price": [(iso_date, value), ...]} for Keepa-style data
    warnings: list[str] = field(default_factory=list)


class DataProvider(ABC):
    name: str = "base"
    label: str = "Base provider"
    requires_network: bool = False

    @abstractmethod
    def is_configured(self) -> bool:
        ...

    @abstractmethod
    def status_text(self) -> str:
        ...

    def fetch(self, asin: str) -> ProviderResult:
        raise ProviderNotAvailable(f"{self.label} cannot look up products automatically.")
