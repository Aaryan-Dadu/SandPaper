"""Record-aware heuristic extractor.

The previous version grouped text by (tag, class) flatly across the DOM,
which misaligned columns when group cardinalities differed. This version
finds the repeating sibling container that holds the records, then pulls
fields out of each record. HTML <table> elements are handled directly.
A legacy flat fallback runs when no structure is detectable.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, Optional

from bs4 import BeautifulSoup, NavigableString, Tag

from ..exceptions import ExtractionError
from ..types import ExtractedTable

SKIP_TAGS = {
    "script",
    "style",
    "header",
    "footer",
    "nav",
    "noscript",
    "svg",
    "iframe",
    "form",
    "aside",
}
INLINE_LEAFISH = {
    "a",
    "span",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "li",
    "td",
    "th",
    "label",
    "strong",
    "em",
    "small",
    "i",
    "b",
    "abbr",
    "time",
}

DEFAULT_SKIP_CLASS_KEYWORDS = (
    "nav",
    "menu",
    "footer",
    "header",
    "sidebar",
    "breadcrumb",
    "cookie",
    "banner",
    "subscribe",
    "newsletter",
    "social",
    "popup",
    "modal",
    "overlay",
    "advert",
    "promo",
    "skip-link",
)

_WHITESPACE = re.compile(r"\s+")


def _normalized(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _has_class(tag: Tag) -> bool:
    return bool(tag.get("class"))


def _classes(tag: Tag) -> tuple[str, ...]:
    return tuple(tag.get("class", []) or [])


def _signature(tag: Tag) -> tuple[str, tuple[str, ...]]:
    return tag.name, _classes(tag)


def _best_class_name(tag: Tag) -> Optional[str]:
    classes = _classes(tag)
    if not classes:
        return None
    return max(classes, key=len)


def _field_key(tag: Tag) -> str:
    name = _best_class_name(tag)
    if name:
        return name
    return tag.name


def _own_text(tag: Tag) -> str:
    """Text that belongs to this tag, only when this tag is a true leaf.

    A tag is a leaf when it has no element children that themselves carry
    text. A wrapper around a single text-bearing child returns empty so
    the inner element gets credit. This stops `<a>` and `<h2>` from both
    publishing the same value.
    """
    text_parts: list[str] = []
    for child in tag.children:
        if isinstance(child, NavigableString):
            piece = str(child)
            if piece.strip():
                text_parts.append(piece)
        elif isinstance(child, Tag):
            if child.name in SKIP_TAGS:
                continue
            inner = child.get_text(strip=True)
            if inner:
                return ""
    return _normalized("".join(text_parts))


class HeuristicExtractor:
    name = "heuristic"

    def __init__(
        self,
        threshold: int = 10,
        parser: str = "lxml",
        min_text_length: int = 1,
        max_text_length: int = 4000,
        skip_class_keywords: Optional[Iterable[str]] = None,
        near_dup_ratio: float = 0.85,
        prefer_records: bool = True,
        max_fields_per_record: int = 30,
    ):
        if threshold < 1:
            raise ExtractionError(f"threshold must be >= 1, got {threshold}")
        if min_text_length < 0:
            raise ExtractionError("min_text_length must be >= 0")
        if max_text_length and max_text_length < min_text_length:
            raise ExtractionError("max_text_length must be >= min_text_length")
        if not 0.0 <= near_dup_ratio <= 1.0:
            raise ExtractionError("near_dup_ratio must be between 0 and 1")
        self.threshold = threshold
        self.parser = parser
        self.min_text_length = min_text_length
        self.max_text_length = max_text_length
        self.near_dup_ratio = near_dup_ratio
        self.prefer_records = prefer_records
        self.max_fields_per_record = max_fields_per_record
        keywords = (
            tuple(skip_class_keywords)
            if skip_class_keywords is not None
            else DEFAULT_SKIP_CLASS_KEYWORDS
        )
        self._skip_pattern = (
            re.compile(
                r"(?:^|[\s_-])(" + "|".join(re.escape(k) for k in keywords) + r")(?:$|[\s_-])", re.I
            )
            if keywords
            else None
        )

    def extract(self, html: str, source_url: Optional[str] = None) -> ExtractedTable:
        if not html:
            return ExtractedTable(columns={}, source_url=source_url)
        try:
            soup = BeautifulSoup(html, self.parser)
        except Exception as exc:
            raise ExtractionError(f"failed to parse html: {exc}") from exc

        body = soup.find("body") or soup
        self._strip_noise(body)

        if self.prefer_records:
            table_cols = self._extract_html_tables(body)
            if table_cols and self._row_count(table_cols) >= self.threshold:
                return ExtractedTable(
                    columns=self._post_clean(table_cols),
                    source_url=source_url,
                )

            record_cols = self._extract_record_set(body)
            if record_cols and self._row_count(record_cols) >= self.threshold:
                return ExtractedTable(
                    columns=self._post_clean(record_cols),
                    source_url=source_url,
                )

        return ExtractedTable(
            columns=self._legacy_extract(body),
            source_url=source_url,
        )

    # ------------------------------------------------------------------ helpers

    def _row_count(self, columns: dict[str, list[str]]) -> int:
        if not columns:
            return 0
        return max(len(v) for v in columns.values())

    def _strip_noise(self, body: Tag) -> None:
        for tag in list(body.find_all(SKIP_TAGS)):
            if tag.attrs is None:
                continue
            tag.decompose()
        if self._skip_pattern is None:
            return
        for tag in list(body.find_all(True)):
            if tag.attrs is None or tag.parent is None:
                continue
            classes = " ".join(tag.get("class", []) or [])
            ident = tag.get("id", "") or ""
            role = tag.get("role", "") or ""
            label = tag.get("aria-label", "") or ""
            for hay in (classes, ident, role, label):
                if hay and self._skip_pattern.search(hay):
                    tag.decompose()
                    break

    # --- table extraction --------------------------------------------------

    def _extract_html_tables(self, body: Tag) -> Optional[dict[str, list[str]]]:
        best: Optional[Tag] = None
        best_rows = 0
        for table in body.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) > best_rows:
                best, best_rows = table, len(rows)
        if best is None or best_rows < max(2, self.threshold // 2):
            return None
        rows = best.find_all("tr")
        header_cells = rows[0].find_all(["th", "td"])
        headers: list[str] = []
        seen: dict[str, int] = {}
        for cell in header_cells:
            text = _normalized(cell.get_text(" ", strip=True)) or "column"
            base = text
            count = seen.get(base, 0) + 1
            seen[base] = count
            headers.append(base if count == 1 else f"{base}_{count}")

        body_rows = rows[1:] if header_cells and rows[0].find("th") else rows
        if not body_rows:
            return None

        if not headers or all(not h.strip() for h in headers):
            max_cells = max(len(r.find_all(["td", "th"])) for r in body_rows)
            headers = [f"col_{i + 1}" for i in range(max_cells)]

        columns: dict[str, list[str]] = {h: [] for h in headers}
        for row in body_rows:
            cells = row.find_all(["td", "th"])
            for index, header in enumerate(headers):
                text = (
                    _normalized(cells[index].get_text(" ", strip=True))
                    if index < len(cells)
                    else ""
                )
                columns[header].append(text)
        return columns

    # --- record-set extraction ---------------------------------------------

    def _candidate_score(self, parent: Tag, sig, members: list[Tag]) -> float:
        tag_name, classes = sig
        # Prefer class-bearing siblings; require classes for div/span groups
        class_signal = 0.0 if classes else (-3.0 if tag_name in {"div", "span"} else -1.0)
        text_sizes = [len(m.get_text(strip=True)) for m in members]
        avg_text = sum(text_sizes) / len(text_sizes) if text_sizes else 0.0
        if avg_text < 8:
            return -1.0
        # Penalize parents whose other children are heterogeneous noise
        siblings_total = sum(1 for c in parent.children if isinstance(c, Tag))
        homogeneity = len(members) / max(siblings_total, 1)
        return (
            len(members) * (1.0 + min(avg_text, 1500) / 1500.0) * (0.4 + 0.6 * homogeneity)
            + class_signal
        )

    def _find_best_record_set(self, body: Tag) -> Optional[tuple[Tag, list[Tag]]]:
        best_score = -1.0
        best: Optional[tuple[Tag, list[Tag]]] = None
        candidates = [body, *body.find_all(True)]
        for parent in candidates:
            if parent.name in SKIP_TAGS:
                continue
            groups: dict[Any, list[Tag]] = defaultdict(list)
            for child in parent.find_all(recursive=False):
                if not isinstance(child, Tag) or child.name in SKIP_TAGS:
                    continue
                groups[_signature(child)].append(child)
            for sig, members in groups.items():
                if len(members) < self.threshold:
                    continue
                score = self._candidate_score(parent, sig, members)
                if score > best_score:
                    best_score = score
                    best = (parent, members)
        return best

    def _extract_record(self, container: Tag) -> dict[str, str]:
        fields: dict[str, str] = {}
        if self._skip_pattern is not None:
            classes = " ".join(container.get("class", []) or [])
            if self._skip_pattern.search(classes):
                return fields
        for tag in container.find_all(True):
            if tag.name in SKIP_TAGS:
                continue
            text = _own_text(tag)
            if not text:
                continue
            if len(text) < self.min_text_length:
                continue
            if self.max_text_length and len(text) > self.max_text_length:
                continue
            key = _field_key(tag)
            if key in fields:
                continue
            fields[key] = text
            if len(fields) >= self.max_fields_per_record:
                break
        return fields

    def _extract_record_set(self, body: Tag) -> Optional[dict[str, list[str]]]:
        best = self._find_best_record_set(body)
        if best is None:
            return None
        _, members = best
        records = [self._extract_record(m) for m in members]
        records = [r for r in records if r]
        if len(records) < self.threshold:
            return None

        columns: dict[str, list[str]] = {}
        for record in records:
            for key in record:
                columns.setdefault(key, [])
        for record in records:
            for key in columns:
                columns[key].append(record.get(key, ""))
        return columns

    # --- legacy fallback ---------------------------------------------------

    def _legacy_extract(self, body: Tag) -> dict[str, list[str]]:
        data: dict[str, list[str]] = {}
        for tag in body.find_all(True):
            if tag.name in SKIP_TAGS:
                continue
            text = _own_text(tag)
            if not text:
                continue
            if len(text) < self.min_text_length:
                continue
            if self.max_text_length and len(text) > self.max_text_length:
                continue
            key = _field_key(tag)
            data.setdefault(key, []).append(text)
        return self._post_filter_legacy(data)

    def _post_filter_legacy(self, data: dict[str, list[str]]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for key, values in data.items():
            if len(values) < self.threshold:
                continue
            unique = set(values)
            if len(unique) <= 1:
                continue
            if len(unique) / len(values) < (1.0 - self.near_dup_ratio):
                continue
            out[key] = values
        return out

    # --- post-clean shared by record-set and table paths ------------------

    def _post_clean(self, columns: dict[str, list[str]]) -> dict[str, list[str]]:
        if not columns:
            return columns
        target_len = self._row_count(columns)
        normalized = {k: list(v) + [""] * (target_len - len(v)) for k, v in columns.items()}
        # Drop columns that are all empty
        normalized = {k: v for k, v in normalized.items() if any(s.strip() for s in v)}
        if not normalized:
            return normalized
        # Drop columns where every value is identical (no information)
        normalized = {k: v for k, v in normalized.items() if len(set(v)) > 1}
        if not normalized:
            return normalized
        # Merge columns whose value sequences are identical (keep most descriptive key)
        seen: dict[tuple[str, ...], str] = {}
        ordered_keys = list(normalized.keys())
        for key in ordered_keys:
            sig = tuple(normalized[key])
            existing = seen.get(sig)
            if existing is None:
                seen[sig] = key
                continue
            # Keep the more descriptive key (longer wins)
            keeper = key if len(key) > len(existing) else existing
            drop = existing if keeper is key else key
            seen[sig] = keeper
            normalized.pop(drop, None)
        return normalized
