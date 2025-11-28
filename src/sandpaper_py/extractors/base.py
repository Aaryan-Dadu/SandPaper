from __future__ import annotations

from typing import Protocol

from ..types import ExtractedTable


class Extractor(Protocol):
    name: str

    def extract(self, html: str, source_url: str | None = None) -> ExtractedTable: ...
