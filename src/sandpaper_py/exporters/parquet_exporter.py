from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..exceptions import ExportError
from ..types import ExtractedTable
from .base import (
    atomic_write_path,
    normalize_to_dataframe,
    replace_atomic,
    require_table,
    resolve_path,
)


class ParquetExporter:
    name = "parquet"
    extension = ".parquet"

    def __init__(
        self,
        compression: Literal["snappy", "gzip", "brotli", "lz4", "zstd"] | None = "snappy",
        typed: bool = False,
        drop_empty_columns: bool = False,
        sort_columns: bool = False,
    ):
        self.compression = compression
        self.typed = typed
        self.drop_empty_columns = drop_empty_columns
        self.sort_columns = sort_columns

    def export(self, table: ExtractedTable, output_path: str | Path) -> str:
        require_table(table)
        try:
            import pyarrow  # noqa: F401
        except ImportError as exc:
            raise ExportError(
                "parquet export needs pyarrow: pip install 'sandpaper-py[parquet]'"
            ) from exc
        path = resolve_path(output_path, self.extension)
        if self.typed:
            from ..schema import coerce_dataframe

            df = coerce_dataframe(table)
        else:
            df = normalize_to_dataframe(table, self.drop_empty_columns, self.sort_columns)
        tmp = atomic_write_path(path)
        try:
            df.to_parquet(tmp, index=False, compression=self.compression, engine="pyarrow")
            replace_atomic(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return str(path)
