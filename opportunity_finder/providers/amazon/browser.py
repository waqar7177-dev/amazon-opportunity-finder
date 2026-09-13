"""Polite page collection from Amazon with the user's own browser (Playwright + Edge/Chrome).

Plain HTTP requests receive an AWS WAF challenge instead of content, so a real browser is used.
This module never solves or bypasses a CAPTCHA or bot check: when one appears it raises
CollectionBlocked and the job stops, keeping everything collected so far.

Politeness: one page at a time, a minimum delay with jitter between page loads, limited retries
with exponential back-off when Amazon throttles, and an on-disk cache so the same page is not
fetched twice within the cache window.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .marketplace import Marketplace
from .parsers import classify_page

log = logging.getLogger("opportunity_finder.amazon")


class CollectionBlocked(RuntimeError):
    """Amazon showed a CAPTCHA, bot check or sign-in wall. Stop; do not retry around it."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class PageNotFound(LookupError):
    pass


class FetchFailed(RuntimeError):
    pass


class BrowserUnavailable(RuntimeError):
    pass


@dataclass
class FetchResult:
    url: str
    html: str
    status: int | None
    from_cache: bool = False


class PageSource(Protocol):
    location_confirmed: bool | None

    def fetch(self, url: str, kind: str) -> FetchResult: ...

    def close(self) -> None: ...


class PageCache:
    def __init__(self, folder: Path, max_age_hours: float):
        self.folder = folder
        self.max_age = max_age_hours * 3600

    def _path(self, url: str) -> Path:
        return self.folder / (hashlib.sha1(url.encode()).hexdigest() + ".html.gz")

    def get(self, url: str) -> str | None:
        path = self._path(url)
        if self.max_age <= 0 or not path.exists() or time.time() - path.stat().st_mtime > self.max_age:
            return None
        try:
            return gzip.decompress(path.read_bytes()).decode("utf-8")
        except (OSError, EOFError):
            return None

    def put(self, url: str, html: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self._path(url).write_bytes(gzip.compress(html.encode("utf-8")))


class AmazonBrowser:
    """A PageSource backed by a real browser session."""

    CHANNELS = ("msedge", "chrome", None)  # None = Playwright's own Chromium, if installed

    def __init__(self, marketplace: Marketplace, *, postcode: str, delay_seconds: float, cache: PageCache,
                 headless: bool = True, max_retries: int = 2, sleep: Callable[[float], None] = time.sleep):
        self.marketplace = marketplace
        self.postcode = postcode
        self.delay = max(3.0, float(delay_seconds))
        self.cache = cache
        self.headless = headless
        self.max_retries = max_retries
        self._sleep = sleep
        self._last_load = 0.0
        self._pw = self._browser = self._context = self._page = None
        self.location_confirmed: bool | None = None
        self.pages_loaded = 0

    # ---------------------------------------------------------- lifecycle
    def _start(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
            raise BrowserUnavailable("The Playwright package is not installed. Run run.bat again.") from exc
        self._pw = sync_playwright().start()
        errors = []
        for channel in self.CHANNELS:
            try:
                self._browser = self._pw.chromium.launch(channel=channel, headless=self.headless) if channel \
                    else self._pw.chromium.launch(headless=self.headless)
                log.info("Browser started (%s)", channel or "chromium")
                break
            except Exception as exc:  # noqa: BLE001 - try the next browser
                errors.append(f"{channel or 'chromium'}: {str(exc).splitlines()[0][:120]}")
        if self._browser is None:
            self.close()
            log.error("No browser could be started: %s", " | ".join(errors))
            raise BrowserUnavailable("Brand research needs Microsoft Edge or Google Chrome installed on this computer.")
        self._context = self._browser.new_context(locale=self.marketplace.locale, viewport={"width": 1366, "height": 900})
        self._context.add_cookies(self.marketplace.cookies())
        self._page = self._context.new_page()
        self._set_delivery_location()

    def _throttle(self) -> None:
        wait = self.delay + random.uniform(0, self.delay * 0.6) - (time.monotonic() - self._last_load)
        if wait > 0 and self._last_load:
            self._sleep(wait)
        self._last_load = time.monotonic()

    def _goto(self, url: str) -> tuple[int | None, str]:
        self._throttle()
        response = self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        self._page.wait_for_timeout(1800)
        self.pages_loaded += 1
        return (response.status if response else None), self._page.content()

    def _set_delivery_location(self) -> None:
        """Use the site's own "Deliver to" setting so prices, stock and offers are the UK ones."""
        try:
            status, html = self._goto(self.marketplace.base_url + "/")
            check = classify_page(html, status)
            if check.blocked:
                raise CollectionBlocked(check.kind, check.message)
            self._page.click("#nav-global-location-popover-link", timeout=10_000)
            self._page.wait_for_selector("#GLUXZipUpdateInput", timeout=10_000)
            self._page.fill("#GLUXZipUpdateInput", self.postcode)
            self._page.click("#GLUXZipUpdate", timeout=5_000)
            self._page.wait_for_timeout(2500)
            self._page.reload(wait_until="domcontentloaded")
            label = self._page.inner_text("#glow-ingress-block", timeout=8_000)
            wanted = self.postcode.replace(" ", "").upper()
            self.location_confirmed = wanted in label.replace(" ", "").upper()
        except CollectionBlocked:
            raise
        except Exception as exc:  # noqa: BLE001 - the site layout may change; carry on, but record it
            self.location_confirmed = False
            log.warning("Could not confirm the UK delivery location: %s", str(exc).splitlines()[0][:160])
        log.info("Delivery location confirmed: %s", self.location_confirmed)

    def close(self) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer is not None:
                    closer.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._pw = self._browser = self._context = self._page = None

    # --------------------------------------------------------------- fetch
    def fetch(self, url: str, kind: str) -> FetchResult:
        cached = self.cache.get(url)
        if cached is not None and classify_page(cached).kind == "ok":
            return FetchResult(url, cached, 200, from_cache=True)
        self._start()
        for attempt in range(self.max_retries + 1):
            try:
                status, html = self._goto(url)
            except Exception as exc:  # noqa: BLE001 - network or browser error
                if attempt >= self.max_retries:
                    raise FetchFailed(f"Could not load the page ({str(exc).splitlines()[0][:120]}).") from exc
                self._sleep(self.delay * (2 ** (attempt + 1)))
                continue
            check = classify_page(html, status, self._page.url if self._page else url)
            if check.blocked:
                log.warning("Amazon block detected (%s) on %s page", check.kind, kind)
                raise CollectionBlocked(check.kind, check.message)
            if check.kind == "not_found":
                raise PageNotFound(url)
            if check.kind in ("throttled", "empty"):
                if attempt >= self.max_retries:
                    raise FetchFailed(check.message)
                backoff = self.delay * (3 ** (attempt + 1))
                log.info("Amazon %s on %s page; waiting %.0fs before retry %d", check.kind, kind, backoff, attempt + 1)
                self._sleep(backoff)
                continue
            self.cache.put(url, html)
            return FetchResult(url, html, status)
        raise FetchFailed("Could not load the page.")  # pragma: no cover


def describe_block(kind: str) -> str:
    return {
        "captcha": "Amazon temporarily blocked automated collection (it asked for a CAPTCHA).",
        "challenge": "Amazon temporarily blocked automated collection (bot check page).",
        "signin": "Amazon temporarily blocked automated collection (it asked to sign in).",
    }.get(kind, "Amazon temporarily blocked automated collection.")


def cache_meta(folder: Path) -> dict:
    files = list(folder.glob("*.html.gz")) if folder.exists() else []
    return {"pages": len(files), "bytes": sum(f.stat().st_size for f in files)}


__all__ = ["AmazonBrowser", "PageCache", "PageSource", "FetchResult", "CollectionBlocked", "PageNotFound",
           "FetchFailed", "BrowserUnavailable", "describe_block", "cache_meta", "json"]
