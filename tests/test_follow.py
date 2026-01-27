"""Tests for detail-page join (--follow)."""

from __future__ import annotations

import pytest

from sandpaper_py.config import ScrapeConfig
from sandpaper_py.core import _resolve_follow_url, scrape
from sandpaper_py.exceptions import LoadError
from sandpaper_py.extractors import SelectorExtractor
from sandpaper_py.extractors.selector import _parse_selector
from sandpaper_py.types import LoadResult
from tests.conftest import article_detail_html

# -- helpers


class _StubLoader:
    """Stub loader returning canned HTML per URL pattern."""

    def __init__(self, list_html: str, fail_for: set[str] | None = None):
        self.list_html = list_html
        self.fail_for = fail_for or set()
        self.calls: list[str] = []

    def load(self, url: str) -> LoadResult:
        self.calls.append(url)
        if url in self.fail_for:
            raise LoadError(url, "stub failure")
        if "/articles/" in url:
            slug = url.rsplit("/", 1)[-1]
            return LoadResult(url=url, html=article_detail_html(slug), status=200, final_url=url)
        return LoadResult(url=url, html=self.list_html, status=200, final_url=url)

    def close(self) -> None:
        pass


# -- @attr syntax


def test_parse_selector_plain():
    assert _parse_selector("a.title") == ("a.title", None)


def test_parse_selector_attribute():
    assert _parse_selector("a.title@href") == ("a.title", "href")


def test_parse_selector_attribute_in_brackets_not_misparsed():
    sel, attr = _parse_selector('a[href*="@example.com"]')
    # The "@" inside the bracket should not become an attr suffix.
    assert sel == 'a[href*="@example.com"]'
    assert attr is None


def test_selector_attribute_extraction():
    html = '<ul><li><a class="x" href="/a">A</a></li><li><a class="x" href="/b">B</a></li></ul>'
    ex = SelectorExtractor(selectors={"href": "a.x@href", "text": "a.x"})
    table = ex.extract(html)
    assert table.columns["href"] == ["/a", "/b"]
    assert table.columns["text"] == ["A", "B"]


def test_selector_attribute_with_row_selector():
    html = '<ul><li class="row"><a href="/a">A</a></li><li class="row"><a href="/b">B</a></li></ul>'
    ex = SelectorExtractor(
        row_selector="li.row",
        selectors={"href": "a@href", "label": "a"},
    )
    table = ex.extract(html)
    assert table.columns["href"] == ["/a", "/b"]
    assert table.columns["label"] == ["A", "B"]


def test_selector_extract_one_returns_first_match():
    html = "<div><span class='b'>one</span><span class='b'>two</span></div>"
    ex = SelectorExtractor(selectors={"first": "span.b"})
    record = ex.extract_one(html)
    assert record == {"first": "one"}


def test_selector_extract_one_missing_returns_empty_string():
    ex = SelectorExtractor(selectors={"x": ".missing"})
    assert ex.extract_one("<html><body></body></html>") == {"x": ""}


# -- URL resolution


def test_resolve_follow_url_absolute():
    assert _resolve_follow_url("https://e.com/a", "https://b.com", None) == "https://e.com/a"


def test_resolve_follow_url_relative_with_base():
    assert _resolve_follow_url("/a", "https://b.com/page", None) == "https://b.com/a"


def test_resolve_follow_url_relative_with_prefix():
    assert _resolve_follow_url("/a", None, "https://e.com") == "https://e.com/a"


def test_resolve_follow_url_invalid():
    assert _resolve_follow_url("", None, None) is None
    assert _resolve_follow_url("javascript:void(0)", "https://e.com", None) is None


# -- end-to-end follow


def test_follow_merges_detail_fields(monkeypatch, articles_list_html: str):
    stub = _StubLoader(articles_list_html)
    monkeypatch.setattr("sandpaper_py.core._build_loader", lambda _cfg, **_kw: stub)

    cfg = ScrapeConfig(
        url="https://news.example.com/list",
        extractor="selector",
        row_selector="article.post",
        selectors={
            "title": "h2.title",
            "summary": "p.lede",
            "url": "a.title-link@href",
        },
        follow_field="url",
        follow_selectors={
            "body": "div.body",
            "author": "span.author",
        },
        follow_concurrency=1,
    )
    result = scrape(cfg)
    assert result.rows == 5
    assert set(result.columns) == {"title", "summary", "url", "body", "author"}
    assert result.table.columns["url"][0] == "/articles/alpha"
    assert "full body for alpha" in result.table.columns["body"][0]
    assert result.table.columns["author"][0] == "Author Alpha"


def test_follow_concurrent(monkeypatch, articles_list_html: str):
    stub = _StubLoader(articles_list_html)
    monkeypatch.setattr("sandpaper_py.core._build_loader", lambda _cfg, **_kw: stub)

    cfg = ScrapeConfig(
        url="https://news.example.com/list",
        extractor="selector",
        row_selector="article.post",
        selectors={"title": "h2.title", "url": "a.title-link@href"},
        follow_field="url",
        follow_selectors={"body": "div.body"},
        follow_concurrency=3,
    )
    result = scrape(cfg)
    assert result.rows == 5
    bodies = result.table.columns["body"]
    assert all("full body" in b for b in bodies)


def test_follow_skip_on_error_default(monkeypatch, articles_list_html: str):
    """Default behavior: a failing detail page does not abort the run."""
    stub = _StubLoader(
        articles_list_html,
        fail_for={"https://news.example.com/articles/gamma"},
    )
    monkeypatch.setattr("sandpaper_py.core._build_loader", lambda _cfg, **_kw: stub)

    cfg = ScrapeConfig(
        url="https://news.example.com/list",
        extractor="selector",
        row_selector="article.post",
        selectors={"title": "h2.title", "url": "a.title-link@href"},
        follow_field="url",
        follow_selectors={"body": "div.body"},
        follow_concurrency=1,
    )
    result = scrape(cfg)
    assert result.rows == 5
    assert result.table.columns["body"][2] == ""  # gamma failed
    assert result.table.columns["body"][0] != ""


def test_follow_fail_on_error(monkeypatch, articles_list_html: str):
    stub = _StubLoader(
        articles_list_html,
        fail_for={"https://news.example.com/articles/gamma"},
    )
    monkeypatch.setattr("sandpaper_py.core._build_loader", lambda _cfg, **_kw: stub)

    cfg = ScrapeConfig(
        url="https://news.example.com/list",
        extractor="selector",
        row_selector="article.post",
        selectors={"title": "h2.title", "url": "a.title-link@href"},
        follow_field="url",
        follow_selectors={"body": "div.body"},
        follow_concurrency=1,
        follow_skip_on_error=False,
    )
    with pytest.raises(LoadError):
        scrape(cfg)


def test_follow_resolves_relative_urls(monkeypatch, articles_list_html: str):
    stub = _StubLoader(articles_list_html)
    monkeypatch.setattr("sandpaper_py.core._build_loader", lambda _cfg, **_kw: stub)

    cfg = ScrapeConfig(
        url="https://news.example.com/list",
        extractor="selector",
        row_selector="article.post",
        selectors={"url": "a.title-link@href"},
        follow_field="url",
        follow_selectors={"body": "div.body"},
        follow_concurrency=1,
    )
    scrape(cfg)
    # Verify the loader was called with absolute URLs derived from the base
    detail_calls = [c for c in stub.calls if "/articles/" in c]
    assert "https://news.example.com/articles/alpha" in detail_calls


def test_follow_no_field_value_skips_row(monkeypatch):
    list_html = """
    <html><body>
      <article class='post'>
        <h2 class='title'><a class='title-link' href='/articles/a'>A</a></h2>
        <p class='lede'>A</p>
      </article>
      <article class='post'>
        <h2 class='title'>B (no link)</h2>
        <p class='lede'>B</p>
      </article>
    </body></html>"""
    stub = _StubLoader(list_html)
    monkeypatch.setattr("sandpaper_py.core._build_loader", lambda _cfg, **_kw: stub)

    cfg = ScrapeConfig(
        url="https://e.com/list",
        extractor="selector",
        row_selector="article.post",
        selectors={"title": "h2.title", "url": "a.title-link@href"},
        follow_field="url",
        follow_selectors={"body": "div.body"},
        follow_concurrency=1,
    )
    result = scrape(cfg)
    assert result.rows == 2
    assert result.table.columns["body"][0] != ""  # row A fetched
    assert result.table.columns["body"][1] == ""  # row B had no url


def test_follow_provenance_records_settings(monkeypatch, articles_list_html: str):
    stub = _StubLoader(articles_list_html)
    monkeypatch.setattr("sandpaper_py.core._build_loader", lambda _cfg, **_kw: stub)

    cfg = ScrapeConfig(
        url="https://news.example.com/list",
        extractor="selector",
        row_selector="article.post",
        selectors={"url": "a.title-link@href"},
        follow_field="url",
        follow_selectors={"body": "div.body"},
        follow_concurrency=2,
    )
    result = scrape(cfg)
    opts = result.provenance.options
    assert opts["follow_field"] == "url"
    assert opts["follow_selectors"] == {"body": "div.body"}
    assert opts["follow_concurrency"] == 2


def test_run_command_accepts_follow_flags():
    from click.testing import CliRunner

    from sandpaper_py.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["run", "--help"])
    assert result.exit_code == 0
    assert "--follow" in result.output
    assert "--follow-selectors" in result.output
    assert "--follow-concurrency" in result.output
    assert "--follow-fail-on-error" in result.output
