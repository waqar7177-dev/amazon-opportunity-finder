"""Background runner for brand searches.

One worker thread runs searches one at a time (so Amazon is never hit in parallel). All state lives in
SQLite, so the web pages only read the database, a restart turns a running search into "interrupted",
and "Resume" simply queues it again.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from ..database.db import connect
from ..database.research_repository import ResearchRepository
from ..domain.settings import Settings
from ..providers.amazon.browser import AmazonBrowser, PageCache, PageSource
from ..providers.amazon.marketplace import Marketplace, get_marketplace
from .brand_research import BrandResearch
from .product_service import ProductService

log = logging.getLogger("opportunity_finder.research")

SourceFactory = Callable[[Settings, Marketplace], PageSource]


def browser_source_factory(data_dir: Path) -> SourceFactory:
    def factory(settings: Settings, marketplace: Marketplace) -> PageSource:
        cache = PageCache(Path(data_dir) / "cache" / marketplace.key, settings.research_cache_hours)
        return AmazonBrowser(marketplace, postcode=settings.research_postcode, delay_seconds=settings.research_delay_seconds,
                             cache=cache, headless=not settings.research_show_browser)
    return factory


class ResearchRunner:
    def __init__(self, db_path: Path, source_factory: SourceFactory, background: bool = True):
        self.db_path = db_path
        self.source_factory = source_factory
        self.background = background
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel: set[int] = set()
        self.current_search_id: int | None = None

    # ------------------------------------------------------------ control
    def start(self, brand: str, *, store_url: str | None = None, reevaluate_rejected: bool = False,
              marketplace: str = "amazon_uk") -> int:
        conn = connect(self.db_path)
        try:
            repo = ResearchRepository(conn)
            settings = ProductService(conn).settings
            brand_row = repo.get_or_create_brand(brand)
            # Search with the brand's saved spelling, so "aero", "AERO" and "Aero" are one brand with one query (F14).
            search_id = repo.create_search(brand_row["id"], brand_row["name"], store_url=store_url, marketplace=marketplace,
                                           reevaluate_rejected=reevaluate_rejected,
                                           criteria_fingerprint=settings.criteria_fingerprint())
            conn.commit()
        finally:
            conn.close()
        log.info("Brand search %s queued for %r", search_id, brand)
        self.wake()
        return search_id

    def resume(self, search_id: int) -> bool:
        conn = connect(self.db_path)
        try:
            repo = ResearchRepository(conn)
            search = repo.get_search(search_id)
            if not search or search["status"] in ("queued", "running", "completed"):
                return False
            repo.update_search(search_id, status="queued", message="Waiting to resume…", error=None)
            conn.commit()
        finally:
            conn.close()
        self._cancel.discard(search_id)
        self.wake()
        return True

    def cancel(self, search_id: int) -> None:
        self._cancel.add(search_id)
        conn = connect(self.db_path)
        try:
            repo = ResearchRepository(conn)
            search = repo.get_search(search_id)
            if search and search["status"] == "queued":
                repo.update_search(search_id, status="cancelled", message="Cancelled before it started.")
                conn.commit()
        finally:
            conn.close()

    def wake(self) -> None:
        if not self.background:
            return
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="brand-research", daemon=True)
                self._thread.start()
        self._wake.set()

    # ------------------------------------------------------------- worker
    def _loop(self) -> None:
        while True:
            self._wake.clear()
            ran = self.run_pending()
            if not ran and not self._wake.wait(timeout=30):
                return  # idle: the thread exits; the next start() creates a new one

    def run_pending(self) -> int:
        """Run every queued search now, in order. Returns how many ran. Used by the thread and by tests."""
        ran = 0
        while True:
            conn = connect(self.db_path)
            try:
                repo = ResearchRepository(conn)
                queued = repo.queued_search_ids()
                if not queued:
                    return ran
                search_id = queued[0]
                # Claim it atomically so the same search can never be run twice at once (FAILURES F13).
                if not conn.execute("UPDATE brand_searches SET status = 'running' WHERE id = ? AND status = 'queued'",
                                    (search_id,)).rowcount:
                    conn.commit()
                    continue
                conn.commit()
                search = repo.get_search(search_id)
                settings = ProductService(conn).settings
                marketplace = get_marketplace(search["marketplace"])
                self.current_search_id = search_id
                source = self.source_factory(settings, marketplace)
                try:
                    BrandResearch(conn, source, marketplace, should_stop=lambda: search_id in self._cancel).run(search_id)
                finally:
                    try:
                        source.close()
                    except Exception:  # noqa: BLE001
                        log.exception("Closing the browser failed")
                    self.current_search_id = None
                    self._cancel.discard(search_id)
                ran += 1
            finally:
                conn.close()
