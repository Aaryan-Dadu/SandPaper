# SandPaper

SandPaper scrapes web pages with Playwright and writes structured data to CSV, JSON, Excel, Parquet, or SQLite. It ships with an interactive CLI, a non-interactive CLI for scripting, an HTTP API, a small web UI, a visual selector picker, and a session recorder that replays as recipes.

**Docs**: [Getting started](docs/getting-started.md) · [User guide](docs/user-guide.md) · [Installation](INSTALLATION.md) · [Contributing](CONTRIBUTING.md)

## Install

From PyPI:

```bash
pip install sandpaper-py
playwright install
```

With optional features:

```bash
pip install "sandpaper-py[excel,parquet,api,schedule]"
```

From source:

```bash
git clone https://github.com/Aaryan-Dadu/SandPaper
cd SandPaper
pip install -e ".[dev,all]"
playwright install
```

`playwright install` downloads the browser binaries the loader needs. The first scrape after a fresh install will fail without it.

## Quick start

Interactive mode:

```bash
sandpaper
```

Single-shot non-interactive scrape:

```bash
sandpaper run --url https://quotes.toscrape.com -o quotes.csv
```

Multi-page with a template:

```bash
sandpaper run \
  --template "https://quotes.toscrape.com/page/{page}/" \
  --pages 1-5 \
  -o quotes.csv
```

Auto-paginate by following `rel="next"` links:

```bash
sandpaper run --url https://quotes.toscrape.com --auto-paginate -o quotes.csv
```

CSS selector extraction:

```bash
sandpaper run \
  --url https://quotes.toscrape.com \
  --extractor selector \
  --selectors '{"quote": "span.text", "author": "small.author"}' \
  -o quotes.json -f json
```

Concurrent multi-page:

```bash
sandpaper run \
  --template "https://example.com/page/{page}" \
  --pages 1-50 \
  --concurrency 4 --rate 2 \
  -o data.parquet -f parquet
```

Dry run (preview without writing):

```bash
sandpaper run --url https://example.com --dry-run
```

## Programmatic API

```python
from sandpaper_py import scrape, ScrapeConfig

cfg = ScrapeConfig(
    page_template="https://quotes.toscrape.com/page/{page}/",
    pages="1-3",
    output="quotes.csv",
    format="csv",
    threshold=10,
)
result = scrape(cfg)
print(result.rows, result.columns)
```

Or use the helpers:

```python
from sandpaper_py import scrape_url, scrape_urls

scrape_url("https://example.com", output="example.csv")
scrape_urls(["https://a.com", "https://b.com"], output="combined.json", format="json")
```

## Commands

| Command | Purpose |
|---------|---------|
| `sandpaper` | Interactive prompt-driven scrape. |
| `sandpaper run` | Non-interactive scrape from flags. |
| `sandpaper watch --every <sec>` | Re-run on a fixed interval. |
| `sandpaper schedule --cron "..."` | Run on a cron schedule. |
| `sandpaper pick <url>` | Open a visual selector picker. |
| `sandpaper serve` | Start the HTTP API and web UI. |
| `sandpaper preset {list,save,show,delete}` | Manage per-site presets. |
| `sandpaper config {path,show,init}` | Manage the global config file. |

Run `sandpaper <command> --help` for full options.

## Output formats

`-f csv` (default), `json`, `jsonl`, `excel`, `parquet`, `sqlite`.

`excel` requires `pip install "sandpaper-py[excel]"`. `parquet` requires `[parquet]`.

## Extractors

* `heuristic` (default) groups text by `tag-class` and keeps any column with at least `--threshold` items and more than one unique value. Good for generic scrapes where the structure is unknown.
* `selector` takes a JSON map of column to CSS selector and pulls one column per selector. Use `sandpaper pick` to build the map by clicking.

## Presets

Saved per-site configurations live in the user config directory (see `sandpaper config path`). A preset name that matches a URL host is auto-suggested in interactive mode.

```bash
sandpaper preset save quotes.toscrape.com \
  --extractor selector \
  --selectors '{"quote": "span.text", "author": "small.author"}' \
  --threshold 1
sandpaper run --url https://quotes.toscrape.com --preset quotes.toscrape.com
```

## Web UI and HTTP API

```bash
pip install "sandpaper-py[api]"
sandpaper serve
```

Open `http://127.0.0.1:8000` for the form-based UI, or POST to `/api/scrape`:

```bash
curl -X POST http://127.0.0.1:8000/api/scrape \
  -H 'content-type: application/json' \
  -d '{"url": "https://quotes.toscrape.com", "format": "json"}'
```

## Visual selector picker

```bash
sandpaper pick https://quotes.toscrape.com --save-preset quotes
```

A real browser opens with an overlay. Click any element inside one of the repeating items (a card, a row, a search result). SandPaper walks up the DOM, finds the row container, highlights every sibling row in green, and shows a side panel with `&uarr; Broader` / `&darr; Narrower` controls if it picked the wrong level.

Each subsequent click captures a field. The selector is computed relative to the row container, so the same field is automatically pulled out of every other row. The side panel shows a live 5-row preview table that updates as you click. Per-field undo buttons remove a column. Press Esc to finish.

Output is a complete preset (`row_selector` + `selectors`). With `--save-preset NAME`, sandpaper writes it directly to your preset library:

```bash
sandpaper run --url https://quotes.toscrape.com --preset quotes -o quotes.json -f json
```

Or use the row-scoped extraction directly without going through the picker:

```bash
sandpaper run --url https://quotes.toscrape.com \
  -e selector \
  --row-selector "div.quote" \
  --selectors '{"text": "span.text", "author": "small.author"}' \
  -o quotes.json -f json
```

Row-scoped extraction guarantees per-row alignment: each row in the output corresponds to exactly one container element, no positional zipping across mismatched groups.

## Watch and schedule

```bash
sandpaper watch --url https://example.com --every 600 -o feed.csv
sandpaper schedule --url https://example.com --cron "*/15 * * * *" -o feed.csv
```

`schedule` requires `pip install "sandpaper-py[schedule]"`.

## Recipes (record once, replay anywhere)

When a scrape needs interaction (login, search, paginate, follow), record what you do once:

```bash
sandpaper record https://example.com/search --output search.recipe.json
```

A real Chromium opens with a recorder toolbar. Type, click, and navigate normally — every action is captured. Click "Capture extract" to launch the pattern picker mid-recording (point at the row pattern + each field). Click "Save & finish" to write the recipe.

Replay it any time, with optional parameter overrides:

```bash
sandpaper run-recipe search.recipe.json --param query=laptops -o results.json
```

Recipes are JSON, declarative, and shareable. Full schema and action vocabulary in the [User guide](docs/user-guide.md#recipes).

## Detail-page join

The most common scraping pattern: list page → click each item → scrape detail → merge. Express it with one flag.

```bash
sandpaper run \
  --url https://news.example.com/articles \
  -e selector \
  --row-selector "article.post" \
  --selectors '{"title": "h2.title", "summary": "p.lede", "url": "a.title-link@href"}' \
  --follow url \
  --follow-selectors '{"body": "div.body", "author": "span.author"}' \
  --follow-concurrency 4 \
  -o articles.json -f json
```

Each row from the list page is enriched with the detail-page fields, joined by the URL extracted via the `selector@attr` syntax. Output is one row per article with both summary and full body.

* `selector@attr` extracts the named attribute (most often `href` or `src`) instead of text content.
* Relative URLs are resolved against the list page's URL automatically; `--follow-url-prefix https://example.com` overrides the base.
* `--follow-concurrency N` runs detail fetches in parallel with per-thread persistent loaders.
* Failed detail pages are skipped silently by default. `--follow-fail-on-error` aborts the run on the first failure.

## Cleaner output

The heuristic extractor is record-aware. On any page that contains a repeating row pattern (product cards, company listings, search results) or an HTML `<table>`, SandPaper finds the row container and pulls one row per repeating element. Each row is a clean `{column: value}` record. No positional zipping across mismatched groups, no `tag-class` key noise, no filter sidebar leaking into the data.

Default pipeline:

1. Strip `script`, `style`, `nav`, `header`, `footer`, `form`, `aside`, and any element whose class/id/role/aria-label matches a noise keyword (`cookie`, `popup`, `sidebar`, `subscribe`, ...).
2. If a `<table>` with `>= threshold/2` rows exists, extract its headers and cells directly.
3. Otherwise find the parent whose direct children form the largest, most homogeneous repeating group. Each child becomes one record.
4. In each record, only true leaf tags publish text (so `<a><h2>Name</h2></a>` yields one column, not two).
5. Post-clean: drop empty/single-value columns, merge columns with identical value sequences.

Knobs that control output quality:

```bash
--min-text-length 2 --max-text-length 800
--near-dup-ratio 0.9
--max-fields-per-record 20
--no-prefer-records          # fall back to the flat heuristic
--block-resources image,media,font   # default; speeds up scrapes
--no-dismiss-overlays        # disable cookie/popup auto-dismiss
```

```bash
sandpaper run --url https://example.com \
  --min-text-length 2 --max-text-length 800 --near-dup-ratio 0.9 \
  -o clean.json -f json --normalize-keys --quality-report
```

`--normalize-keys` slugifies JSON keys, `--sort-keys` makes output deterministic, `--keep-empty-columns` retains all-empty columns, `--csv-safe` neutralizes spreadsheet formula injection. `--typed` runs schema coercion before Parquet/Excel/SQLite export.

## Data quality controls

Post-processing runs after extraction and before export. Use these to shape the output without writing Python:

```bash
sandpaper run --url ... \
  --rename-columns '{"raw_name":"name","raw_price":"price"}' \
  --keep-columns name,price,url \
  --required-columns name,price \
  --schema-lock-after 5 \
  --null-policy null \
  -o out.json -f json
```

* `--rename-columns JSON` — pre-export rename map. Collisions get a numeric suffix.
* `--keep-columns / --drop-columns` — whitelist or blacklist (whitelist wins).
* `--required-columns` — drop rows that are missing a value in any of these columns.
* `--no-trim` — disable whitespace trimming on cell values (default on).
* `--schema-lock-after N` — infer schema from the first N rows; drop columns absent there from the rest.
* `--null-policy {empty,null,skip}` — JSON-only: `empty` keeps `""`, `null` writes `null`, `skip` omits the key from the row.

## In-memory results

```python
from sandpaper_py import scrape_url

result = scrape_url("https://quotes.toscrape.com")
df = result.to_pandas(typed=True)
rows = result.records()
```

`result.to_polars()` is also available if Polars is installed.

## Caching, throttling, anti-block

```bash
sandpaper run --url https://example.com \
  --cache-dir .sp-cache --cache-ttl 3600 \
  --rotate-user-agents --random-delay 800 --rate 2
```

The cache is a per-URL SHA1-keyed local HTML store; warm hits skip the browser entirely. UA rotation picks from a built-in pool. `--random-delay` adds 0..N ms uniform jitter before each request.

## Provenance and quality report

`--provenance` writes a `<output>.meta.json` sidecar with source URLs, timestamps, options, and selectors. `--quality-report` writes `<output>.quality.json` with row counts, inferred types, null ratios, and per-column samples.

## Plugin system

Custom exporters, extractors, and loaders are picked up from entry points:

```toml
[project.entry-points."sandpaper.exporters"]
yaml = "your_pkg.yaml_exporter:YAMLExporter"

[project.entry-points."sandpaper.extractors"]
microdata = "your_pkg.microdata:MicrodataExtractor"
```

Implement the matching protocol (`Exporter`, `Extractor`, or `PageLoader` from `sandpaper_py`) and the format becomes available as `-f yaml`, `-e microdata`, etc.

## Project layout

```
src/sandpaper_py/
  cli.py               CLI entry (Click)
  menu.py              Interactive prompts
  core.py              scrape() and helpers
  config.py            Config file handling
  presets.py           Per-site presets
  pagination.py        URL templates and next-link detection
  schema.py            Type inference and column stats
  provenance.py        Sidecar metadata writer
  plugins.py           Entry-point lookup
  visual.py            Visual selector picker
  api.py               HTTP API and web UI server
  watch.py             Watch and schedule modes
  loaders/             Page loaders (Playwright)
  extractors/          Heuristic and selector extractors
  exporters/           CSV, JSON, JSONL, Excel, Parquet, SQLite
tests/
.github/workflows/     CI and release
```

## Development

```bash
pip install -e ".[dev,all]"
playwright install
pre-commit install
ruff check src tests
ruff format src tests
mypy src/sandpaper_py
pytest -v
```

## License

MIT, see [LICENSE](LICENSE).
