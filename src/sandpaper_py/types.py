from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LoadResult:
    url: str
    html: str
    status: int = 200
    final_url: Optional[str] = None
    elapsed: float = 0.0
    attempts: int = 1


@dataclass
class ExtractedTable:
    columns: dict[str, list[str]]
    source_url: Optional[str] = None

    def row_count(self) -> int:
        if not self.columns:
            return 0
        return max((len(v) for v in self.columns.values()), default=0)

    def column_names(self) -> list[str]:
        return list(self.columns.keys())

    def records(self) -> list[dict[str, str]]:
        if not self.columns:
            return []
        keys = list(self.columns.keys())
        n = self.row_count()
        rows: list[dict[str, str]] = []
        for i in range(n):
            rows.append({k: self.columns[k][i] if i < len(self.columns[k]) else "" for k in keys})
        return rows


@dataclass
class Provenance:
    source_urls: list[str] = field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    extractor: Optional[str] = None
    loader: Optional[str] = None
    selectors: dict[str, str] = field(default_factory=dict)
    sandpaper_version: Optional[str] = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScrapeResult:
    table: ExtractedTable
    provenance: Provenance
    output_path: Optional[str] = None

    @property
    def rows(self) -> int:
        return self.table.row_count()

    @property
    def columns(self) -> list[str]:
        return self.table.column_names()

    def records(self) -> list[dict[str, str]]:
        return self.table.records()

    def to_pandas(self, typed: bool = False):
        from .exporters.base import normalize_to_dataframe
        from .schema import coerce_dataframe

        if typed:
            return coerce_dataframe(self.table)
        return normalize_to_dataframe(self.table)

    def to_polars(self, typed: bool = False):
        try:
            import polars as pl
        except ImportError as exc:
            raise RuntimeError("to_polars needs polars: pip install polars") from exc
        return pl.from_pandas(self.to_pandas(typed=typed))
