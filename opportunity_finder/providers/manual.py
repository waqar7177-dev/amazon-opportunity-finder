"""Manual provider: data the user typed, pasted (Smart Paste) or imported. Always available, never online."""
from __future__ import annotations

from datetime import datetime

from .base import DataProvider, ProviderResult

ESTIMATED_FIELDS = {"monthly_sales"}


class ManualProvider(DataProvider):
    name = "manual"
    label = "Manual entry, Smart Paste and bulk import"

    def is_configured(self) -> bool:
        return True

    def status_text(self) -> str:
        return "Active — data comes from what you enter, paste or import. Nothing is fetched from Amazon."

    def from_values(self, values: dict, source: str = "manual") -> ProviderResult:
        clean = {k: v for k, v in values.items() if v not in (None, "")}
        provenance = {k: ("estimated" if k in ESTIMATED_FIELDS else "raw") for k in clean}
        return ProviderResult(provider=source, values=clean, provenance=provenance,
                              fetched_at=datetime.now().replace(microsecond=0).isoformat())
