from sandpaper_py.utils import (
    get_site_name,
    is_valid_url,
    merge_columns,
    sanitize_filename,
)


def test_sanitize_filename_strips_bad_chars():
    assert sanitize_filename("a/b:c?d") == "a_b_c_d"


def test_sanitize_filename_falls_back():
    assert sanitize_filename("...") == "output"
    assert sanitize_filename("") == "output"


def test_sanitize_filename_truncates():
    name = sanitize_filename("a" * 500)
    assert len(name) == 200


def test_get_site_name():
    assert get_site_name("https://www.example.com/path") == "example"
    assert get_site_name("https://blog.example.co.uk") == "example"
    assert get_site_name("https://shop.acme.io") == "acme"
    assert get_site_name("not a url") == "site"


def test_is_valid_url():
    assert is_valid_url("https://example.com")
    assert is_valid_url("http://localhost:8000")
    assert not is_valid_url("ftp://example.com")
    assert not is_valid_url("")
    assert not is_valid_url("example.com")


def test_merge_columns():
    target = {"a": [1, 2]}
    incoming = {"a": [3], "b": [9]}
    merge_columns(target, incoming)
    assert target == {"a": [1, 2, 3], "b": [9]}
