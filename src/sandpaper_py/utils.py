from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .exceptions import ConfigError

log = logging.getLogger("sandpaper")


def setup_logging(level: str = "INFO") -> None:
    import logging as _logging

    from rich.logging import RichHandler

    _logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False, markup=True)],
    )


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str, fallback: str = "output") -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", name).strip(" .")
    if not cleaned or cleaned.upper() in _RESERVED_FILENAMES:
        return fallback
    if len(cleaned) > 200:
        cleaned = cleaned[:200]
    return cleaned


def get_site_name(url: str) -> str:
    if not url or not is_valid_url(url):
        return "site"
    try:
        import tldextract

        parts = tldextract.extract(url)
        if parts.domain:
            return parts.domain
    except Exception:
        pass
    host = urlparse(url).netloc.split(":")[0]
    if not host:
        return "site"
    chunks = host.split(".")
    _SECOND_LEVEL = {"co", "com", "net", "org", "gov", "edu", "ac"}
    if len(chunks) >= 3 and chunks[-2] in _SECOND_LEVEL:
        return chunks[-3]
    if len(chunks) >= 2:
        return chunks[-2]
    return chunks[0] or "site"


def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def ensure_output_dir(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    parent = p if p.suffix == "" else p.parent
    parent.mkdir(parents=True, exist_ok=True)
    return p


def parse_page_range(spec: str, max_pages: int = 10000) -> list[int]:
    spec = spec.strip()
    if not spec:
        raise ConfigError("empty page range")
    pages: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo_s, hi_s = chunk.split("-", 1)
            try:
                lo, hi = int(lo_s), int(hi_s)
            except ValueError as exc:
                raise ConfigError(f"invalid page range chunk {chunk!r}: {exc}") from exc
            if lo < 1 or hi < 1:
                raise ConfigError(f"page numbers must be >= 1, got {chunk}")
            if lo > hi:
                raise ConfigError(f"invalid range: {chunk}")
            if hi - lo + 1 > max_pages:
                raise ConfigError(
                    f"range {chunk} expands to {hi - lo + 1} pages, "
                    f"above the safety cap of {max_pages}"
                )
            pages.extend(range(lo, hi + 1))
        else:
            try:
                n = int(chunk)
            except ValueError as exc:
                raise ConfigError(f"invalid page number {chunk!r}: {exc}") from exc
            if n < 1:
                raise ConfigError(f"page number must be >= 1, got {n}")
            pages.append(n)
        if len(pages) > max_pages:
            raise ConfigError(
                f"page list exceeds safety cap of {max_pages}; "
                "raise --max-pages-limit or split the run"
            )
    if not pages:
        raise ConfigError("empty page range")
    return pages


def merge_columns(target: dict[str, list[str]], incoming: dict[str, list[str]]) -> None:
    for key, values in incoming.items():
        if key in target:
            target[key].extend(values)
        else:
            target[key] = list(values)


def package_version() -> Optional[str]:
    try:
        from importlib.metadata import version

        return version("sandpaper-py")
    except Exception:
        return None


_USER_AGENTS = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36 Edg/120.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
)


def random_user_agent() -> str:
    import random

    return random.choice(_USER_AGENTS)


def slugify_key(key: str) -> str:
    out = re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").lower()
    return out or "field"


class HTMLCache:
    def __init__(self, root: Optional[str], ttl_seconds: int = 0):
        self.root = Path(root).expanduser() if root else None
        self.ttl_seconds = ttl_seconds
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Optional[Path]:
        if self.root is None:
            return None
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.html"

    def get(self, url: str) -> Optional[str]:
        path = self._path(url)
        if path is None or not path.exists():
            return None
        if self.ttl_seconds > 0:
            age = time.time() - path.stat().st_mtime
            if age > self.ttl_seconds:
                return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def put(self, url: str, html: str) -> None:
        path = self._path(url)
        if path is None:
            return
        try:
            path.write_text(html, encoding="utf-8")
        except OSError:
            log.debug("cache write failed for %s", url)
