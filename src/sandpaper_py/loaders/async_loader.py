"""Async Playwright loader.

Built for high-concurrency runs. One browser + one context shared across
all tasks; per-task pages bounded by an asyncio.Semaphore.

Falls back to ``RuntimeError`` when ``playwright.async_api`` is missing
so import-time use stays cheap.
"""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from typing import Optional

from ..exceptions import LoadError, RobotsDisallowed
from ..robots import RobotsCache
from ..types import LoadResult
from ..utils import HTMLCache, random_user_agent
from .playwright_loader import LoaderOptions

log = logging.getLogger("sandpaper.async_loader")


class AsyncPlaywrightLoader:
    """Async counterpart to PlaywrightLoader. Reuses one browser/context.

    Concurrency control is via the caller-supplied semaphore (defaults to
    ``options.retries + 4`` worker pages).
    """

    def __init__(
        self,
        options: Optional[LoaderOptions] = None,
        max_pages: int = 4,
    ):
        self.options = options or LoaderOptions()
        self._pw = None
        self._browser = None
        self._context = None
        self._sem = asyncio.Semaphore(max(1, max_pages))
        self._robots = RobotsCache(
            user_agent=self.options.user_agent,
            enabled=self.options.obey_robots,
            allow_on_error=self.options.allow_on_robots_error,
        )
        self._cache = HTMLCache(self.options.cache_dir, self.options.cache_ttl_seconds)
        self._closed = False

    async def __aenter__(self) -> AsyncPlaywrightLoader:
        await self._ensure_browser()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _ensure_browser(self) -> None:
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise LoadError("", f"playwright not installed: {exc}") from exc

        self._pw = await async_playwright().start()
        last_err: Optional[Exception] = None
        for engine in self.options.engines:
            engine_obj = getattr(self._pw, engine, None)
            if engine_obj is None:
                continue
            try:
                launch_kwargs: dict = {"headless": self.options.headless}
                proxy_url: Optional[str] = None
                if self.options.proxies:
                    proxy_url = random.choice(self.options.proxies)
                elif self.options.proxy:
                    proxy_url = self.options.proxy
                if proxy_url:
                    launch_kwargs["proxy"] = {"server": proxy_url}
                self._browser = await engine_obj.launch(**launch_kwargs)
                ua = (
                    random_user_agent()
                    if self.options.rotate_user_agents
                    else self.options.user_agent
                )
                ctx_kwargs: dict = {"user_agent": ua}
                if self.options.storage_state and Path(self.options.storage_state).exists():
                    ctx_kwargs["storage_state"] = self.options.storage_state
                self._context = await self._browser.new_context(**ctx_kwargs)
                if self.options.headers:
                    await self._context.set_extra_http_headers(self.options.headers)
                if self.options.cookies:
                    await self._context.add_cookies(self.options.cookies)
                if self.options.block_resources:
                    blocked = frozenset(self.options.block_resources)

                    async def _blocker(route, blocked=blocked):
                        if route.request.resource_type in blocked:
                            await route.abort()
                        else:
                            await route.continue_()

                    await self._context.route("**/*", _blocker)
                log.debug("async loader started: %s ua=%s", engine, ua)
                return
            except Exception as exc:
                last_err = exc
                log.warning("async engine %s failed to start: %s", engine, exc)
                await self._safe_stop()
        raise LoadError("", f"no async browser engine could start: {last_err}")

    async def _safe_stop(self) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:
                    pass
        self._context = None
        self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._safe_stop()

    async def load(self, url: str) -> LoadResult:
        cached = self._cache.get(url)
        if cached is not None:
            return LoadResult(url=url, html=cached, status=200, final_url=url, attempts=0)

        if not self._robots.allowed(url):
            raise RobotsDisallowed(url)
        crawl_delay = self._robots.crawl_delay(url)
        if crawl_delay > 0:
            await asyncio.sleep(crawl_delay)
        if self.options.random_delay_ms:
            await asyncio.sleep(random.uniform(0, self.options.random_delay_ms) / 1000.0)

        await self._ensure_browser()
        assert self._context is not None
        attempts = 0
        last_err: Optional[Exception] = None

        async with self._sem:
            for attempt in range(1, self.options.retries + 2):
                attempts = attempt
                page = None
                try:
                    page = await self._context.new_page()
                    response = await page.goto(url, timeout=self.options.timeout_ms)
                    await page.wait_for_load_state("networkidle", timeout=self.options.timeout_ms)
                    if self.options.wait_for_selector:
                        await page.wait_for_selector(
                            self.options.wait_for_selector,
                            timeout=self.options.timeout_ms,
                        )
                    if self.options.extra_wait_ms:
                        await page.wait_for_timeout(self.options.extra_wait_ms)
                    if self.options.dismiss_overlays:
                        await self._dismiss_overlays(page)
                    if self.options.scroll:
                        await self._auto_scroll(page)
                    html = await page.content()
                    status = response.status if response else 200
                    final_url = page.url
                    self._cache.put(url, html)
                    return LoadResult(
                        url=url,
                        html=html,
                        status=status,
                        final_url=final_url,
                        attempts=attempt,
                    )
                except Exception as exc:
                    last_err = exc
                    log.warning("async attempt %d for %s failed: %s", attempt, url, exc)
                finally:
                    if page is not None:
                        try:
                            await page.close()
                        except Exception:
                            pass
                if attempt <= self.options.retries:
                    sleep_for = self.options.retry_backoff**attempt + random.uniform(0, 0.25)
                    await asyncio.sleep(sleep_for)
        raise LoadError(url, str(last_err) if last_err else "unknown", attempts=attempts)

    async def _auto_scroll(self, page) -> None:
        previous = 0
        for _ in range(self.options.max_scrolls):
            current = await page.evaluate("() => document.body ? document.body.scrollHeight : 0")
            if current == previous:
                return
            await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(int(self.options.scroll_pause * 1000))
            previous = current

    async def _dismiss_overlays(self, page) -> None:
        try:
            await page.evaluate(
                """
                () => {
                  const re = /(cookie|consent|gdpr|popup|modal|overlay|newsletter|subscribe)/i;
                  document.querySelectorAll('div, section, aside').forEach(el => {
                    const cls = el.className || '';
                    const id = el.id || '';
                    if ((typeof cls === 'string' && re.test(cls)) || re.test(id)) {
                      const cs = getComputedStyle(el);
                      if (cs.position === 'fixed' || cs.position === 'sticky') {
                        el.style.display = 'none';
                      }
                    }
                  });
                  document.querySelectorAll('button, [role="button"]').forEach(btn => {
                    const t = (btn.textContent || '').trim().toLowerCase();
                    if (/^(accept|agree|allow all|got it|i accept)$/i.test(t)) {
                      try { btn.click(); } catch (e) {}
                    }
                  });
                }
                """
            )
        except Exception:
            pass
