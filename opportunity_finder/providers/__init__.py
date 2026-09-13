"""Data providers. See base.py for the interface."""
from .base import DataProvider, ProviderNotAvailable, ProviderResult
from .keepa import KeepaProvider
from .manual import ManualProvider


def provider_statuses(config) -> list[dict]:
    providers: list[DataProvider] = [
        ManualProvider(),
        KeepaProvider(getattr(config, "KEEPA_API_KEY", "") or "", bool(getattr(config, "ENABLE_KEEPA", False))),
    ]
    return [{"name": p.name, "label": p.label, "active": p.is_configured(), "status": p.status_text(),
             "network": p.requires_network} for p in providers]


__all__ = ["DataProvider", "ProviderNotAvailable", "ProviderResult", "KeepaProvider", "ManualProvider", "provider_statuses"]
