from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from .types import ExtractedTable

_CURRENCY_RE = re.compile(r"^\s*[\$€£¥₹]\s*([\d,]+(?:\.\d+)?)\s*$")
_NUMBER_RE = re.compile(r"^-?\d+(?:[\.,]\d+)?$")
_INT_RE = re.compile(r"^-?\d{1,15}$")
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%d %B %Y",
    "%B %d, %Y",
    "%d %b %Y",
)


@dataclass
class ColumnStats:
    name: str
    inferred_type: str = "string"
    non_empty: int = 0
    empty: int = 0
    unique: int = 0
    sample: list[str] = field(default_factory=list)


@dataclass
class TableStats:
    rows: int
    columns: list[ColumnStats]


def _try_parse_date(value: str) -> Optional[datetime]:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _classify_value(value: str) -> str:
    s = value.strip()
    if not s:
        return "empty"
    if _INT_RE.match(s):
        return "integer"
    if _NUMBER_RE.match(s):
        return "number"
    if _CURRENCY_RE.match(s):
        return "currency"
    if _try_parse_date(s) is not None:
        return "date"
    if s.lower() in {"true", "false", "yes", "no"}:
        return "boolean"
    return "string"


def infer_column_type(values: list[str]) -> str:
    counts: dict[str, int] = {}
    for v in values:
        kind = _classify_value(v)
        counts[kind] = counts.get(kind, 0) + 1
    counts.pop("empty", None)
    if not counts:
        return "string"
    total = sum(counts.values())
    best, count = max(counts.items(), key=lambda kv: kv[1])
    if count / total < 0.8:
        return "string"
    return best


def summarize(table: ExtractedTable) -> TableStats:
    cols: list[ColumnStats] = []
    for name, values in table.columns.items():
        non_empty = sum(1 for v in values if v.strip())
        empty = len(values) - non_empty
        unique = len(set(values))
        sample = [v for v in values if v.strip()][:3]
        cols.append(
            ColumnStats(
                name=name,
                inferred_type=infer_column_type(values),
                non_empty=non_empty,
                empty=empty,
                unique=unique,
                sample=sample,
            )
        )
    return TableStats(rows=table.row_count(), columns=cols)


def coerce_dataframe(table: ExtractedTable) -> pd.DataFrame:
    if not table.columns:
        return pd.DataFrame()
    max_len = max(len(v) for v in table.columns.values())
    data: dict[str, Any] = {}
    for name, values in table.columns.items():
        padded = list(values) + [""] * (max_len - len(values))
        kind = infer_column_type(padded)
        if kind == "integer":
            data[name] = pd.to_numeric(pd.Series(padded), errors="coerce").astype("Int64")
        elif kind in {"number", "currency"}:
            cleaned = [_strip_currency(v) for v in padded]
            data[name] = pd.to_numeric(pd.Series(cleaned), errors="coerce")
        elif kind == "date":
            data[name] = pd.to_datetime(pd.Series(padded), errors="coerce")
        elif kind == "boolean":
            data[name] = pd.Series(padded).map(_to_bool)
        else:
            data[name] = padded
    return pd.DataFrame(data, columns=list(table.columns.keys()))


def _strip_currency(value: str) -> str:
    m = _CURRENCY_RE.match(value)
    if m:
        return m.group(1).replace(",", "")
    return value.replace(",", "")


def _to_bool(value: str) -> Optional[bool]:
    s = value.strip().lower()
    if s in {"true", "yes"}:
        return True
    if s in {"false", "no"}:
        return False
    return None
