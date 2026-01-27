import pytest

from sandpaper_py.exceptions import ConfigError
from sandpaper_py.pagination import detect_next_link, expand_template, is_same_origin
from sandpaper_py.utils import parse_page_range


def test_expand_template_basic():
    urls = expand_template("https://e.com/p/{page}", [1, 2, 3])
    assert urls == [
        "https://e.com/p/1",
        "https://e.com/p/2",
        "https://e.com/p/3",
    ]


def test_expand_template_requires_placeholder():
    with pytest.raises(ConfigError):
        expand_template("https://e.com/p/", [1])


def test_parse_page_range_simple():
    assert parse_page_range("1-3") == [1, 2, 3]


def test_parse_page_range_mixed():
    assert parse_page_range("1-3,5,7-8") == [1, 2, 3, 5, 7, 8]


def test_parse_page_range_invalid():
    with pytest.raises(ConfigError):
        parse_page_range("3-1")
    with pytest.raises(ConfigError):
        parse_page_range("")


def test_detect_next_link_rel_next(list_html):
    next_url = detect_next_link(list_html, "https://e.com/page/1")
    assert next_url == "https://e.com/page/2"


def test_detect_next_link_none():
    assert detect_next_link("<html><body></body></html>", "https://e.com") is None


def test_is_same_origin():
    assert is_same_origin("https://e.com/a", "https://e.com/b")
    assert not is_same_origin("https://e.com/a", "https://other.com/a")
