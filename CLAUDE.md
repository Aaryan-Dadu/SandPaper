# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install for development (all optional deps + dev tools)
pip install -e ".[dev,all]"
playwright install        # required – downloads Chromium binaries

# Setup pre-commit hooks (runs ruff and whitespace checks on commit)
pre-commit install

# Lint
ruff check src tests

# Format
ruff format src tests

# Type check
mypy src/sandpaper_py

# Run all tests
pytest -v

# Run a single test file
pytest tests/test_core.py -v

# Run tests matching a name pattern
pytest -v -k "test_follow"

# Skip slow/browser tests
pytest -v -m "not slow and not browser"
```

CI runs `ruff check`, `ruff format --check`, `mypy`, and `pytest` (Python 3.9–3.12, Ubuntu). All four must pass before merging.

## Architecture

SandPaper is a Playwright-based web scraper packaged as `sandpaper-py`. The entry point is `sandpaper_py.cli:main` (Click). The public programmatic API is `scrape()`, `scrape_url()`, and `scrape_urls()` from `sandpaper_py.api`.

### Data flow

```
CLI / API → ScrapeConfig → core.scrape()
              ↓
         PlaywrightLoader (loads HTML)
              ↓
         Extractor (heuristic | selector)  →  ExtractedTable {columns: dict[str, list[str]]}
              ↓
         _post_process() (trim, rename, keep/drop, required, schema lock)
              ↓
         Exporter (csv | json | jsonl | excel | parquet | sqlite)
              ↓
         ScrapeResult {table, provenance, output_path}
```

All internal data moves as `dict[str, list[str]]` (column-oriented), not row-oriented. Conversion to records (`list[dict]`) happens only at export or when the caller calls `.records()`.

### Key modules

| Module | Role |
|--------|------|
| `config.py` | `ScrapeConfig` dataclass — all scrape options with defaults. `merge()` merges a preset onto a config. Global config stored as TOML at `platformdirs.user_config_dir("sandpaper")/config.toml`. |
| `core.py` | `scrape()` — the central orchestrator. Handles serial, concurrent (ThreadPoolExecutor), async (asyncio + Playwright), and auto-paginate modes. Also runs follow/detail-page joins. |
| `plugins.py` | Discovers exporters, extractors, and loaders via `importlib.metadata` entry points (groups `sandpaper.exporters`, `sandpaper.extractors`, `sandpaper.loaders`). All three subsystems are pluggable. |
| `types.py` | Shared dataclasses: `LoadResult`, `ExtractedTable`, `Provenance`, `ScrapeResult`. |
| `loaders/playwright_loader.py` | Sync Playwright loader — handles retries, rate limiting, proxy rotation, UA rotation, robots.txt, HTML caching, overlay dismissal. |
| `loaders/async_loader.py` | Async Playwright loader used when `async_mode=True` and multiple URLs. |
| `extractors/heuristic.py` | Record-aware DOM heuristic: strips noise elements, finds largest repeating sibling group or `<table>`, emits one record per row element. |
| `extractors/selector.py` | CSS selector extractor: supports `selector@attr` syntax for attribute extraction and `row_selector` for row-scoped extraction. |
| `exporters/` | One class per format. All implement `export(table: ExtractedTable, path: str) -> str`. |
| `pagination.py` | `expand_template()` for `{page}` templates, `detect_next_link()` for `rel="next"` auto-pagination, `parse_page_range()` for `"1-5"` / `"1,3,5"` syntax. |
| `presets.py` | Per-site TOML presets stored in config dir. `load_preset().merge(cfg)` applies preset defaults below explicit CLI flags. |
| `visual.py` | Visual selector picker — opens Chromium with an injected overlay, walks the DOM to find the repeating row container, writes a preset. |
| `api.py` | FastAPI HTTP server + Jinja2 web UI (`sandpaper serve`). Requires `[api]` extra. |
| `watch.py` | `sandpaper watch` (fixed interval) and `sandpaper schedule` (cron via APScheduler). |
| `recipe_runner.py` / `recipes.py` | Record-then-replay session system. Recipes are JSON files with an action vocabulary (click, type, navigate, extract). |
| `provenance.py` | Writes `<output>.meta.json` sidecar and `<output>.quality.json` quality report. |
| `schema.py` | Type inference and column stats used by the quality report and `--typed` coercion. |
| `throttle.py` | `RateLimiter` (token bucket) shared across threads in concurrent mode. |

### Extension points

Third-party packages can add exporters, extractors, or loaders via `pyproject.toml` entry points:

```toml
[project.entry-points."sandpaper.exporters"]
yaml = "your_pkg.yaml_exporter:YAMLExporter"
```

The class must implement the matching protocol (`Exporter`, `Extractor`, or `PageLoader`).

## Python compatibility

The package targets Python 3.9–3.12. Use `typing.Optional[X]` and `typing.Union[X, Y]` rather than `X | Y` or `X | None` (3.10+ syntax). Use `Dict`, `List`, `Tuple` from `typing` for annotations — `ruff` is configured to ignore the UP006/UP007/UP035/UP045 rules that would flag these.
