from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .schema import summarize
from .types import ExtractedTable, Provenance


def write_sidecar(provenance: Provenance, output_path: str | Path) -> Path:
    target = Path(output_path)
    sidecar = target.with_suffix(target.suffix + ".meta.json")
    with open(sidecar, "w", encoding="utf-8") as fh:
        json.dump(asdict(provenance), fh, indent=2, ensure_ascii=False)
    return sidecar


def write_quality_report(table: ExtractedTable, output_path: str | Path) -> Path:
    target = Path(output_path)
    sidecar = target.with_suffix(target.suffix + ".quality.json")
    stats = summarize(table)
    payload = {
        "rows": stats.rows,
        "columns": [
            {
                "name": c.name,
                "inferred_type": c.inferred_type,
                "non_empty": c.non_empty,
                "empty": c.empty,
                "unique": c.unique,
                "null_ratio": (c.empty / (c.empty + c.non_empty))
                if (c.empty + c.non_empty)
                else 0.0,
                "sample": c.sample,
            }
            for c in stats.columns
        ],
    }
    with open(sidecar, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return sidecar
