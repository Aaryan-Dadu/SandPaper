from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from ..exceptions import ExtractionError
from ..types import ExtractedTable

ATTR_SUFFIX = re.compile(r"^(.*?)@([A-Za-z_-][A-Za-z0-9_-]*)$")


def _parse_selector(spec: str) -> tuple[str, Optional[str]]:
    """Split `selector@attr` syntax into (selector, attribute).

    Returns (spec, None) when the spec has no trailing @attr suffix. The regex
    requires the attribute to match a strict identifier shape so that CSS
    attribute selectors like `a[href*="@example.com"]` are not misparsed.
    """
    m = ATTR_SUFFIX.match(spec)
    if m:
        sel = m.group(1).strip()
        attr = m.group(2)
        if sel:
            return sel, attr
    return spec, None


class SelectorExtractor:
    name = "selector"

    def __init__(
        self,
        selectors: dict[str, str],
        attribute: Optional[str] = None,
        parser: str = "lxml",
        row_selector: Optional[str] = None,
    ):
        if not selectors:
            raise ExtractionError("selectors dict is empty")
        self.parser = parser
        self.row_selector = row_selector
        self.default_attribute = attribute
        self._compiled: dict[str, tuple[str, Optional[str]]] = {}
        for column, spec in selectors.items():
            sel, attr = _parse_selector(spec)
            self._compiled[column] = (sel, attr or attribute)
        self.selectors = selectors

    def extract(self, html: str, source_url: Optional[str] = None) -> ExtractedTable:
        if not html:
            return ExtractedTable(columns={}, source_url=source_url)
        try:
            soup = BeautifulSoup(html, self.parser)
        except Exception as exc:
            raise ExtractionError(f"failed to parse html: {exc}") from exc

        if self.row_selector:
            return self._extract_row_scoped(soup, source_url)
        return self._extract_flat(soup, source_url)

    # ----------------------------------------------------------------- flat

    def _extract_flat(self, soup, source_url: Optional[str]) -> ExtractedTable:
        columns: dict[str, list[str]] = {}
        for column, (selector, attr) in self._compiled.items():
            try:
                elements = soup.select(selector)
            except Exception as exc:
                raise ExtractionError(f"bad selector {selector!r}: {exc}") from exc
            columns[column] = [self._read_value(el, attr) for el in elements]
        return ExtractedTable(columns=columns, source_url=source_url)

    # ----------------------------------------------------------- row-scoped

    def _extract_row_scoped(self, soup, source_url: Optional[str]) -> ExtractedTable:
        try:
            rows = soup.select(self.row_selector)
        except Exception as exc:
            raise ExtractionError(f"bad row_selector {self.row_selector!r}: {exc}") from exc
        columns: dict[str, list[str]] = {col: [] for col in self._compiled}
        for row in rows:
            for column, (selector, attr) in self._compiled.items():
                try:
                    el = row.select_one(selector)
                except Exception as exc:
                    raise ExtractionError(
                        f"bad selector {selector!r} for column {column!r}: {exc}"
                    ) from exc
                columns[column].append(self._read_value(el, attr) if el else "")
        return ExtractedTable(columns=columns, source_url=source_url)

    # ----------------------------------------------------------- shared

    def _read_value(self, el, attr: Optional[str]) -> str:
        if el is None:
            return ""
        if attr:
            val = el.get(attr)
            if val is None:
                return ""
            return val if isinstance(val, str) else " ".join(val)
        return el.get_text(strip=True)

    def extract_one(self, html: str, source_url: Optional[str] = None) -> dict[str, str]:
        """Single-record convenience: take the first match per selector.

        Used by the follow pipeline to reduce a detail page to one row.
        """
        if not html:
            return dict.fromkeys(self._compiled, "")
        try:
            soup = BeautifulSoup(html, self.parser)
        except Exception as exc:
            raise ExtractionError(f"failed to parse html: {exc}") from exc
        record: dict[str, str] = {}
        for column, (selector, attr) in self._compiled.items():
            try:
                el = soup.select_one(selector)
            except Exception as exc:
                raise ExtractionError(f"bad selector {selector!r}: {exc}") from exc
            record[column] = self._read_value(el, attr)
        return record
