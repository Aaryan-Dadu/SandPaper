import pytest

from sandpaper_py.exceptions import ExtractionError
from sandpaper_py.extractors import HeuristicExtractor, SelectorExtractor


def test_heuristic_pulls_repeating_columns(list_html):
    ex = HeuristicExtractor(threshold=10)
    table = ex.extract(list_html, source_url="https://e.com")
    assert table.row_count() == 12
    titles = next(v for k, v in table.columns.items() if "title" in k)
    assert titles[:3] == ["Alpha", "Beta", "Gamma"]


def test_heuristic_filters_below_threshold(list_html):
    ex = HeuristicExtractor(threshold=20)
    table = ex.extract(list_html)
    assert table.columns == {}


def test_heuristic_handles_missing_body(no_body_html):
    ex = HeuristicExtractor(threshold=1)
    table = ex.extract(no_body_html)
    assert table.columns == {}


def test_heuristic_empty_html():
    ex = HeuristicExtractor()
    assert ex.extract("").columns == {}


def test_heuristic_threshold_validation():
    with pytest.raises(ExtractionError):
        HeuristicExtractor(threshold=0)


def test_selector_extracts(list_html):
    ex = SelectorExtractor(selectors={"title": "h2.title", "price": ".price"})
    table = ex.extract(list_html)
    assert table.columns["title"][0] == "Alpha"
    assert table.columns["price"][0] == "$10.00"
    assert len(table.columns["title"]) == 12


def test_selector_requires_selectors():
    with pytest.raises(ExtractionError):
        SelectorExtractor(selectors={})
