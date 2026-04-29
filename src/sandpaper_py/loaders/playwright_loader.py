from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..exceptions import LoadError, RobotsDisallowed
from ..robots import RobotsCache
from ..throttle import RateLimiter
from ..types import LoadResult
from ..utils import HTMLCache, random_user_agent

log = logging.getLogger("sandpaper.loader")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0 Safari/537.36 sandpaper/0.1"
)


@dataclass
class LoaderOptions:
    headless: bool = True
    timeout_ms: int = 60000
    scroll: bool = True
    scroll_pause: float = 1.0
    max_scrolls: int = 30
    wait_for_selector: Optional[str] = None
    extra_wait_ms: int = 0
    user_agent: str = DEFAULT_USER_AGENT
    rotate_user_agents: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    cookies: list[dict] = field(default_factory=list)
    storage_state: Optional[str] = None
    proxy: Optional[str] = None
    proxies: tuple[str, ...] = ()
    retries: int = 2
    retry_backoff: float = 1.5
    rate_per_second: float = 0.0
    random_delay_ms: int = 0
    obey_robots: bool = False
    allow_on_robots_error: bool = False
    cache_dir: Optional[str] = None
    cache_ttl_seconds: int = 0
    block_resources: tuple[str, ...] = ()
    dismiss_overlays: bool = False
    engines: tuple[str, ...] = ("chromium", "firefox", "webkit")


class PlaywrightLoader:
    def __init__(
        self,
        options: Optional[LoaderOptions] = None,
        shared_limiter: Optional[RateLimiter] = None,
    ):
        self.options = options or LoaderOptions()
        self._pw = None
        self._browser = None
        self._context = None
        self._engine_name: Optional[str] = None
        self._lock = threading.Lock()
        self._limiter = shared_limiter or RateLimiter(self.options.rate_per_second)
        self._robots = RobotsCache(
            user_agent=self.options.user_agent,
            enabled=self.options.obey_robots,
            allow_on_error=self.options.allow_on_robots_error,
        )
        self._cache = HTMLCache(self.options.cache_dir, self.options.cache_ttl_seconds)

    def _ensure_browser(self) -> None:
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise LoadError("", f"playwright not installed: {exc}") from exc

        self._pw = sync_playwright().start()
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
                self._browser = engine_obj.launch(**launch_kwargs)
                ua = (
                    random_user_agent()
                    if self.options.rotate_user_agents
                    else self.options.user_agent
                )
                ctx_kwargs: dict = {"user_agent": ua}
                if self.options.storage_state and Path(self.options.storage_state).exists():
                    ctx_kwargs["storage_state"] = self.options.storage_state
                self._context = self._browser.new_context(**ctx_kwargs)
                if self.options.headers:
                    self._context.set_extra_http_headers(self.options.headers)
                if self.options.cookies:
                    self._context.add_cookies(self.options.cookies)
                if self.options.block_resources:
                    blocked = frozenset(self.options.block_resources)

                    def _blocker(route, request, _blocked=blocked):
                        if request.resource_type in _blocked:
                            route.abort()
                        else:
                            route.continue_()

                    self._context.route("**/*", _blocker)
                self._engine_name = engine
                log.debug("started %s with ua=%s", engine, ua)
                return
            except Exception as exc:
                last_err = exc
                log.warning("engine %s failed to start: %s", engine, exc)
                self._safe_stop()
        raise LoadError("", f"no browser engine could start: {last_err}")

    def _safe_stop(self) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                try:
                    closer.close()
                except Exception:
                    pass
        self._context = None
        self._browser = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def close(self) -> None:
        with self._lock:
            self._safe_stop()

    def __enter__(self) -> PlaywrightLoader:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def load(self, url: str) -> LoadResult:
        cached = self._cache.get(url)
        if cached is not None:
            return LoadResult(url=url, html=cached, status=200, final_url=url, attempts=0)

        if not self._robots.allowed(url):
            raise RobotsDisallowed(url)
        crawl_delay = self._robots.crawl_delay(url)
        if crawl_delay > 0:
            time.sleep(crawl_delay)
        if self.options.random_delay_ms:
            time.sleep(random.uniform(0, self.options.random_delay_ms) / 1000.0)
        self._limiter.wait(url)

        with self._lock:
            self._ensure_browser()
            assert self._context is not None
            attempts = 0
            last_err: Optional[Exception] = None
            for attempt in range(1, self.options.retries + 2):
                attempts = attempt
                page = None
                start = time.monotonic()
                try:
                    page = self._context.new_page()
                    response = page.goto(url, timeout=self.options.timeout_ms)
                    page.wait_for_load_state("networkidle", timeout=self.options.timeout_ms)
                    if self.options.wait_for_selector:
                        page.wait_for_selector(
                            self.options.wait_for_selector,
                            timeout=self.options.timeout_ms,
                        )
                    if self.options.extra_wait_ms:
                        page.wait_for_timeout(self.options.extra_wait_ms)
                    if self.options.dismiss_overlays:
                        self._dismiss_overlays(page)
                    if self.options.scroll:
                        self._auto_scroll(page)
                    html = page.content()
                    status = response.status if response else 200
                    final_url = page.url
                    elapsed = time.monotonic() - start
                    self._cache.put(url, html)
                    return LoadResult(
                        url=url,
                        html=html,
                        status=status,
                        final_url=final_url,
                        elapsed=elapsed,
                        attempts=attempt,
                    )
                except Exception as exc:
                    last_err = exc
                    log.warning("attempt %d for %s failed: %s", attempt, url, exc)
                finally:
                    if page is not None:
                        try:
                            page.close()
                        except Exception:
                            pass
                if attempt <= self.options.retries:
                    sleep = self.options.retry_backoff**attempt + random.uniform(0, 0.25)
                    time.sleep(sleep)

        raise LoadError(url, str(last_err) if last_err else "unknown", attempts=attempts)

    def _auto_scroll(self, page) -> None:
        previous = 0
        for _ in range(self.options.max_scrolls):
            current = page.evaluate("() => document.body ? document.body.scrollHeight : 0")
            if current == previous:
                return
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(int(self.options.scroll_pause * 1000))
            previous = current

    def _dismiss_overlays(self, page) -> None:
        try:
            page.evaluate(
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

    def save_storage_state(self, path: str) -> None:
        with self._lock:
            if self._context is None:
                return
            self._context.storage_state(path=path)
