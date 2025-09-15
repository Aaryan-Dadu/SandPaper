# Installation

SandPaper is a Python package distributed on PyPI. It runs on Python 3.9+ and uses Playwright to drive real browsers.

## Requirements

* Python 3.9, 3.10, 3.11, or 3.12
* pip 22+ (older versions of pip cannot resolve modern wheel metadata)
* About 500 MB free disk space if you want browser binaries (Chromium / Firefox / WebKit)

Optional system libraries (only matter on Linux for some pages):

* `libicu` - text rendering and locale handling
* `libjpeg-turbo` - JPEG decoding
* `gstreamer1-libav` - video / audio codecs (only matters if a target page autoplays media)

On Fedora these come from `dnf install libicu libjpeg-turbo`. `gstreamer1-libav` lives in RPM Fusion. On Debian / Ubuntu use `apt install libicu74 libjpeg-turbo8 gstreamer1.0-libav` (or run `sudo playwright install-deps` which Playwright provides for those distros).

## Quick install (from PyPI)

```bash
pip install sandpaper-py
playwright install
```

The second command downloads the actual browser binaries. The first scrape will fail without it.

## With optional features

SandPaper bundles its non-core features as extras:

| Extra | Pulls in | Enables |
|-------|----------|---------|
| `excel` | `openpyxl` | `-f excel` exporter (`.xlsx`) |
| `parquet` | `pyarrow` | `-f parquet` exporter |
| `api` | `fastapi`, `uvicorn`, `jinja2` | `sandpaper serve` and the web UI |
| `schedule` | `apscheduler` | `sandpaper schedule --cron ...` |
| `all` | every extra above | all of the above |
| `dev` | `pytest`, `ruff`, `mypy`, stubs | running tests and linters |

```bash
pip install "sandpaper-py[excel,parquet]"
pip install "sandpaper-py[api]"
pip install "sandpaper-py[all]"
```

## From source

```bash
git clone https://github.com/Aaryan-Dadu/SandPaper
cd SandPaper
pip install -e ".[dev,all]"
playwright install
```

`-e` makes it an editable install: changes to `src/sandpaper_py/` take effect without reinstalling.

## Inside a virtual environment (recommended)

```bash
python -m venv .venv
source .venv/bin/activate           # Linux / macOS
# .venv\Scripts\activate            # Windows PowerShell
pip install --upgrade pip
pip install "sandpaper-py[all]"
playwright install
```

## Verify

```bash
sandpaper --version
sandpaper run --url https://quotes.toscrape.com -o quotes.csv --threshold 5
```

If the second command produces a `quotes.csv` with rows in it, the install is good.

## Browser binaries

`playwright install` downloads Chromium, Firefox, and WebKit into `~/.cache/ms-playwright/` (Linux/macOS) or `%LOCALAPPDATA%\ms-playwright\` (Windows). To install only one engine:

```bash
playwright install chromium
```

To remove them:

```bash
playwright uninstall
```

## Common install issues

**`playwright: command not found`** - Playwright is a dependency of sandpaper-py; if it isn't on PATH, ensure your venv is activated, or run `python -m playwright install` instead.

**`Host system is missing dependencies`** - Playwright printed Ubuntu apt commands but you are not on Ubuntu. Use the Fedora / Arch / macOS equivalent listed above. The warning is non-fatal for most HTML scraping.

**`pyarrow` build fails on Linux** - You probably have an old pip. `pip install --upgrade pip` then retry. On older Pythons you may need `pip install pyarrow --only-binary :all:`.

**`fastapi` not found when running `sandpaper serve`** - You did not install the `[api]` extra. `pip install "sandpaper-py[api]"`.

## Upgrading

```bash
pip install --upgrade sandpaper-py
playwright install
```

## Uninstalling

```bash
pip uninstall sandpaper-py
playwright uninstall                 # if you also want the browser binaries gone
rm -rf ~/.config/sandpaper           # configs, presets, profiles (Linux)
```

## Docker

A minimal Dockerfile to run sandpaper in a container:

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy
WORKDIR /app
RUN pip install --upgrade pip
RUN pip install "sandpaper-py[all]"
ENTRYPOINT ["sandpaper"]
```

Build and run:

```bash
docker build -t sandpaper .
docker run --rm sandpaper run --url https://example.com -o /tmp/out.json -f json
```

The Microsoft `playwright/python` base image already has the browser binaries and required system libs, so no `playwright install` step is needed.
