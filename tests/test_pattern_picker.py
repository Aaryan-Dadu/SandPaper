"""Tests for the pattern picker and row-scoped selector extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from sandpaper_py.cli import main
from sandpaper_py.exceptions import ExtractionError
from sandpaper_py.extractors import SelectorExtractor
from sandpaper_py.visual import PickResult


def test_row_scoped_extraction_aligns(cards_html: str):
    ex = SelectorExtractor(
        row_selector="li.companyCard",
        selectors={
            "name": "h2.companyCardWrapper__companyName",
            "rating": "span.companyCardWrapper__companyRating",
            "rating_count": "span.companyCardWrapper__companyRatingCount",
        },
    )
    table = ex.extract(cards_html)
    assert table.row_count() == 10
    assert table.columns["name"][0] == "TCS"
    assert table.columns["rating"][0] == "3.3"
    assert table.columns["rating_count"][0] == "(1.1L)"


def test_row_scoped_missing_field_yields_empty_string():
    html = """
    <ul>
      <li class='card'><span class='name'>A</span><span class='price'>1</span></li>
      <li class='card'><span class='name'>B</span></li>
      <li class='card'><span class='name'>C</span><span class='price'>3</span></li>
    </ul>
    """
    ex = SelectorExtractor(
        row_selector="li.card",
        selectors={"name": "span.name", "price": "span.price"},
    )
    table = ex.extract(html)
    assert table.columns["name"] == ["A", "B", "C"]
    assert table.columns["price"] == ["1", "", "3"]


def test_row_scoped_zero_rows():
    ex = SelectorExtractor(
        row_selector="li.card",
        selectors={"name": ".name"},
    )
    table = ex.extract("<html><body><div>nothing</div></body></html>")
    assert table.columns == {"name": []}


def test_row_scoped_invalid_row_selector():
    ex = SelectorExtractor(
        row_selector="li.card[",
        selectors={"name": ".name"},
    )
    with pytest.raises(ExtractionError, match="row_selector"):
        ex.extract("<html><body></body></html>")


def test_row_scoped_invalid_field_selector(cards_html: str):
    ex = SelectorExtractor(
        row_selector="li.companyCard",
        selectors={"name": "h2[ broken"},
    )
    with pytest.raises(ExtractionError, match="selector"):
        ex.extract(cards_html)


def test_pick_result_to_preset():
    result = PickResult(
        row_selector="li.card",
        selectors={"name": "h2.title", "price": "span.price"},
        samples={"name": ["A", "B"], "price": ["1", "2"]},
        row_count=2,
    )
    payload = result.to_preset_dict()
    assert payload["extractor"] == "selector"
    assert payload["row_selector"] == "li.card"
    assert payload["selectors"] == {"name": "h2.title", "price": "span.price"}


def test_pick_command_help():
    runner = CliRunner()
    result = runner.invoke(main, ["pick", "--help"])
    assert result.exit_code == 0
    assert "row pattern" in result.output.lower()
    assert "--save-preset" in result.output
    assert "--save" in result.output


def test_run_command_accepts_row_selector():
    runner = CliRunner()
    result = runner.invoke(main, ["run", "--help"])
    assert result.exit_code == 0
    assert "--row-selector" in result.output


def test_pattern_picker_preset_round_trip(tmp_path: Path, monkeypatch):
    """A picker result saved as a preset should reload with row_selector intact."""
    monkeypatch.setattr("sandpaper_py.presets.presets_dir", lambda: tmp_path)
    from sandpaper_py.config import ScrapeConfig
    from sandpaper_py.presets import load_preset, save_preset

    cfg = ScrapeConfig(
        extractor="selector",
        row_selector="li.card",
        selectors={"name": "h2.title"},
    )
    save_preset("test_site", cfg)
    loaded = load_preset("test_site")
    assert loaded.row_selector == "li.card"
    assert loaded.selectors == {"name": "h2.title"}
    assert loaded.extractor == "selector"


def test_end_to_end_with_picker_preset(monkeypatch, cards_html: str, tmp_path: Path):
    """A preset built from picker output should drive a clean scrape end-to-end."""
    monkeypatch.setattr("sandpaper_py.presets.presets_dir", lambda: tmp_path)
    from sandpaper_py.config import ScrapeConfig
    from sandpaper_py.core import scrape
    from sandpaper_py.presets import save_preset
    from sandpaper_py.types import LoadResult

    save_preset(
        "cards_site",
        ScrapeConfig(
            extractor="selector",
            row_selector="li.companyCard",
            selectors={
                "name": "h2.companyCardWrapper__companyName",
                "rating": "span.companyCardWrapper__companyRating",
            },
        ),
    )

    class StubLoader:
        def load(self, url: str) -> LoadResult:
            return LoadResult(url=url, html=cards_html, status=200, final_url=url)

        def close(self) -> None:
            pass

    monkeypatch.setattr("sandpaper_py.core._build_loader", lambda _cfg, **_kw: StubLoader())

    output = tmp_path / "out.json"
    cfg = ScrapeConfig(
        url="https://example.com",
        preset="cards_site",
        output=str(output),
        format="json",
    )
    result = scrape(cfg)
    assert result.rows == 10
    assert set(result.columns) == {"name", "rating"}
    assert all(name.strip() for name in result.table.columns["name"])
