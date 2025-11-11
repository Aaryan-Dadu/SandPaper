from __future__ import annotations

import logging
import threading
import urllib.robotparser
from urllib.parse import urljoin, urlparse

log = logging.getLogger("sandpaper.robots")


class RobotsCache:
    def __init__(
        self,
        user_agent: str = "sandpaper",
        enabled: bool = False,
        allow_on_error: bool = False,
    ):
        self.user_agent = user_agent
        self.enabled = enabled
        self.allow_on_error = allow_on_error
        self._cache: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._errored: set[str] = set()
        self._lock = threading.Lock()

    def allowed(self, url: str) -> bool:
        if not self.enabled:
            return True
        parsed = urlparse(url)
        if not parsed.netloc:
            return True
        base = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            parser = self._cache.get(base)
            errored = base in self._errored
            if parser is None and not errored:
                parser = urllib.robotparser.RobotFileParser()
                parser.set_url(urljoin(base, "/robots.txt"))
                try:
                    parser.read()
                    self._cache[base] = parser
                except Exception as exc:
                    log.warning("could not read robots.txt for %s: %s", base, exc)
                    self._errored.add(base)
                    parser = None
        if parser is None:
            return self.allow_on_error
        return parser.can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float:
        if not self.enabled:
            return 0.0
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            parser = self._cache.get(base)
        if parser is None:
            return 0.0
        delay = parser.crawl_delay(self.user_agent)
        return float(delay) if delay else 0.0
