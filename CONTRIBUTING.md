# Contributing to SandPaper

Thank you for considering a contribution. SandPaper is small enough that one file can carry a feature end to end, and big enough that the seven-step pipeline (loader → extractor → post-processing → exporter, plus follow / picker / API / CLI) is worth understanding before you cut. This doc covers the ground rules.

## Quick links

* [INSTALLATION.md](INSTALLATION.md) - getting the package running locally.
* [INTERNAL.md](INTERNAL.md) - architecture notes and the active backlog (this file is gitignored).
* [README.md](README.md) - user-facing docs and the CLI surface.

## Development setup

```bash
git clone https://github.com/Aaryan-Dadu/SandPaper
cd SandPaper
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev,all]"
playwright install
pre-commit install
```

That is it. You should now have:

* The `sandpaper` CLI on your PATH.
* `pytest`, `ruff`, `mypy` available.
* Pre-commit hooks that run on every git commit.

## Layout

```
src/sandpaper_py/
  __init__.py            public API (re-exports)
  cli.py                 Click entry: run, watch, schedule, pick, serve, preset, profile, config
  menu.py                interactive prompts (`sandpaper interactive`)
  core.py                scrape() orchestration: list → follow → post-process → export
  config.py              ScrapeConfig dataclass + load/save TOML
  presets.py             per-site presets (host-keyed configs)
  pagination.py          {page} expansion + rel="next" detection
  schema.py              type inference + column stats + coerce_dataframe
  provenance.py          metadata sidecar + quality report writer
  plugins.py             entry-point lookup for loaders / extractors / exporters
  visual.py              pattern picker (JS overlay + Python wrapper) and login session
  api.py                 FastAPI app: /api/scrape, /api/scrape/stream (SSE)
  watch.py               watch-and-rerun, cron schedule
  robots.py              robots.txt parser cache
  throttle.py            per-host rate limiter (RateLimiter)
  exceptions.py          SandpaperError tree
  types.py               LoadResult, ExtractedTable, Provenance, ScrapeResult
  utils.py               logging, URL/filename validators, page-range parser, HTMLCache, UA pool
  loaders/
    base.py              PageLoader Protocol
    playwright_loader.py sync Playwright loader (default)
    async_loader.py      async Playwright loader (`--async`)
  extractors/
    base.py              Extractor Protocol
    heuristic.py         record-aware heuristic + table-first
    selector.py          CSS selector + selector@attr + row-scoped
  exporters/
    base.py              shared helpers (atomic write, padding, normalize, safe_dataframe)
    csv_exporter.py
    json_exporter.py     JSON + JSONL
    excel_exporter.py    [excel]
    parquet_exporter.py  [parquet]
    sqlite_exporter.py
tests/
.github/workflows/       ci.yml, release.yml
```

## Workflow

1. Open or take an issue. For substantial changes, comment your intended approach first.
2. Branch from main: `git checkout -b feat/short-name`.
3. Write or update tests in `tests/` first when feasible. The codebase has a stub-loader pattern (see `tests/test_core.py` and `tests/test_follow.py`) that lets you run the full `scrape()` pipeline against canned HTML, no browser needed.
4. Implement the change. Keep the pipeline boundaries clean: a feature is usually one new function + one CLI flag + one `ScrapeConfig` field.
5. Run the local checks below.
6. Open a PR. Keep it focused on one concern per PR.

## Local checks

These run in CI and must all pass.

```bash
ruff check src tests
ruff format --check src tests
mypy src/sandpaper_py
pytest -v
```

If you want one command:

```bash
ruff check src tests && ruff format --check src tests && mypy src/sandpaper_py && pytest -v
```

Pre-commit auto-runs ruff and ruff-format on commit. To run all hooks against the whole tree:

```bash
pre-commit run --all-files
```

## Adding things

### Adding a new exporter

1. Create `src/sandpaper_py/exporters/<name>_exporter.py` with a class exposing `name`, `extension`, and `export(table, output_path) -> str`. Use the helpers from `exporters/base.py`: `require_table`, `normalize_to_dataframe`, `atomic_write_path`, `replace_atomic`, `resolve_path`, `safe_dataframe`.
2. Re-export it from `exporters/__init__.py`.
3. Register an entry point in `pyproject.toml` under `[project.entry-points."sandpaper.exporters"]`.
4. The CLI's `--format` choices are computed at parse time from the plugin registry, so the new format auto-appears in `--help`. No CLI edits required.
5. Add tests in `tests/test_exporters.py` (round trips, edge cases like missing values).

### Adding a new extractor

1. Create `src/sandpaper_py/extractors/<name>.py` implementing `extract(html, source_url) -> ExtractedTable`.
2. Re-export from `extractors/__init__.py`.
3. Register under `[project.entry-points."sandpaper.extractors"]`.
4. The CLI auto-discovers it via the same plugin registry as exporters.
5. Add tests covering the happy path + at least one degenerate input (empty body, malformed HTML).

### Adding a new loader

1. Create `src/sandpaper_py/loaders/<name>_loader.py` implementing `PageLoader` (`load(url) -> LoadResult` and `close()`).
2. Re-export from `loaders/__init__.py`.
3. Register under `[project.entry-points."sandpaper.loaders"]`.
4. To swap loader from the CLI, extend `core._build_loader` and add a `--loader` flag.

### Adding a CLI flag

1. Add the flag to `_common_scrape_options` in `cli.py` so it lands on `run`, `watch`, `schedule`, and `preset save` together.
2. Add the corresponding field to `ScrapeConfig` in `config.py` with a sensible default.
3. Read it in `_config_from_options` in `cli.py`.
4. Use it inside `core.py` (or wherever the feature lives).
5. If it changes scrape behavior in a visible way, record it in the `Provenance.options` dict in `core.scrape()`.
6. Add a test that hits `sandpaper run --help` and asserts the flag is exposed.

## Test conventions

* All tests run offline by default. Tests that need a real browser are marked `@pytest.mark.browser` and excluded from default runs.
* The stub-loader pattern (a class with `load(url) -> LoadResult` and `close()`) is the standard way to drive `scrape()` end-to-end. See `tests/test_follow.py::_StubLoader` for a fuller example with URL-pattern-based responses.
* Fixture HTML lives in `tests/fixtures/`. Add a new fixture when you need a structurally different page (don't bloat existing fixtures).
* Each PR should add at least one test for the change. Tests don't need to be exhaustive; they need to make regressions visible.

## Style and conventions

* Python 3.9 baseline. `from __future__ import annotations` is on by default in new modules so we can write `dict[str, list[str]]` style hints, but runtime code targeting py3.9 must use `Optional[X]` / `Union[X, Y]` from `typing` rather than `X | None` syntax (we ignore the corresponding ruff `UP` rules for this reason).
* Type hints on all public functions and on complex internal helpers. Skip them on trivial one-liners only.
* Prefer small standalone functions over methods on big classes. The post-processing pipeline in `core.py` is a good model: each step is a tiny pure function + one orchestrator.
* No backwards-compatibility shims. If you remove a feature, remove it cleanly. Old configs that reference removed fields will be ignored by `load_config` (it filters by current `ScrapeConfig` keys), so no migration needed.
* Comments only for *why*, not *what*. Identifier names should carry the *what*.
* Avoid em-dashes in user-facing text. Plain ASCII reads cleaner across terminals and tools.
* Logging uses `log = logging.getLogger("sandpaper.<module>")`. Status messages go to logs, not `print`. The CLI sets the level via `--log-level`.

## Commit messages

* Imperative mood, concise subject, body for context if needed.
* Reference the issue / observation in the body when relevant.

Examples:

```
feat: add async Playwright loader for high-concurrency scrapes

Closes the "concurrency uses threads, not asyncio" item in INTERNAL.md.
Backed by AsyncPlaywrightLoader; opt-in via --async on `run`.
```

```
fix: harden _strip_noise against tags decomposed mid-iteration

bs4 detaches tag.attrs to None when an ancestor is decomposed.
Skip such tags instead of letting tag.get(...) crash.
```

## Release process

Maintainers handle releases. The flow:

1. Bump `version` in `pyproject.toml`.
2. Update CHANGELOG (if present) or release notes draft.
3. Tag and push: `git tag vX.Y.Z && git push origin main --tags`.
4. The `release.yml` workflow runs on the tag, builds with `python -m build`, and publishes via OIDC trusted publishing.

Pre-1.0, breaking changes can land on minor bumps but must be called out in the release body.

## Reporting bugs

* GitHub issues. Include:
  * `sandpaper --version` output
  * Python version (`python --version`)
  * OS
  * The exact command you ran and what happened
  * A minimal reproducible HTML or URL when relevant
* For Playwright crashes, attaching the relevant lines from the run with `--log-level debug` is gold.

## Asking for help

* GitHub Discussions (if enabled) for design questions.
* GitHub Issues for bugs and concrete feature asks.

## License

By contributing you agree that your contributions are licensed under the MIT License (see [LICENSE](LICENSE)).
