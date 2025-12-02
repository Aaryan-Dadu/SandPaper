from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional, Protocol

import pandas as pd

from ..exceptions import ExportError
from ..types import ExtractedTable

_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


class Exporter(Protocol):
    name: str
    extension: str

    def export(self, table: ExtractedTable, output_path: str | Path) -> str: ...


def normalize_to_dataframe(
    table: ExtractedTable,
    drop_empty_columns: bool = False,
    sort_columns: bool = False,
) -> pd.DataFrame:
    if not table.columns:
        return pd.DataFrame()
    columns = table.columns
    if drop_empty_columns:
        columns = {k: v for k, v in columns.items() if any(s.strip() for s in v)}
    if not columns:
        return pd.DataFrame()
    max_len = max(len(v) for v in columns.values())
    keys = sorted(columns.keys()) if sort_columns else list(columns.keys())
    padded = {k: list(columns[k]) + [""] * (max_len - len(columns[k])) for k in keys}
    return pd.DataFrame(padded, columns=keys)


def neutralize_formula(value: str) -> str:
    if isinstance(value, str) and value and value[0] in _FORMULA_TRIGGERS:
        return "'" + value
    return value


def safe_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        out[col] = [neutralize_formula(v) if isinstance(v, str) else v for v in out[col]]
    return out


def atomic_write_path(path: Path) -> Path:
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), suffix=".tmp")
    os.close(fd)
    return Path(tmp)


def replace_atomic(tmp: Path, target: Path) -> None:
    os.replace(tmp, target)


def require_table(table: ExtractedTable) -> None:
    if not table.columns or table.row_count() == 0:
        raise ExportError("nothing to export: extracted table is empty")


def resolve_path(output_path: str | Path, default_extension: str) -> Path:
    p = Path(output_path).expanduser()
    if not p.suffix:
        p = p.with_suffix(default_extension)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def maybe_extension(name: str) -> Optional[str]:
    return f".{name}" if name and not name.startswith(".") else name or None
