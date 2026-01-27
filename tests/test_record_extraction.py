"""Tests for the record-aware heuristic extractor."""

from __future__ import annotations

from sandpaper_py.extractors import HeuristicExtractor


def test_record_set_aligns_rows(cards_html: str):
    """Each row should describe one company; columns should not be misaligned."""
    ex = HeuristicExtractor(threshold=5)
    table = ex.extract(cards_html)
    assert table.row_count() == 10

    by_name = dict(table.columns.items())
    name_col = next(
        (v for k, v in by_name.items() if "company_name" in k.lower() or "companyName" in k), None
    )
    assert name_col is not None
    assert name_col[0] == "TCS"
    assert name_col[1] == "Wipro"
    assert name_col[-1] == "Genpact"

    rating_col = next(
        (v for k, v in by_name.items() if "rating" in k.lower() and "count" not in k.lower()), None
    )
    assert rating_col is not None
    assert rating_col[0] == "3.3"
    assert rating_col[1] == "3.6"


def test_record_set_dedups_duplicate_columns(cards_html: str):
    """The h2 inside a wrapper anchor should not produce a separate column from the leaf text."""
    ex = HeuristicExtractor(threshold=5)
    table = ex.extract(cards_html)
    keys = list(table.columns.keys())
    name_keys = [k for k in keys if "company_name" in k.lower() or "companyName" in k]
    assert len(name_keys) == 1


def test_record_set_excludes_filter_aside(cards_html: str):
    """Sidebar filters with 3 repeating filter-row siblings should not become the chosen record set."""
    ex = HeuristicExtractor(threshold=5)
    table = ex.extract(cards_html)
    # Filter rows would produce a 'filter-row' or 'label' column with 3 entries; ensure rows >= 10
    assert table.row_count() >= 10
    # No column should look like a filter label list
    for values in table.columns.values():
        assert "Filter" not in values[:3] or len([v for v in values if v == "Filter"]) <= 1


def test_table_extraction_first(table_html_doc: str):
    ex = HeuristicExtractor(threshold=5)
    table = ex.extract(table_html_doc)
    assert table.row_count() == 12
    assert set(table.columns.keys()) == {"Country", "Capital", "Population"}
    assert table.columns["Country"][0] == "India"
    assert table.columns["Population"][0] == "1428000000"


def test_legacy_fallback_when_no_records():
    """Pages with no repeating siblings still produce something via the flat fallback."""
    html = (
        "<html><body>"
        + "".join(f"<p class='note'>note {i}</p>" for i in range(15))
        + "</body></html>"
    )
    ex = HeuristicExtractor(threshold=10)
    table = ex.extract(html)
    assert table.row_count() == 15


def test_no_generic_no_class_columns_in_records(cards_html: str):
    """Record-aware output should not produce 'no-class' style columns when classes exist."""
    ex = HeuristicExtractor(threshold=5)
    table = ex.extract(cards_html)
    for key in table.columns:
        assert "no-class" not in key.lower()


def test_row_alignment_no_blank_first_column(cards_html: str):
    """Every row should have a value in the company name column; positional misalignment is gone."""
    ex = HeuristicExtractor(threshold=5)
    table = ex.extract(cards_html)
    name_col = next(
        v for k, v in table.columns.items() if "company_name" in k.lower() or "companyName" in k
    )
    assert all(v.strip() for v in name_col)


def test_max_fields_per_record_caps_keys():
    html = (
        "<html><body>"
        + "".join(
            "<div class='card'>"
            + "".join(f"<span class='f{j}'>val{i}-{j}</span>" for j in range(50))
            + "</div>"
            for i in range(12)
        )
        + "</body></html>"
    )
    ex = HeuristicExtractor(threshold=10, max_fields_per_record=10)
    table = ex.extract(html)
    assert len(table.columns) <= 10
