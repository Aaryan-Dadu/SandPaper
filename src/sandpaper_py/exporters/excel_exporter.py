from __future__ import annotations

from pathlib import Path

from ..exceptions import ExportError
from ..types import ExtractedTable
from .base import (
    atomic_write_path,
    normalize_to_dataframe,
    replace_atomic,
    require_table,
    resolve_path,
)


class ExcelExporter:
    name = "excel"
    extension = ".xlsx"

    def __init__(
        self,
        sheet_name: str = "data",
        typed: bool = False,
        drop_empty_columns: bool = False,
        sort_columns: bool = False,
    ):
        self.sheet_name = sheet_name
        self.typed = typed
        self.drop_empty_columns = drop_empty_columns
        self.sort_columns = sort_columns

    def export(self, table: ExtractedTable, output_path: str | Path) -> str:
        require_table(table)
        try:
            import openpyxl  # noqa: F401
        except ImportError as exc:
            raise ExportError(
                "excel export needs openpyxl: pip install 'sandpaper-py[excel]'"
            ) from exc
        path = resolve_path(output_path, self.extension)
        if self.typed:
            from ..schema import coerce_dataframe

            df = coerce_dataframe(table)
        else:
            df = normalize_to_dataframe(table, self.drop_empty_columns, self.sort_columns)
        tmp = atomic_write_path(path)
        try:
            df.to_excel(tmp, index=False, sheet_name=self.sheet_name, engine="openpyxl")
            replace_atomic(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return str(path)
