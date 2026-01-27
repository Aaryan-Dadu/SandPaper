"""Tests for the items addressed in the 'Known limits / future work' pass.

Covered:
* Dynamic --format / --extractor Click choices respect plugin registry
* Shared RateLimiter across concurrent threads
* Proxy rotation pool (CLI parsing + LoaderOptions wiring)
* CSV --typed export
* `sandpaper profile` command surface
* `--profile NAME` resolves storage_state path
* `--async` flag exposed on run
* SSE endpoint registered on the FastAPI app (when fastapi is installed)
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from click.testing import CliRunner

from sandpaper_py.cli import _available_extractors, _available_formats, _load_proxies, main
from sandpaper_py.config import ScrapeConfig
from sandpaper_py.exporters import CSVExporter
from sandpaper_py.loaders.playwright_loader import LoaderOptions, PlaywrightLoader
from sandpaper_py.throttle import RateLimiter
from sandpaper_py.types import ExtractedTable

# -- dynamic CLI choices


def test_available_formats_contains_builtins():
    formats = _available_formats()
    for name in ("csv", "json", "jsonl", "excel", "parquet", "sqlite"):
        assert name in formats


def test_available_extractors_contains_builtins():
    extractors = _available_extractors()
    assert "heuristic" in extractors
    assert "selector" in extractors


# -- proxy rotation


def test_load_proxies_csv():
    assert _load_proxies("http://a:1, http://b:2", None) == ["http://a:1", "http://b:2"]


def test_load_proxies_file(tmp_path: Path):
    f = tmp_path / "proxies.txt"
    f.write_text("http://a:1\n# comment\nhttp://b:2\n\n")
    assert _load_proxies(None, str(f)) == ["http://a:1", "http://b:2"]


def test_load_proxies_file_overrides_csv(tmp_path: Path):
    f = tmp_path / "proxies.txt"
    f.write_text("http://from-file:1\n")
    assert _load_proxies("http://from-csv:1", str(f)) == ["http://from-file:1"]


def test_loader_options_carry_proxies():
    opts = LoaderOptions(proxies=("http://a:1", "http://b:2"))
    assert opts.proxies == ("http://a:1", "http://b:2")


# -- shared RateLimiter


def test_loader_accepts_shared_limiter():
    shared = RateLimiter(2.0)
    loader = PlaywrightLoader(LoaderOptions(rate_per_second=10.0), shared_limiter=shared)
    assert loader._limiter is shared


def test_loader_builds_own_limiter_when_none_passed():
    loader = PlaywrightLoader(LoaderOptions(rate_per_second=2.0))
    assert isinstance(loader._limiter, RateLimiter)


# -- CSV typed mode


def test_csv_typed_export_writes_coerced_values(tmp_path: Path):
    table = ExtractedTable(
        columns={
            "n": ["1", "2", "3"],
            "price": ["$10.00", "$20.50", "$5.99"],
        }
    )
    out = tmp_path / "typed.csv"
    CSVExporter(typed=True).export(table, out)
    rows = list(csv.reader(out.open()))
    assert rows[0] == ["n", "price"]
    # n was inferred as integer; price as currency. Both should be numeric strings.
    assert rows[1][0] == "1"
    assert float(rows[1][1]) == 10.0


# -- profile command surface


def test_profile_help_lists_subcommands():
    runner = CliRunner()
    result = runner.invoke(main, ["profile", "--help"])
    assert result.exit_code == 0
    for sub in ("login", "list", "path", "delete"):
        assert sub in result.output


def test_profile_list_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sandpaper_py.cli._profiles_dir", lambda: tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["profile", "list"])
    assert result.exit_code == 0
    assert "no profiles" in result.output.lower()


def test_profile_path_command(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sandpaper_py.cli._profiles_dir", lambda: tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["profile", "path", "myprofile"])
    assert result.exit_code == 0
    assert "myprofile.json" in result.output


def test_profile_delete_existing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sandpaper_py.cli._profiles_dir", lambda: tmp_path)
    profile = tmp_path / "site.json"
    profile.write_text("{}")
    runner = CliRunner()
    result = runner.invoke(main, ["profile", "delete", "site"])
    assert result.exit_code == 0
    assert "deleted" in result.output.lower()
    assert not profile.exists()


def test_profile_delete_missing_is_idempotent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sandpaper_py.cli._profiles_dir", lambda: tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["profile", "delete", "ghost"])
    assert result.exit_code == 0
    assert "no profile" in result.output.lower()


# -- --profile NAME resolution


def test_profile_flag_resolves_to_storage_state(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sandpaper_py.cli._profiles_dir", lambda: tmp_path)
    profile = tmp_path / "site.json"
    profile.write_text("{}")
    from sandpaper_py.cli import _resolve_storage_state

    assert _resolve_storage_state(None, "site") == str(profile)


def test_profile_flag_missing_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sandpaper_py.cli._profiles_dir", lambda: tmp_path)
    import click as click_module

    from sandpaper_py.cli import _resolve_storage_state

    with pytest.raises(click_module.UsageError, match="not found"):
        _resolve_storage_state(None, "ghost")


def test_profile_flag_explicit_storage_state_wins(tmp_path: Path):
    from sandpaper_py.cli import _resolve_storage_state

    explicit = str(tmp_path / "explicit.json")
    assert _resolve_storage_state(explicit, "anything") == explicit


# -- --async flag


def test_run_help_exposes_async_flag():
    runner = CliRunner()
    result = runner.invoke(main, ["run", "--help"])
    assert result.exit_code == 0
    assert "--async" in result.output


def test_run_help_exposes_proxy_flags():
    runner = CliRunner()
    result = runner.invoke(main, ["run", "--help"])
    assert result.exit_code == 0
    assert "--proxies" in result.output
    assert "--proxy-list" in result.output
    assert "--profile" in result.output


# -- async loader (smoke; we don't actually launch a browser)


def test_async_loader_imports_cleanly():
    from sandpaper_py.loaders import AsyncPlaywrightLoader

    loader = AsyncPlaywrightLoader(LoaderOptions(rate_per_second=0))
    assert loader is not None


def test_async_mode_in_config_round_trip():
    cfg = ScrapeConfig(async_mode=True)
    assert cfg.async_mode is True


# -- SSE endpoint


def test_sse_endpoint_registered():
    pytest.importorskip("fastapi")
    from sandpaper_py.api import create_app

    app = create_app()
    routes = {getattr(r, "path", None) for r in app.routes}
    assert "/api/scrape/stream" in routes
    assert "/api/scrape" in routes
