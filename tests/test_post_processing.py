"""Tests for the post-processing pipeline:

* trim_cells
* rename_columns / keep_columns / drop_columns
* required_columns
* schema_lock_after
* JSON null_policy
"""

from __future__ import annotations

import json
from pathlib import Path

from sandpaper_py.config import ScrapeConfig
from sandpaper_py.core import (
    _apply_schema_lock,
    _enforce_required,
    _post_process,
    _rename_columns,
    _select_columns,
    _trim_columns,
    scrape,
)
from sandpaper_py.exporters import JSONExporter, JSONLExporter
from sandpaper_py.types import ExtractedTable, LoadResult

# ----- trim


def test_trim_columns_strips_whitespace():
    columns = {"a": ["  hi ", "\tworld\n", "ok"], "b": [" x ", "y", " z"]}
    out = _trim_columns(columns)
    assert out == {"a": ["hi", "world", "ok"], "b": ["x", "y", "z"]}


# ----- rename / keep / drop


def test_rename_columns_simple():
    out = _rename_columns({"a": [1, 2], "b": [3, 4]}, {"a": "alpha"})
    assert list(out.keys()) == ["alpha", "b"]
    assert out["alpha"] == [1, 2]


def test_rename_columns_collision_appends_suffix():
    out = _rename_columns({"a": [1], "b": [2], "c": [3]}, {"a": "x", "b": "x"})
    keys = list(out.keys())
    assert "x" in keys
    assert "x_2" in keys
    assert "c" in keys


def test_select_columns_keep_only():
    out = _select_columns({"a": [1], "b": [2], "c": [3]}, keep=["a", "c"], drop=[])
    assert list(out.keys()) == ["a", "c"]


def test_select_columns_drop():
    out = _select_columns({"a": [1], "b": [2]}, keep=[], drop=["b"])
    assert list(out.keys()) == ["a"]


def test_select_columns_keep_takes_precedence():
    out = _select_columns({"a": [1], "b": [2], "c": [3]}, keep=["a"], drop=["a"])
    assert list(out.keys()) == ["a"]


# ----- required


def test_required_columns_drops_rows_missing_value():
    columns = {
        "name": ["Alice", "", "Charlie"],
        "city": ["NYC", "SF", ""],
    }
    out = _enforce_required(columns, ["name", "city"])
    assert out == {"name": ["Alice"], "city": ["NYC"]}


def test_required_columns_unknown_column_logged_and_ignored(caplog):
    columns = {"a": ["1", "2"]}
    out = _enforce_required(columns, ["a", "missing_col"])
    # rows kept since 'missing_col' isn't in the columns
    assert out == {"a": ["1", "2"]}


def test_required_columns_empty_passes_through():
    columns = {"a": ["1", "2"]}
    assert _enforce_required(columns, []) == columns


# ----- schema lock


def test_schema_lock_drops_columns_absent_in_first_n():
    columns = {
        "always": ["a", "b", "c", "d"],
        "late": ["", "", "", "x"],
    }
    out = _apply_schema_lock(columns, lock_after=2)
    assert "always" in out
    assert "late" not in out


def test_schema_lock_disabled_when_zero():
    columns = {"a": [""], "b": [""]}
    out = _apply_schema_lock(columns, lock_after=0)
    assert out == columns


def test_schema_lock_no_drop_when_n_exceeds_rows():
    columns = {"a": ["", ""], "b": ["1", "2"]}
    out = _apply_schema_lock(columns, lock_after=10)
    assert out == columns


# ----- post_process orchestration


def test_post_process_full_pipeline():
    cfg = ScrapeConfig(
        trim_cells=True,
        rename_columns={"raw_name": "name"},
        drop_columns=["junk"],
        required_columns=["name"],
    )
    columns = {
        "raw_name": [" Alice ", " ", "Charlie"],
        "junk": ["x", "y", "z"],
        "score": ["1", "2", "3"],
    }
    out = _post_process(columns, cfg)
    assert "name" in out
    assert "junk" not in out
    assert out["name"] == ["Alice", "Charlie"]
    assert out["score"] == ["1", "3"]


def test_post_process_keep_columns_wins():
    cfg = ScrapeConfig(keep_columns=["a"], drop_columns=["a"])
    out = _post_process({"a": ["1"], "b": ["2"]}, cfg)
    assert list(out.keys()) == ["a"]


# ----- JSON null policy


def _fixture_table_with_blank() -> ExtractedTable:
    return ExtractedTable(columns={"name": ["Alice", "", "Charlie"], "city": ["NYC", "SF", ""]})


def test_json_null_policy_empty_keeps_string(tmp_path: Path):
    out = tmp_path / "out.json"
    JSONExporter(null_policy="empty").export(_fixture_table_with_blank(), out)
    rows = json.loads(out.read_text())
    assert rows[1]["name"] == ""
    assert rows[2]["city"] == ""


def test_json_null_policy_null_replaces_empty(tmp_path: Path):
    out = tmp_path / "out.json"
    JSONExporter(null_policy="null").export(_fixture_table_with_blank(), out)
    rows = json.loads(out.read_text())
    assert rows[1]["name"] is None
    assert rows[2]["city"] is None
    assert rows[0]["name"] == "Alice"


def test_json_null_policy_skip_omits_key(tmp_path: Path):
    out = tmp_path / "out.json"
    JSONExporter(null_policy="skip").export(_fixture_table_with_blank(), out)
    rows = json.loads(out.read_text())
    assert "name" not in rows[1]
    assert "city" not in rows[2]
    assert rows[0]["name"] == "Alice"


def test_jsonl_null_policy_null(tmp_path: Path):
    out = tmp_path / "out.jsonl"
    JSONLExporter(null_policy="null").export(_fixture_table_with_blank(), out)
    line = out.read_text().splitlines()[1]
    assert json.loads(line)["name"] is None


# ----- end-to-end via scrape()


class _StubLoader:
    def __init__(self, html: str):
        self.html = html

    def load(self, url: str) -> LoadResult:
        return LoadResult(url=url, html=self.html, status=200, final_url=url)

    def close(self) -> None:
        pass


def test_end_to_end_rename_and_required(monkeypatch, tmp_path: Path):
    html = """
    <ul>
      <li class='card'><span class='nm'>Alice</span><span class='ct'>NYC</span></li>
      <li class='card'><span class='nm'>Bob</span><span class='ct'></span></li>
      <li class='card'><span class='nm'></span><span class='ct'>Berlin</span></li>
      <li class='card'><span class='nm'>Dora</span><span class='ct'>SF</span></li>
    </ul>"""
    monkeypatch.setattr("sandpaper_py.core._build_loader", lambda _cfg, **_kw: _StubLoader(html))
    cfg = ScrapeConfig(
        url="https://e.com",
        extractor="selector",
        row_selector="li.card",
        selectors={"nm": "span.nm", "ct": "span.ct"},
        rename_columns={"nm": "name", "ct": "city"},
        required_columns=["name", "city"],
        format="json",
        output=str(tmp_path / "out.json"),
    )
    result = scrape(cfg)
    assert result.rows == 2
    assert set(result.columns) == {"name", "city"}
    rows = json.loads(Path(cfg.output).read_text())
    assert {(r["name"], r["city"]) for r in rows} == {("Alice", "NYC"), ("Dora", "SF")}


def test_end_to_end_null_policy_through_scrape(monkeypatch, tmp_path: Path):
    html = """
    <ul>
      <li class='card'><span class='name'>Alice</span><span class='city'>NYC</span></li>
      <li class='card'><span class='name'>Bob</span><span class='city'></span></li>
    </ul>"""
    monkeypatch.setattr("sandpaper_py.core._build_loader", lambda _cfg, **_kw: _StubLoader(html))
    out = tmp_path / "out.json"
    cfg = ScrapeConfig(
        url="https://e.com",
        extractor="selector",
        row_selector="li.card",
        selectors={"name": "span.name", "city": "span.city"},
        format="json",
        output=str(out),
        null_policy="null",
        json_drop_empty=False,
    )
    scrape(cfg)
    rows = json.loads(out.read_text())
    assert rows[0]["city"] == "NYC"
    assert rows[1]["city"] is None


def test_end_to_end_trim_cells(monkeypatch, tmp_path: Path):
    html = """
    <ul>
      <li class='card'><span class='name'>  Alice </span></li>
      <li class='card'><span class='name'>\tBob\n</span></li>
    </ul>"""
    monkeypatch.setattr("sandpaper_py.core._build_loader", lambda _cfg, **_kw: _StubLoader(html))
    cfg = ScrapeConfig(
        url="https://e.com",
        extractor="selector",
        row_selector="li.card",
        selectors={"name": "span.name"},
    )
    result = scrape(cfg)
    # bs4 strip already handles most; verify post-process trim catches the rest
    assert result.table.columns["name"] == ["Alice", "Bob"]


def test_run_command_accepts_new_flags():
    from click.testing import CliRunner

    from sandpaper_py.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["run", "--help"])
    assert result.exit_code == 0
    for flag in (
        "--rename-columns",
        "--keep-columns",
        "--drop-columns",
        "--required-columns",
        "--no-trim",
        "--null-policy",
        "--schema-lock-after",
    ):
        assert flag in result.output, f"missing flag: {flag}"
