from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LoadResult:
    url: str
    html: str
    status: int = 200
    final_url: str | None = None
    elapsed: float = 0.0
    attempts: int = 1


@dataclass
class ExtractedTable:
    columns: dict[str, list[str]]
    source_url: str | None = None

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
    started_at: str | None = None
    finished_at: str | None = None
    extractor: str | None = None
    loader: str | None = None
    selectors: dict[str, str] = field(default_factory=dict)
    sandpaper_version: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScrapeResult:
    table: ExtractedTable
    provenance: Provenance
    output_path: str | None = None

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
