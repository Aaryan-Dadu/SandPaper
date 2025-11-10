from __future__ import annotations

import threading
import time
from collections import defaultdict
from urllib.parse import urlparse


class RateLimiter:
    def __init__(self, requests_per_second: float = 0.0):
        self.min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._last: dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        if self.min_interval <= 0:
            return
        host = urlparse(url).netloc
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last[host]
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last[host] = time.monotonic()
