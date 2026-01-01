from __future__ import annotations

import sqlite3
from pathlib import Path

from ..types import ExtractedTable
from .base import normalize_to_dataframe, require_table, resolve_path


class SQLiteExporter:
    name = "sqlite"
    extension = ".db"

    def __init__(
        self,
        table_name: str = "scrape",
        if_exists: str = "replace",
        typed: bool = False,
        drop_empty_columns: bool = False,
        sort_columns: bool = False,
    ):
        if if_exists not in {"replace", "append", "fail"}:
            raise ValueError("if_exists must be replace, append, or fail")
        self.table_name = table_name
        self.if_exists = if_exists
        self.typed = typed
        self.drop_empty_columns = drop_empty_columns
        self.sort_columns = sort_columns

    def export(self, table: ExtractedTable, output_path: str | Path) -> str:
        require_table(table)
        path = resolve_path(output_path, self.extension)
        if self.typed:
            from ..schema import coerce_dataframe

            df = coerce_dataframe(table)
        else:
            df = normalize_to_dataframe(table, self.drop_empty_columns, self.sort_columns)
        with sqlite3.connect(str(path)) as conn:
            df.to_sql(self.table_name, conn, if_exists=self.if_exists, index=False)
        return str(path)
