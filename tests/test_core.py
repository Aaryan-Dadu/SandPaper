from pathlib import Path

from sandpaper_py.config import ScrapeConfig
from sandpaper_py.core import _deduplicate, scrape


class _StubLoader:
    def __init__(self, html_by_url: dict[str, str]):
        self.html_by_url = html_by_url
        self.closed = False

    def load(self, url: str):
        from sandpaper_py.types import LoadResult

        if url not in self.html_by_url:
            from sandpaper_py.exceptions import LoadError

            raise LoadError(url, "stub: not found")
        return LoadResult(url=url, html=self.html_by_url[url], status=200, final_url=url)

    def close(self) -> None:
        self.closed = True


def test_deduplicate_removes_repeats():
    columns = {"a": ["1", "1", "2"], "b": ["x", "x", "y"]}
    out = _deduplicate(columns)
    assert out == {"a": ["1", "2"], "b": ["x", "y"]}


def test_scrape_with_stub(monkeypatch, list_html, tmp_path: Path):
    pages = {
        "https://example.com/p/1": list_html,
        "https://example.com/p/2": list_html,
    }

    def fake_build_loader(_cfg, **_kw):
        return _StubLoader(pages)

    monkeypatch.setattr("sandpaper_py.core._build_loader", fake_build_loader)

    out = tmp_path / "out.csv"
    cfg = ScrapeConfig(
        page_template="https://example.com/p/{page}",
        pages="1-2",
        output=str(out),
        format="csv",
        threshold=10,
    )
    result = scrape(cfg)
    assert result.rows == 24
    assert out.exists()
    assert "https://example.com/p/1" in result.provenance.source_urls


def test_scrape_dry_run(monkeypatch, list_html):
    pages = {"https://example.com": list_html}

    def fake_build_loader(_cfg, **_kw):
        return _StubLoader(pages)

    monkeypatch.setattr("sandpaper_py.core._build_loader", fake_build_loader)

    cfg = ScrapeConfig(url="https://example.com", threshold=10, format="csv", output=None)
    result = scrape(cfg)
    assert result.output_path is None
    assert result.rows == 12


def test_scrape_dedupe(monkeypatch, list_html):
    pages = {
        "https://example.com/p/1": list_html,
        "https://example.com/p/2": list_html,
    }

    def fake_build_loader(_cfg, **_kw):
        return _StubLoader(pages)

    monkeypatch.setattr("sandpaper_py.core._build_loader", fake_build_loader)

    cfg = ScrapeConfig(
        page_template="https://example.com/p/{page}",
        pages="1-2",
        threshold=10,
        deduplicate=True,
    )
    result = scrape(cfg)
    assert result.rows == 12
