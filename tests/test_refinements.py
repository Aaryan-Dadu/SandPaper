"""Tests covering the audit-driven refinements."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sandpaper_py.exceptions import ConfigError
from sandpaper_py.exporters import CSVExporter, JSONExporter, JSONLExporter
from sandpaper_py.exporters.base import (
    neutralize_formula,
    normalize_to_dataframe,
    safe_dataframe,
)
from sandpaper_py.extractors import HeuristicExtractor
from sandpaper_py.provenance import write_quality_report
from sandpaper_py.robots import RobotsCache
from sandpaper_py.types import ExtractedTable, Provenance, ScrapeResult
from sandpaper_py.utils import HTMLCache, parse_page_range, slugify_key


def test_parse_page_range_caps_huge_ranges():
    with pytest.raises(ConfigError, match="safety cap"):
        parse_page_range("1-50000", max_pages=1000)


def test_parse_page_range_rejects_zero():
    with pytest.raises(ConfigError):
        parse_page_range("0-5")


def test_parse_page_range_combined_cap():
    with pytest.raises(ConfigError, match="safety cap"):
        parse_page_range("1-600,1-600", max_pages=1000)


def test_robots_allow_on_error_default_denies():
    rc = RobotsCache(enabled=True, allow_on_error=False)
    rc._errored.add("https://offline.example")
    assert rc.allowed("https://offline.example/page") is False


def test_robots_allow_on_error_can_be_relaxed():
    rc = RobotsCache(enabled=True, allow_on_error=True)
    rc._errored.add("https://offline.example")
    assert rc.allowed("https://offline.example/page") is True


def test_heuristic_drops_overlong_text():
    big = "x" * 10000
    html = (
        "<html><body><div class='listing'>"
        + "".join(f"<p class='item'>row {i}</p>" for i in range(15))
        + "</div>"
        + f"<div class='nav-bar'><span>{big}</span></div>"
        + "</body></html>"
    )
    ex = HeuristicExtractor(threshold=10, max_text_length=4000)
    table = ex.extract(html)
    keys = list(table.columns.keys())
    assert "item" in keys
    assert not any("nav" in k.lower() for k in keys)


def test_heuristic_skips_nav_class_ancestors():
    html = (
        """
    <html><body>
      <div class='site-nav'>
        <a class='nav-link'>Home</a><a class='nav-link'>About</a><a class='nav-link'>Contact</a>
      </div>
      <ul>"""
        + "".join(f"<li class='item'><span class='title'>row {i}</span></li>" for i in range(15))
        + """</ul>
    </body></html>
    """
    )
    ex = HeuristicExtractor(threshold=3)
    table = ex.extract(html)
    keys = list(table.columns.keys())
    assert "title" in keys
    assert "nav-link" not in keys


def test_csv_safe_mode_neutralizes_formulas(tmp_path: Path):
    table = ExtractedTable(columns={"name": ["=cmd|/c calc", "Alice", "+1"]})
    out = tmp_path / "safe.csv"
    CSVExporter(safe=True).export(table, out)
    rows = out.read_text(encoding="utf-8").splitlines()
    assert rows[1].startswith("'=cmd")
    assert rows[3].startswith("'+1")
    assert rows[2] == "Alice"


def test_csv_default_does_not_escape(tmp_path: Path):
    table = ExtractedTable(columns={"name": ["=danger", "Alice"]})
    out = tmp_path / "raw.csv"
    CSVExporter().export(table, out)
    assert out.read_text().splitlines()[1] == "=danger"


def test_neutralize_formula_pure():
    assert neutralize_formula("=foo") == "'=foo"
    assert neutralize_formula("@bar") == "'@bar"
    assert neutralize_formula("safe") == "safe"


def test_safe_dataframe_passthrough_for_non_strings():
    import pandas as pd

    df = pd.DataFrame({"a": [1, 2, 3], "b": ["=x", "y", "z"]})
    out = safe_dataframe(df)
    assert list(out["a"]) == [1, 2, 3]
    assert out["b"].iloc[0].startswith("'=")


def test_json_drop_empty_columns(tmp_path: Path):
    table = ExtractedTable(columns={"name": ["A", "B"], "blank": ["", ""], "ok": ["x", "y"]})
    out = tmp_path / "clean.json"
    JSONExporter(drop_empty_columns=True).export(table, out)
    payload = json.loads(out.read_text())
    assert "blank" not in payload[0]
    assert "name" in payload[0]


def test_json_normalize_keys(tmp_path: Path):
    table = ExtractedTable(columns={"Some Title!": ["a", "b"], "Price-USD": ["1", "2"]})
    out = tmp_path / "n.json"
    JSONExporter(normalize_keys=True).export(table, out)
    rows = json.loads(out.read_text())
    keys = set(rows[0].keys())
    assert "some_title" in keys
    assert "price_usd" in keys


def test_jsonl_drop_empty_and_sort(tmp_path: Path):
    table = ExtractedTable(columns={"z": ["1", "2"], "a": ["x", "y"], "blank": ["", ""]})
    out = tmp_path / "feed.jsonl"
    JSONLExporter(drop_empty_columns=True, sort_keys=True).export(table, out)
    line = out.read_text().splitlines()[0]
    keys = list(json.loads(line).keys())
    assert keys == ["a", "z"]


def test_normalize_to_dataframe_drop_empty():
    table = ExtractedTable(columns={"keep": ["a"], "drop": [""]})
    df = normalize_to_dataframe(table, drop_empty_columns=True)
    assert list(df.columns) == ["keep"]


def test_normalize_to_dataframe_sort():
    table = ExtractedTable(columns={"z": ["1"], "a": ["2"]})
    df = normalize_to_dataframe(table, sort_columns=True)
    assert list(df.columns) == ["a", "z"]


def test_slugify_key():
    assert slugify_key("Some Title!") == "some_title"
    assert slugify_key("price-USD") == "price_usd"
    assert slugify_key("---") == "field"


def test_html_cache_round_trip(tmp_path: Path):
    cache = HTMLCache(str(tmp_path), ttl_seconds=60)
    assert cache.get("https://e.com") is None
    cache.put("https://e.com", "<html>cached</html>")
    assert cache.get("https://e.com") == "<html>cached</html>"


def test_html_cache_disabled_when_root_none():
    cache = HTMLCache(None)
    cache.put("https://e.com", "x")
    assert cache.get("https://e.com") is None


def test_scrape_result_records_and_pandas():
    table = ExtractedTable(columns={"a": ["1", "2"], "b": ["x", "y"]})
    result = ScrapeResult(table=table, provenance=Provenance())
    rows = result.records()
    assert rows == [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}]

    df = result.to_pandas()
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2

    typed = result.to_pandas(typed=True)
    assert list(typed.columns) == ["a", "b"]


def test_quality_report_sidecar(tmp_path: Path):
    table = ExtractedTable(columns={"x": ["1", "", "3"], "y": ["a", "b", "c"]})
    target = tmp_path / "out.json"
    target.write_text("[]")
    sidecar = write_quality_report(table, target)
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text())
    assert payload["rows"] == 3
    by_name = {c["name"]: c for c in payload["columns"]}
    assert by_name["x"]["empty"] == 1
    assert by_name["x"]["null_ratio"] == pytest.approx(1 / 3)


def test_typed_export_to_parquet(tmp_path: Path):
    pyarrow = pytest.importorskip("pyarrow")  # noqa: F841
    from sandpaper_py.exporters import ParquetExporter

    table = ExtractedTable(columns={"n": ["1", "2", "3"], "name": ["a", "b", "c"]})
    out = tmp_path / "typed.parquet"
    ParquetExporter(typed=True).export(table, out)
    assert out.exists()


def test_per_thread_loader_reuse(monkeypatch, list_html, tmp_path: Path):
    """Verify _scrape_concurrent calls _build_loader once per worker, not per URL."""
    from sandpaper_py.config import ScrapeConfig
    from sandpaper_py.core import scrape
    from sandpaper_py.types import LoadResult

    build_calls = {"count": 0}

    class StubLoader:
        def load(self, url: str) -> LoadResult:
            return LoadResult(url=url, html=list_html, status=200, final_url=url)

        def close(self) -> None:
            pass

    def fake_build(_cfg, **_kwargs):
        build_calls["count"] += 1
        return StubLoader()

    monkeypatch.setattr("sandpaper_py.core._build_loader", fake_build)

    urls = [f"https://e.com/p/{i}" for i in range(20)]
    cfg = ScrapeConfig(url_list=urls, concurrency=4, threshold=10)
    result = scrape(cfg)
    assert result.rows >= 12
    assert build_calls["count"] <= 4
