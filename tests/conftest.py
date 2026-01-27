from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def list_html() -> str:
    return (FIXTURES / "list.html").read_text(encoding="utf-8")


@pytest.fixture
def no_body_html() -> str:
    return (FIXTURES / "no_body.html").read_text(encoding="utf-8")


@pytest.fixture
def cards_html() -> str:
    return (FIXTURES / "cards.html").read_text(encoding="utf-8")


@pytest.fixture
def table_html_doc() -> str:
    return (FIXTURES / "table.html").read_text(encoding="utf-8")


@pytest.fixture
def articles_list_html() -> str:
    return (FIXTURES / "articles_list.html").read_text(encoding="utf-8")


def article_detail_html(slug: str) -> str:
    return f"""<!doctype html><html><body>
      <article class='detail'>
        <h1 class='heading'>{slug.title()} Title</h1>
        <div class='body'><p>The full body for {slug}, with more text than the lede.</p></div>
        <ul class='tags'><li class='tag'>news</li><li class='tag'>{slug}</li></ul>
        <span class='author'>Author {slug.title()}</span>
      </article>
    </body></html>"""
