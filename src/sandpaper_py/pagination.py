from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .exceptions import ConfigError


def expand_template(template: str, pages: Iterable[int]) -> list[str]:
    if "{page}" not in template:
        raise ConfigError("template must contain {page}")
    return [template.replace("{page}", str(p)) for p in pages]


def detect_next_link(html: str, base_url: str) -> str | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")

    link = soup.find("link", attrs={"rel": "next"})
    if isinstance(link, Tag) and link.get("href"):
        return urljoin(base_url, str(link["href"]))

    a = soup.find("a", attrs={"rel": "next"})
    if isinstance(a, Tag) and a.get("href"):
        return urljoin(base_url, str(a["href"]))

    text_patterns = re.compile(r"^(next|next\s+page|next\s*&raquo;|»|>)$", re.IGNORECASE)
    for anchor in soup.find_all("a", href=True):
        text = anchor.get_text(strip=True)
        if text and text_patterns.match(text):
            return urljoin(base_url, anchor["href"])
        if anchor.get("aria-label", "").lower() in {"next", "next page"}:
            return urljoin(base_url, anchor["href"])
        classes = " ".join(anchor.get("class", []))
        if re.search(r"\b(next|pagination__next|page-next)\b", classes, re.IGNORECASE):
            return urljoin(base_url, anchor["href"])

    return None


def is_same_origin(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.scheme, pa.netloc) == (pb.scheme, pb.netloc)
