from __future__ import annotations

import json
from pathlib import Path

from ..types import ExtractedTable
from ..utils import slugify_key
from .base import (
    atomic_write_path,
    normalize_to_dataframe,
    replace_atomic,
    require_table,
    resolve_path,
)


def _records(
    table: ExtractedTable,
    drop_empty_columns: bool,
    sort_columns: bool,
    normalize_keys: bool,
    null_policy: str = "empty",
) -> list[dict]:
    df = normalize_to_dataframe(
        table,
        drop_empty_columns=drop_empty_columns,
        sort_columns=sort_columns,
    )
    rows = df.to_dict(orient="records")
    if normalize_keys:
        seen: dict[str, int] = {}
        mapping: dict[str, str] = {}
        for col in df.columns:
            base = slugify_key(col)
            count = seen.get(base, 0) + 1
            seen[base] = count
            mapping[col] = base if count == 1 else f"{base}_{count}"
        rows = [{mapping[k]: v for k, v in row.items()} for row in rows]
    if null_policy == "null":
        rows = [
            {k: (None if isinstance(v, str) and not v else v) for k, v in row.items()}
            for row in rows
        ]
    elif null_policy == "skip":
        rows = [
            {k: v for k, v in row.items() if not (isinstance(v, str) and not v)} for row in rows
        ]
    return rows


class JSONExporter:
    name = "json"
    extension = ".json"

    def __init__(
        self,
        encoding: str = "utf-8",
        indent: int = 2,
        sort_keys: bool = False,
        drop_empty_columns: bool = True,
        sort_columns: bool = False,
        normalize_keys: bool = False,
        null_policy: str = "empty",
    ):
        self.encoding = encoding
        self.indent = indent
        self.sort_keys = sort_keys
        self.drop_empty_columns = drop_empty_columns
        self.sort_columns = sort_columns
        self.normalize_keys = normalize_keys
        self.null_policy = null_policy

    def export(self, table: ExtractedTable, output_path: str | Path) -> str:
        require_table(table)
        path = resolve_path(output_path, self.extension)
        records = _records(
            table,
            drop_empty_columns=self.drop_empty_columns,
            sort_columns=self.sort_columns,
            normalize_keys=self.normalize_keys,
            null_policy=self.null_policy,
        )
        tmp = atomic_write_path(path)
        try:
            with open(tmp, "w", encoding=self.encoding) as fh:
                json.dump(
                    records,
                    fh,
                    ensure_ascii=False,
                    indent=self.indent,
                    sort_keys=self.sort_keys,
                )
            replace_atomic(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return str(path)


class JSONLExporter:
    name = "jsonl"
    extension = ".jsonl"

    def __init__(
        self,
        encoding: str = "utf-8",
        sort_keys: bool = False,
        drop_empty_columns: bool = True,
        sort_columns: bool = False,
        normalize_keys: bool = False,
        null_policy: str = "empty",
    ):
        self.encoding = encoding
        self.sort_keys = sort_keys
        self.drop_empty_columns = drop_empty_columns
        self.sort_columns = sort_columns
        self.normalize_keys = normalize_keys
        self.null_policy = null_policy

    def export(self, table: ExtractedTable, output_path: str | Path) -> str:
        require_table(table)
        path = resolve_path(output_path, self.extension)
        records = _records(
            table,
            drop_empty_columns=self.drop_empty_columns,
            sort_columns=self.sort_columns,
            normalize_keys=self.normalize_keys,
            null_policy=self.null_policy,
        )
        tmp = atomic_write_path(path)
        try:
            with open(tmp, "w", encoding=self.encoding) as fh:
                for row in records:
                    fh.write(json.dumps(row, ensure_ascii=False, sort_keys=self.sort_keys))
                    fh.write("\n")
            replace_atomic(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return str(path)
