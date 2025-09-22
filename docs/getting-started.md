# Getting started with SandPaper

SandPaper scrapes web pages with Playwright and turns them into structured data. This guide takes you from a fresh install to your first three real scrapes in about ten minutes.

If you have not installed yet, follow [INSTALLATION.md](../INSTALLATION.md) first. The short version:

```bash
pip install "sandpaper-py[all]"
playwright install
```

## Your first scrape

Pick a page that has a list on it. We will use [https://quotes.toscrape.com](https://quotes.toscrape.com), a public test target.

```bash
sandpaper run --url https://quotes.toscrape.com -o quotes.csv --threshold 5
```

What this did:

* Opened a real browser headlessly.
* Fetched the page.
* Looked for repeating sibling elements (the heuristic extractor).
* Found 10 quote cards, pulled fields out of each one.
* Wrote `quotes.csv` to your working directory.

Open `quotes.csv` in a text editor or spreadsheet. Each row is one quote.

If you want JSON instead, change the format:

```bash
sandpaper run --url https://quotes.toscrape.com -o quotes.json -f json
```

## Pin the columns you want

The heuristic extractor is good for "give me whatever repeats." For real work you usually want specific columns. Use the **pattern picker** to point at what you want.

```bash
sandpaper pick https://quotes.toscrape.com --save-preset quotes
```

A real Chromium window opens with a panel in the top-right. Click any quote on the page. SandPaper outlines all the quote cards in green: those are the rows. Now click each field inside one quote and label it (`text`, `author`, `tags`). Press Esc when you are done.

This saves a *preset*. Use it from now on:

```bash
sandpaper run --url https://quotes.toscrape.com --preset quotes -o quotes.json -f json
```

Output is one row per quote with exactly the columns you picked.

## Scrape a list across pages

Most listings span multiple pages. Two ways to handle this.

### URL template (when the page number is in the URL)

```bash
sandpaper run \
  --template "https://quotes.toscrape.com/page/{page}/" \
  --pages 1-10 \
  --preset quotes \
  -o quotes.json -f json
```

### Auto-paginate (follow the "next" link automatically)

```bash
sandpaper run \
  --url https://quotes.toscrape.com \
  --auto-paginate --max-auto-pages 10 \
  --preset quotes \
  -o quotes.json -f json
```

Auto-paginate works on any site that has a `<a rel="next">` or a "Next" link. Most listings do.

## List page → click into details

The other common pattern: scrape a list, follow each item's link, scrape the detail page, merge.

```bash
sandpaper run \
  --url https://news.example.com/articles \
  -e selector \
  --row-selector "article.post" \
  --selectors '{"title": "h2", "summary": "p.lede", "url": "a@href"}' \
  --follow url \
  --follow-selectors '{"body": "div.article-body", "tags": ".tag"}' \
  --follow-concurrency 4 \
  -o articles.json -f json
```

Each row in `articles.json` has both the summary fields from the list and the body fields from the detail page.

The `selector@attr` syntax (like `a@href`) extracts an attribute instead of text.

## Record a session as a recipe

When the page needs interaction, like searching or logging in, record what you do once and replay it later.

```bash
sandpaper record https://example.com/search --output search-recipe.json
```

A real browser opens. Type a query, click the search button, paginate, click "Capture extract" in the toolbar to point out what you want from the results page, and click "Save & finish" when done. SandPaper writes a recipe file.

Replay it any time:

```bash
sandpaper run-recipe search-recipe.json -o results.json
```

Or with parameter overrides:

```bash
sandpaper run-recipe search-recipe.json --param query=laptops -o results.json
```

## Logging into a site

Some sites require a login before you can scrape. SandPaper saves the session so you only do it once.

```bash
sandpaper profile login https://app.example.com --as my-account
```

A browser opens. Log in normally. Click "Save session" on the toolbar. Now any scrape can replay that session:

```bash
sandpaper run --url https://app.example.com/dashboard --profile my-account -o data.csv
```

## Run the same scrape on a schedule

Daily or hourly:

```bash
sandpaper schedule --preset quotes --url https://quotes.toscrape.com \
  --cron "0 9 * * *" -o quotes-daily.csv
```

The first argument to `--cron` is a standard cron expression. This one runs at 09:00 every day.

For one-off polling:

```bash
sandpaper watch --preset quotes --url https://quotes.toscrape.com --every 600 -o quotes.csv
```

Re-runs every 600 seconds.

## Use it from Python

```python
from sandpaper_py import scrape_url

result = scrape_url("https://quotes.toscrape.com", threshold=5)
print(result.rows, result.columns)

df = result.to_pandas(typed=True)        # pandas DataFrame
records = result.records()               # list of dicts
```

For richer cases:

```python
from sandpaper_py import ScrapeConfig, scrape

cfg = ScrapeConfig(
    url="https://quotes.toscrape.com",
    extractor="selector",
    row_selector="div.quote",
    selectors={"text": "span.text", "author": "small.author"},
    output="quotes.json",
    format="json",
)
result = scrape(cfg)
```

## Web UI

```bash
pip install "sandpaper-py[api]"
sandpaper serve
```

Open `http://127.0.0.1:8000` in a browser. Form-based UI with live progress streaming, table preview, and provenance JSON. The same engine, just clickable.

## What to read next

* [User guide](user-guide.md) — every CLI command, every flag, deeper coverage of each feature.
* [INSTALLATION.md](../INSTALLATION.md) — install troubleshooting, optional extras, Docker.
* [CONTRIBUTING.md](../CONTRIBUTING.md) — if you want to extend SandPaper or send a patch.

## Common first-run issues

**`Host system is missing dependencies`** — Playwright printed Ubuntu apt commands but you are on a different distro. Most of those libraries are only needed for media. HTML scraping works without them. See [INSTALLATION.md](../INSTALLATION.md#common-install-issues).

**`no rows extracted`** — The heuristic could not find a repeating pattern, or the threshold is too high. Try `--threshold 3`. If the page is a single-record detail page, use `-e selector` with explicit `--selectors`.

**Site blocks the scrape** — Try `--rotate-user-agents`, `--random-delay 800` (milliseconds), or `--rate 1` (one request per second). For login-walled sites use `sandpaper profile login`.

**Cookies banner is in the way** — On by default, but if a site uses an unusual banner pattern, try `--no-dismiss-overlays` to see what is happening, then use the picker to capture the dismiss button as a `click` step in a recipe.
