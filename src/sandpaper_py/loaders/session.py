"""Browser session: a persistent Playwright page with action verbs.

Used by the recipe runner. Unlike PlaywrightLoader (which loads URLs and
returns HTML), a session keeps one page across many actions: goto, fill,
click, wait_for, extract HTML, etc.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Any

from ..exceptions import LoadError
from ..utils import HTMLCache, random_user_agent
from .playwright_loader import LoaderOptions

log = logging.getLogger("sandpaper.session")


class BrowserSession:
    def __init__(self, options: LoaderOptions | None = None):
        self.options = options or LoaderOptions()
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._cache = HTMLCache(self.options.cache_dir, self.options.cache_ttl_seconds)
        self._closed = False

    def __enter__(self) -> BrowserSession:
        self._start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _start(self) -> None:
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise LoadError("", f"playwright not installed: {exc}") from exc

        self._pw = sync_playwright().start()
        last_err: Exception | None = None
        for engine in self.options.engines:
            engine_obj = getattr(self._pw, engine, None)
            if engine_obj is None:
                continue
            try:
                launch_kwargs: dict = {"headless": self.options.headless}
                proxy_url: str | None = None
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

                    def _blocker(route, blocked=blocked):
                        if route.request.resource_type in blocked:
                            route.abort()
                        else:
                            route.continue_()

                    self._context.route("**/*", _blocker)
                self._page = self._context.new_page()
                log.debug("session started: %s ua=%s", engine, ua)
                return
            except Exception as exc:
                last_err = exc
                log.warning("session engine %s failed: %s", engine, exc)
                self._safe_stop()
        raise LoadError("", f"no browser engine could start: {last_err}")

    def _safe_stop(self) -> None:
        for closer in (self._page, self._context, self._browser):
            if closer is not None:
                try:
                    closer.close()
                except Exception:
                    pass
        self._page = None
        self._context = None
        self._browser = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._safe_stop()

    @property
    def page(self):
        if self._page is None:
            self._start()
        return self._page

    @property
    def context(self):
        if self._context is None:
            self._start()
        return self._context

    # ---- action verbs ----

    def goto(self, url: str) -> None:
        self.page.goto(url, timeout=self.options.timeout_ms)
        self.page.wait_for_load_state("networkidle", timeout=self.options.timeout_ms)

    def wait_for_selector(self, selector: str, timeout_ms: int | None = None) -> None:
        self.page.wait_for_selector(selector, timeout=timeout_ms or self.options.timeout_ms)

    def wait_for_load_state(self, state: str = "networkidle") -> None:
        self.page.wait_for_load_state(state, timeout=self.options.timeout_ms)

    def wait(self, ms: int) -> None:
        self.page.wait_for_timeout(int(ms))

    def fill(self, selector: str, value: str) -> None:
        self.page.fill(selector, value, timeout=self.options.timeout_ms)

    def click(self, selector: str) -> None:
        self.page.click(selector, timeout=self.options.timeout_ms)

    def press(self, selector: str, key: str) -> None:
        self.page.press(selector, key, timeout=self.options.timeout_ms)

    def scroll_to_bottom(self, max_scrolls: int | None = None, pause_ms: int | None = None) -> None:
        max_scrolls = max_scrolls if max_scrolls is not None else self.options.max_scrolls
        pause_ms = pause_ms if pause_ms is not None else int(self.options.scroll_pause * 1000)
        previous = 0
        for _ in range(max_scrolls):
            current = self.page.evaluate("() => document.body ? document.body.scrollHeight : 0")
            if current == previous:
                return
            self.page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            self.page.wait_for_timeout(pause_ms)
            previous = current

    def evaluate(self, script: str) -> Any:
        return self.page.evaluate(script)

    def content(self) -> str:
        return self.page.content()

    @property
    def url(self) -> str:
        return self.page.url

    def save_storage_state(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.context.storage_state(path=path)
