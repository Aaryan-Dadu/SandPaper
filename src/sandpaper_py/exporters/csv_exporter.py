from __future__ import annotations

import csv
from pathlib import Path

from ..types import ExtractedTable
from .base import (
    atomic_write_path,
    normalize_to_dataframe,
    replace_atomic,
    require_table,
    resolve_path,
    safe_dataframe,
)


class CSVExporter:
    name = "csv"
    extension = ".csv"

    def __init__(
        self,
        encoding: str = "utf-8",
        quoting: int = csv.QUOTE_MINIMAL,
        safe: bool = False,
        drop_empty_columns: bool = False,
        sort_columns: bool = False,
        typed: bool = False,
    ):
        self.encoding = encoding
        self.quoting = quoting
        self.safe = safe
        self.drop_empty_columns = drop_empty_columns
        self.sort_columns = sort_columns
        self.typed = typed

    def export(self, table: ExtractedTable, output_path: str | Path) -> str:
        require_table(table)
        path = resolve_path(output_path, self.extension)
        if self.typed:
            from ..schema import coerce_dataframe

            df = coerce_dataframe(table)
        else:
            df = normalize_to_dataframe(
                table,
                drop_empty_columns=self.drop_empty_columns,
                sort_columns=self.sort_columns,
            )
        if df.empty:
            raise ValueError("after filtering, no columns remain to write")
        if self.safe:
            df = safe_dataframe(df)
        tmp = atomic_write_path(path)
        try:
            df.to_csv(tmp, index=False, encoding=self.encoding, quoting=self.quoting)
            replace_atomic(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return str(path)
