# SandPaper user guide

The full reference. If you want a short tour first, read [Getting started](getting-started.md).

## Table of contents

1. [Concepts](#concepts)
2. [Commands](#commands)
3. [Extractors](#extractors)
4. [Output formats](#output-formats)
5. [Pagination](#pagination)
6. [Detail-page join (`--follow`)](#detail-page-join---follow)
7. [Recipes](#recipes)
8. [Presets](#presets)
9. [Profiles (logged-in scrapes)](#profiles-logged-in-scrapes)
10. [Data quality controls](#data-quality-controls)
11. [Performance and politeness](#performance-and-politeness)
12. [Web UI and HTTP API](#web-ui-and-http-api)
13. [Programmatic API](#programmatic-api)
14. [Plugins](#plugins)
15. [Configuration files](#configuration-files)
16. [Troubleshooting](#troubleshooting)

---

## Concepts

A scrape in SandPaper is a pipeline of four stages:

1. **Loader** — drives a real browser via Playwright. Handles retries, rate limiting, robots.txt, cookies, sessions, proxies, resource blocking.
2. **Extractor** — turns rendered HTML into a `{column: list_of_values}` table. Two builtins: a record-aware *heuristic* and a CSS-*selector* extractor.
3. **Post-processing** — trim cells, rename, drop, require, schema-lock, deduplicate.
4. **Exporter** — writes the table to CSV, JSON, JSONL, Excel, Parquet, or SQLite.

Two extra layers wrap the pipeline:

* **Follow** — after the list extract, follow a URL field on each row into a detail page and merge fields from there.
* **Recipes** — replace the linear pipeline with a sequence of browser actions (goto, fill, click, paginate, extract, follow). Used for scrapes that need state, like logging in or filling a search form.

Every scrape ends in a `ScrapeResult` that holds the table, the provenance metadata, and (if asked) the on-disk output path.

---

## Commands

Top-level commands:

| Command | Purpose |
|---------|---------|
| `sandpaper` | Open the interactive prompt-driven scrape menu. |
| `sandpaper run` | Non-interactive scrape from CLI flags. |
| `sandpaper watch --every <sec>` | Run on a fixed interval. |
| `sandpaper schedule --cron "..."` | Run on a cron schedule (blocking). |
| `sandpaper pick <url>` | Pattern-aware visual element picker. |
| `sandpaper record <url> -o <recipe>` | Record a browser session as a replayable recipe. |
| `sandpaper run-recipe <file>` | Replay a recipe file. |
| `sandpaper serve` | Start the HTTP API and web UI. |
| `sandpaper preset {list,save,show,delete}` | Manage per-site presets. |
| `sandpaper profile {login,list,path,delete}` | Manage saved login sessions. |
| `sandpaper config {path,show,init}` | Manage the global config file. |

Run any with `--help` for full options. Examples in this guide assume you have run `pip install "sandpaper-py[all]"` and `playwright install`.

---

## Extractors

### `heuristic` (default)

Record-aware. Walks the DOM, drops `nav`/`header`/`footer`/`aside` elements and anything with `cookie`/`popup`/`sidebar` style class names, finds repeating sibling containers, and extracts one row per container.

Knobs:

* `--threshold N` — minimum occurrences to count as a column. Default 10.
* `--min-text-length N` / `--max-text-length N` — drop cells outside the range. Defaults 1 / 4000. The max is what kills the page-wide nav blob you see in dump-everything output.
* `--near-dup-ratio FLOAT` — drop columns where unique-value ratio is below `1 - this`. Default 0.85.
* `--max-fields-per-record N` — cap fields per record. Default 30.
* `--no-prefer-records` — disable record-set detection; flat heuristic only.

If the page contains a real `<table>` with enough rows, SandPaper extracts that directly.

### `selector`

Explicit CSS selectors per column. Two modes:

**Flat:**

```bash
sandpaper run --url ... -e selector \
  --selectors '{"title": "h2.title", "price": ".price"}'
```

Each selector independently runs against the document and the values are zipped positionally. Fast and predictable, but cardinalities must match.

**Row-scoped (recommended):**

```bash
sandpaper run --url ... -e selector \
  --row-selector "li.product" \
  --selectors '{"title": "h2.title", "price": ".price"}'
```

Iterates `soup.select(row_selector)` and runs each field selector relative to that row. Missing fields produce empty strings. This is what you almost always want — it guarantees per-row alignment.

Get the row + field selectors with `sandpaper pick <url>`.

### `selector@attr` syntax

Append `@attr` to extract an attribute instead of text:

```json
{"url": "a.title-link@href", "image": "img.cover@src"}
```

The parser is strict enough that `a[href*="@example.com"]` is not misparsed as an attribute extraction.

---

## Output formats

| `-f` | Extension | Notes |
|------|-----------|-------|
| `csv` | `.csv` | Default. Atomic write. `--csv-safe` neutralizes spreadsheet formula injection. |
| `json` | `.json` | Records (list of objects). |
| `jsonl` | `.jsonl` | Newline-delimited JSON, streamable. |
| `excel` | `.xlsx` | Needs `pip install "sandpaper-py[excel]"`. |
| `parquet` | `.parquet` | Needs `pip install "sandpaper-py[parquet]"`. |
| `sqlite` | `.db` | Plain `to_sql`. `--typed` recommended. |

Format-affecting flags:

* `--typed` — coerce to inferred types (numbers, currencies, dates, booleans) before writing. Recommended for Parquet, Excel, SQLite, and CSV when downstream consumers expect typed columns.
* `--encoding utf-8-sig` — for CSV/JSON files opened in legacy Excel.
* `--keep-empty-columns` — keep all-empty columns (default drops them).
* `--sort-keys` — sort keys in JSON output.
* `--sort-columns` — sort columns alphabetically.
* `--normalize-keys` — slugify column names (`Title!` → `title`).
* `--null-policy {empty,null,skip}` — JSON only. `empty` keeps `""`, `null` writes JSON null, `skip` omits the key.

---

## Pagination

Three strategies, pick whichever fits the site.

**URL template:**

```bash
sandpaper run --template "https://example.com/page/{page}" --pages 1-20
```

`--pages` accepts `1-5`, `7`, `1-3,5,10-12`. Capped by `--max-pages-limit` (default 10000).

**Custom URL list:**

```bash
sandpaper run --url-list https://a --url-list https://b --url-list https://c
```

Or via a recipe with parameters.

**Auto-paginate:**

```bash
sandpaper run --url https://example.com --auto-paginate --max-auto-pages 50
```

Follows `<link rel="next">`, `<a rel="next">`, anchors with text "Next" / "→" / "»", `aria-label="Next"`, or class names like `pagination__next`. Stops when no next link is found, when it crosses origins, when it loops back, or when `--max-auto-pages` is hit.

---

## Detail-page join (`--follow`)

The list-page-then-detail-page pattern. Express it with one flag.

```bash
sandpaper run \
  --url https://news.example.com/articles \
  -e selector --row-selector "article.post" \
  --selectors '{"title": "h2", "url": "a.title-link@href"}' \
  --follow url \
  --follow-selectors '{"body": "div.body", "author": "span.author"}' \
  --follow-concurrency 4 \
  -o articles.json -f json
```

* `--follow FIELD` — name of the field in the list extract whose value is a URL.
* `--follow-selectors JSON` — selectors to run on each detail page. Single-record extraction (first match wins per selector).
* `--follow-concurrency N` — parallel detail fetches. Per-thread persistent loaders.
* `--follow-fail-on-error` — abort the run on any detail-fetch failure (default skips and continues).
* `--follow-url-prefix URL` — prepended to relative URLs (default uses the list page's base).

Output is one row per list entry with both list-page columns and detail-page columns.

---

## Recipes

A recipe is a JSON file describing a sequence of browser actions. Use it when a scrape needs interaction (login, search form, multi-step navigation) or when you want to share a scrape with a teammate.

### Schema

```json
{
  "name": "amazon-search",
  "version": 1,
  "description": "Search Amazon and scrape results",
  "params": {
    "query": {"type": "string", "default": "laptops"},
    "max_pages": {"type": "int", "default": 5}
  },
  "steps": [
    {"action": "goto", "url": "https://amazon.example.com"},
    {"action": "wait_for", "selector": "input.search"},
    {"action": "fill", "selector": "input.search", "value": "{{query}}"},
    {"action": "press", "selector": "input.search", "key": "Enter"},
    {"action": "wait_for", "selector": "li.s-result-item"},
    {
      "action": "extract_paginated",
      "row_selector": "li.s-result-item",
      "selectors": {"title": "h2 a", "price": "span.price", "url": "h2 a@href"},
      "next_selector": "a.s-pagination-next",
      "max_pages": "{{max_pages}}"
    },
    {
      "action": "follow",
      "field": "url",
      "selectors": {"description": "div#productDescription", "rating": "span.review-rating"}
    }
  ],
  "output": {"path": "amazon.json", "format": "json"}
}
```

### Actions

| Action | Required keys | Optional |
|--------|---------------|----------|
| `goto` | `url` | |
| `wait_for` | one of `selector`, `load_state` | `timeout_ms` |
| `wait` | `ms` | |
| `fill` | `selector`, `value` | |
| `click` | `selector` | `wait_for_navigation: true` |
| `press` | `selector`, `key` | |
| `scroll` | | `max_scrolls`, `pause_ms` |
| `evaluate` | `script` | |
| `extract` | `selectors` (or `heuristic: true`) | `row_selector`, `threshold` |
| `extract_paginated` | `row_selector`, `selectors` | `next_selector`, `max_pages`, `same_origin` |
| `follow` | `field`, `selectors` | `concurrency`, `skip_on_error`, `url_prefix`, `row_selector` |
| `save_storage_state` | `path` | |

### Parameters

Declared in `params` with optional `type` (`string`, `int`, `float`, `bool`), `default`, `required`, and `description`. Referenced inside any string with `{{name}}`. Override at run time with `--param key=value`.

### Recording

```bash
sandpaper record https://example.com/search --output recipe.json
```

A headful Chromium opens with a recorder toolbar. Type, click, navigate normally — every interaction is captured. Click **Capture extract** to launch the pattern picker (click row + fields) and append an `extract_paginated` step. Click **Save & finish** to write the recipe.

The recorder dedupes consecutive identical fills (typing fires a change event per keystroke; only the final value is kept) and drops adjacent identical `goto` events.

### Replaying

```bash
sandpaper run-recipe recipe.json -o out.json
sandpaper run-recipe recipe.json -p query=laptops -p max_pages=20
```

CLI overrides:

* `--param key=value` (repeatable) — provide or override a recipe param.
* `--output PATH`, `--format FMT` — override the recipe's `output` block.
* `--profile NAME` / `--storage-state PATH` — drive the recipe through a logged-in session.
* `--rate F`, `--concurrency N` — passed into the runner for follow steps.
* `--cache-dir PATH`, `--rotate-user-agents`, `--obey-robots`, `--headful` — same meaning as on `run`.

### Programmatic use

```python
from sandpaper_py import RecipeRunner, ScrapeConfig, load_recipe

recipe = load_recipe("recipe.json")
result = RecipeRunner(recipe, ScrapeConfig(output="out.json", format="json"),
                     params={"query": "laptops"}).run()
print(result.rows, result.columns)
```

---

## Presets

A preset is a saved per-site configuration. Use it to avoid repeating selectors and other flags every run.

```bash
# Save a preset
sandpaper preset save quotes \
  --extractor selector \
  --row-selector "div.quote" \
  --selectors '{"text": "span.text", "author": "small.author"}'

# List
sandpaper preset list

# Show
sandpaper preset show quotes

# Use
sandpaper run --url https://quotes.toscrape.com --preset quotes -o out.json -f json

# Delete
sandpaper preset delete quotes
```

Presets are stored at `<config_dir>/presets/<name>.toml`. The interactive menu auto-suggests a preset whose name matches the URL host.

The pattern picker can write a preset directly:

```bash
sandpaper pick https://example.com --save-preset mysite
```

---

## Profiles (logged-in scrapes)

A profile is a saved Playwright `storage_state` (cookies, localStorage). Use it to scrape pages that require login without rebuilding the session every run.

```bash
# Create a profile
sandpaper profile login https://app.example.com --as my-account
# A real browser opens. Log in, click "Save session" on the toolbar.

# List profiles
sandpaper profile list

# Use a profile
sandpaper run --url https://app.example.com/dashboard --profile my-account -o data.csv

# Delete
sandpaper profile delete my-account
```

Profiles work with `run`, `run-recipe`, `watch`, `schedule`, and the interactive menu.

For one-off use, `--storage-state path/to/state.json` is the lower-level flag.

---

## Data quality controls

The post-processing pipeline runs after extraction (and follow) and before export. Compose any subset:

```bash
sandpaper run --url ... \
  --rename-columns '{"raw_name":"name","raw_price":"price"}' \
  --keep-columns name,price,url \
  --required-columns name,price \
  --no-trim                              # disable whitespace trim (default on) \
  --schema-lock-after 5 \
  --null-policy null \
  --csv-safe                             # neutralize formula injection in CSV \
  --typed                                # coerce types before export \
  -o out.json -f json
```

| Flag | Behavior |
|------|----------|
| `--rename-columns JSON` | Pre-export rename map. Collisions get a numeric suffix. |
| `--keep-columns / --drop-columns` | Whitelist or blacklist. Whitelist wins. |
| `--required-columns` | Drop rows missing a value in any of these columns. |
| `--no-trim` | Disable whitespace trim on every cell (default on). |
| `--schema-lock-after N` | Infer schema from first N rows; drop columns absent there from the rest. |
| `--null-policy {empty,null,skip}` | JSON-only null handling. |
| `--csv-safe` | Escape leading `=`, `+`, `-`, `@`, tab, CR in CSV cells. |
| `--typed` | Run `coerce_dataframe` (numbers, dates, currencies, booleans) for Parquet/Excel/SQLite/CSV. |
| `--quality-report` | Write `<output>.quality.json` sidecar (rows, types, null ratios, samples). |
| `--provenance` | Write `<output>.meta.json` with source URLs, timestamps, options, selectors. |

---

## Performance and politeness

### Concurrency

```bash
sandpaper run --template "https://e.com/{page}" --pages 1-100 --concurrency 4
sandpaper run --template "https://e.com/{page}" --pages 1-100 --concurrency 8 --async
```

* Default sync mode: one Playwright browser per worker thread. Best for `concurrency` values up to 4–8.
* `--async` switches to a single shared browser with an asyncio semaphore. Better for higher concurrency (40+ pages, 8+ workers).

### Rate limiting

```bash
sandpaper run --url ... --rate 2          # 2 requests/sec per host, shared across workers
sandpaper run --url ... --random-delay 800  # 0..800ms uniform jitter before each request
```

### Caching

```bash
sandpaper run --url ... --cache-dir .sp-cache --cache-ttl 3600
```

A SHA1-keyed local HTML store. Warm hits skip the browser entirely. Use it during development so repeated runs do not pound the target site.

### Anti-block toolkit

```bash
sandpaper run --url ... \
  --rotate-user-agents \
  --random-delay 800 \
  --rate 1 \
  --proxies "http://proxy1.example,http://proxy2.example"
```

Proxies can also come from a file, one per line:

```bash
sandpaper run --url ... --proxy-list proxies.txt
```

### Resource blocking

`--block-resources image,media,font` (default) aborts those resource types via Playwright route interception. Pages that lazy-load 50 images or pull 20MB of webfonts now load in a fraction of the time. Set `--block-resources ""` to load everything.

### Robots.txt

```bash
sandpaper run --url ... --obey-robots
sandpaper run --url ... --obey-robots --allow-on-robots-error  # opt back to fail-open
```

Off by default (so test runs don't surprise you with skipped URLs). When on, an unfetchable robots.txt causes scrapes to be denied; pass `--allow-on-robots-error` to invert that.

---

## Web UI and HTTP API

```bash
pip install "sandpaper-py[api]"
sandpaper serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` for a form-based UI with a "Live progress" toggle that streams events as the scrape runs. The same engine, just clickable.

### HTTP API

* `POST /api/scrape` — synchronous; returns rows + columns + preview + provenance.
* `POST /api/scrape/stream` — server-sent events; emits `start`, repeated `progress`, periodic `heartbeat`, final `done` or `error`.
* `GET /api/health` — returns `{"status": "ok"}`.

```bash
curl -X POST http://127.0.0.1:8000/api/scrape \
  -H 'content-type: application/json' \
  -d '{"url":"https://quotes.toscrape.com","format":"json","threshold":5}'
```

The request body accepts every `ScrapeConfig` field (see `sandpaper_py/api.py::ScrapeRequest`).

For multiple users, run via uvicorn directly with workers:

```bash
uvicorn sandpaper_py.api:create_app --factory --workers 4
```

---

## Programmatic API

```python
from sandpaper_py import (
    scrape, scrape_url, scrape_urls,
    ScrapeConfig, ScrapeResult,
    Recipe, RecipeRunner, load_recipe,
)

# One-liner
result = scrape_url("https://quotes.toscrape.com", threshold=5)

# Detailed
cfg = ScrapeConfig(
    page_template="https://quotes.toscrape.com/page/{page}/",
    pages="1-3",
    extractor="selector",
    row_selector="div.quote",
    selectors={"text": "span.text", "author": "small.author"},
    output="quotes.json",
    format="json",
    deduplicate=True,
    write_provenance=True,
)
result = scrape(cfg)

# In-memory output
df = result.to_pandas(typed=True)        # pandas DataFrame
records = result.records()               # list of dicts
pl = result.to_polars(typed=True)        # polars (if installed)

# Recipe replay
recipe = load_recipe("recipe.json")
runner = RecipeRunner(recipe, ScrapeConfig(output="out.json"), params={"query": "laptops"})
result = runner.run()
```

Every public symbol is re-exported from `sandpaper_py`.

---

## Plugins

Custom exporters, extractors, and loaders are picked up via Python entry points. Register them in your plugin package's `pyproject.toml`:

```toml
[project.entry-points."sandpaper.exporters"]
yaml = "your_pkg.yaml_exporter:YAMLExporter"

[project.entry-points."sandpaper.extractors"]
microdata = "your_pkg.microdata:MicrodataExtractor"

[project.entry-points."sandpaper.loaders"]
http = "your_pkg.http_loader:HTTPLoader"
```

After `pip install your-plugin`, the new format/extractor automatically appears in `sandpaper run --help` (the CLI choice list is built from the plugin registry at parse time).

Implement the matching protocol from `sandpaper_py.exporters.base.Exporter`, `sandpaper_py.extractors.base.Extractor`, or `sandpaper_py.loaders.base.PageLoader`. See the builtins for reference.

---

## Configuration files

```bash
# Show effective config
sandpaper config show

# Print the path the CLI reads from
sandpaper config path

# Write a default config file
sandpaper config init

# Use a non-default location
sandpaper --config /path/to/sandpaper.toml run --url ...
```

The default location is platform-specific (e.g. `~/.config/sandpaper/config.toml` on Linux). Format is TOML; every `ScrapeConfig` field is allowed. The CLI applies precedence:

1. Built-in `ScrapeConfig` defaults
2. Global config file
3. Preset (if `--preset NAME`)
4. CLI flags

Later layers override earlier ones. Dicts merge; lists replace.

---

## Troubleshooting

**`no rows extracted`** — Common causes:

* threshold too high → drop to `--threshold 3`
* the page is a single-record detail page → use `-e selector` with explicit `--selectors`
* robots.txt blocked you → check the warning log, consider `--allow-on-robots-error` if appropriate
* JS-rendered content not yet loaded → add `--wait-for "<css selector>"`

**Site returns 403** — Try `--rotate-user-agents`, `--random-delay 1000`, `--rate 0.5`, or set `--user-agent` to something more specific. For login-walled sites use `sandpaper profile login`.

**Cookie banner blocks the scrape** — On by default, but if a banner uses an unusual pattern, capture the dismiss button with `sandpaper pick`, save it as a `click` step in a recipe, and replay.

**Concurrent run hits the same rate limit as serial** — That's the point of the shared rate limiter (`--rate 2 --concurrency 4` actually means 2/sec total, not 8). If you need a per-worker rate, set `--rate (workers * desired_per_worker)`.

**`fastapi` not found when running `sandpaper serve`** — `pip install "sandpaper-py[api]"`.

**`pyarrow` not found when using `-f parquet`** — `pip install "sandpaper-py[parquet]"`.

**Recipe replay errors on `extract_paginated`** — Check that `next_selector` actually exists on every page, or omit it to let SandPaper fall back to `rel="next"` detection.

**Schedule doesn't fire** — `sandpaper schedule` is blocking and runs in the foreground. Run under a process supervisor (systemd, supervisord, or a Docker container) for production. APScheduler logs the next-fire time on startup.

---

If you find behavior the docs don't cover, open an issue. The [INTERNAL.md](../INTERNAL.md) doc has architecture notes that may help if you want to dig into the source.
