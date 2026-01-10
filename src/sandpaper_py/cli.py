from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from .config import ScrapeConfig, default_config_dir, default_config_path, load_config, save_config
from .core import scrape
from .presets import delete_preset, list_presets, load_preset, save_preset
from .schema import summarize
from .utils import package_version, setup_logging


def _profiles_dir() -> Path:
    return default_config_dir() / "profiles"


def _profile_path(name: str) -> Path:
    return _profiles_dir() / f"{name}.json"


def _resolve_storage_state(explicit: Optional[str], profile_name: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    if profile_name:
        path = _profile_path(profile_name)
        if not path.exists():
            raise click.UsageError(
                f"profile {profile_name!r} not found at {path}; "
                "create it with `sandpaper profile login`"
            )
        return str(path)
    return None


console = Console()
log = logging.getLogger("sandpaper")


def _available_formats() -> list[str]:
    """Format names known at CLI parse time, including plugin-registered ones."""
    builtins = ["csv", "json", "jsonl", "excel", "parquet", "sqlite"]
    try:
        from .plugins import load_exporters

        plugin_names = sorted(load_exporters().keys())
    except Exception:
        return builtins
    seen: list[str] = []
    for name in builtins + plugin_names:
        if name not in seen:
            seen.append(name)
    return seen


def _load_proxies(csv: Optional[str], path: Optional[str]) -> list[str]:
    if path:
        text = Path(path).read_text(encoding="utf-8")
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    if csv:
        return [p.strip() for p in csv.split(",") if p.strip()]
    return []


def _available_extractors() -> list[str]:
    builtins = ["heuristic", "selector"]
    try:
        from .plugins import load_extractors

        plugin_names = sorted(load_extractors().keys())
    except Exception:
        return builtins
    seen: list[str] = []
    for name in builtins + plugin_names:
        if name not in seen:
            seen.append(name)
    return seen


def _config_from_options(**kwargs) -> ScrapeConfig:
    selectors = {}
    if kwargs.get("selectors"):
        selectors = json.loads(kwargs["selectors"])
    headers = {}
    if kwargs.get("headers"):
        headers = json.loads(kwargs["headers"])
    cookies_path = kwargs.get("cookies_file")
    cookies: list[dict] = []
    if cookies_path:
        cookies = json.loads(Path(cookies_path).read_text(encoding="utf-8"))

    cfg = ScrapeConfig(
        url=kwargs.get("url"),
        pages=kwargs.get("pages"),
        page_template=kwargs.get("template"),
        url_list=list(kwargs.get("url_list") or []),
        output=kwargs.get("output"),
        format=kwargs.get("format") or "csv",
        encoding=kwargs.get("encoding") or "utf-8",
        threshold=kwargs.get("threshold") or 10,
        extractor=kwargs.get("extractor") or "heuristic",
        selectors=selectors,
        row_selector=kwargs.get("row_selector"),
        headers=headers,
        cookies=cookies,
        user_agent=kwargs.get("user_agent"),
        storage_state=_resolve_storage_state(
            kwargs.get("storage_state"), kwargs.get("profile_name")
        ),
        proxy=kwargs.get("proxy"),
        proxies=_load_proxies(
            kwargs.get("proxies"),
            kwargs.get("proxy_list_file"),
        ),
        headless=not kwargs.get("headful", False),
        scroll=not kwargs.get("no_scroll", False),
        scroll_pause=kwargs.get("scroll_pause") or 1.0,
        max_scrolls=kwargs.get("max_scrolls") or 30,
        wait_for_selector=kwargs.get("wait_for"),
        extra_wait_ms=kwargs.get("extra_wait") or 0,
        timeout_ms=kwargs.get("timeout") or 60000,
        retries=kwargs.get("retries") if kwargs.get("retries") is not None else 2,
        rate_per_second=kwargs.get("rate") or 0.0,
        obey_robots=kwargs.get("obey_robots", False),
        allow_on_robots_error=kwargs.get("allow_on_robots_error", False),
        concurrency=kwargs.get("concurrency") or 1,
        auto_paginate=kwargs.get("auto_paginate", False),
        max_auto_pages=kwargs.get("max_auto_pages") or 100,
        deduplicate=kwargs.get("deduplicate", False),
        write_provenance=kwargs.get("provenance", False),
        preset=kwargs.get("preset"),
        log_level=kwargs.get("log_level") or "INFO",
        min_text_length=kwargs.get("min_text_length") or 1,
        max_text_length=kwargs.get("max_text_length") or 4000,
        near_dup_ratio=kwargs.get("near_dup_ratio") or 0.85,
        csv_safe=kwargs.get("csv_safe", False),
        json_drop_empty=not kwargs.get("keep_empty_columns", False),
        json_sort_keys=kwargs.get("sort_keys", False),
        json_normalize_keys=kwargs.get("normalize_keys", False),
        typed=kwargs.get("typed", False),
        quality_report=kwargs.get("quality_report", False),
        cache_dir=kwargs.get("cache_dir"),
        cache_ttl_seconds=kwargs.get("cache_ttl") or 0,
        rotate_user_agents=kwargs.get("rotate_user_agents", False),
        random_delay_ms=kwargs.get("random_delay") or 0,
        max_pages_limit=kwargs.get("max_pages_limit") or 10000,
        sort_columns=kwargs.get("sort_columns", False),
        block_resources=[
            r.strip() for r in (kwargs.get("block_resources") or "").split(",") if r.strip()
        ],
        dismiss_overlays=not kwargs.get("no_dismiss_overlays", False),
        prefer_records=not kwargs.get("no_prefer_records", False),
        max_fields_per_record=kwargs.get("max_fields_per_record") or 30,
        follow_field=kwargs.get("follow"),
        follow_selectors=(
            json.loads(kwargs["follow_selectors"]) if kwargs.get("follow_selectors") else {}
        ),
        follow_row_selector=kwargs.get("follow_row_selector"),
        follow_concurrency=kwargs.get("follow_concurrency") or 4,
        follow_skip_on_error=not kwargs.get("follow_fail_on_error", False),
        follow_url_prefix=kwargs.get("follow_url_prefix"),
        rename_columns=(
            json.loads(kwargs["rename_columns"]) if kwargs.get("rename_columns") else {}
        ),
        keep_columns=[
            c.strip() for c in (kwargs.get("keep_columns") or "").split(",") if c.strip()
        ],
        drop_columns=[
            c.strip() for c in (kwargs.get("drop_columns") or "").split(",") if c.strip()
        ],
        required_columns=[
            c.strip() for c in (kwargs.get("required_columns") or "").split(",") if c.strip()
        ],
        trim_cells=not kwargs.get("no_trim", False),
        null_policy=kwargs.get("null_policy") or "empty",
        schema_lock_after=kwargs.get("schema_lock_after") or 0,
        async_mode=kwargs.get("async_mode", False),
    )
    return cfg


def _print_summary(result, dry_run: bool = False) -> None:
    if result.rows == 0:
        console.print(
            "[yellow]no rows extracted. "
            "common causes: robots.txt blocked, threshold too high, "
            "or selectors did not match.[/yellow]"
        )
        if result.provenance.source_urls:
            console.print(f"[dim]urls visited: {len(result.provenance.source_urls)}[/dim]")
        return
    stats = summarize(result.table)
    table = Table(title="Scrape summary", show_lines=False)
    table.add_column("column")
    table.add_column("type")
    table.add_column("filled")
    table.add_column("empty")
    table.add_column("unique")
    table.add_column("sample")
    for c in stats.columns:
        table.add_row(
            c.name,
            c.inferred_type,
            str(c.non_empty),
            str(c.empty),
            str(c.unique),
            ", ".join(c.sample),
        )
    console.print(table)
    console.print(f"[bold]rows:[/bold] {result.rows}  [bold]columns:[/bold] {len(result.columns)}")
    if result.output_path and not dry_run:
        console.print(f"[green]saved to[/green] {result.output_path}")


def _make_progress_callback(progress: Progress, task_id):
    def cb(index: int, total: int, url: str, status: Optional[str]):
        progress.update(task_id, total=total, completed=index, description=f"[cyan]{url}")
        if status and status != "ok":
            log.warning("%s %s", url, status)

    return cb


@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_version() or "unknown", prog_name="sandpaper")
@click.option(
    "--log-level",
    default="INFO",
    show_default=True,
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
)
@click.option(
    "--config", "config_path", type=click.Path(path_type=Path), help="Path to config TOML."
)
@click.pass_context
def main(ctx: click.Context, log_level: str, config_path: Optional[Path]) -> None:
    setup_logging(log_level.upper())
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config_path) if config_path else load_config()
    if ctx.invoked_subcommand is None:
        ctx.invoke(interactive)


def _common_scrape_options(func):
    decorators = [
        click.option("--url", help="Target URL."),
        click.option("--template", help="URL template containing {page}."),
        click.option("--pages", help="Page range like '1-5,7,10-12'."),
        click.option("--url-list", multiple=True, help="Repeatable explicit URLs."),
        click.option("--output", "-o", type=click.Path(), help="Output file path."),
        click.option(
            "--format",
            "-f",
            "format",
            type=click.Choice(_available_formats()),
            default="csv",
            show_default=True,
        ),
        click.option("--encoding", default="utf-8", show_default=True),
        click.option(
            "--extractor",
            "-e",
            type=click.Choice(_available_extractors()),
            default="heuristic",
            show_default=True,
        ),
        click.option("--selectors", help="JSON map of column to CSS selector."),
        click.option(
            "--row-selector",
            help="Row container selector. With --extractor selector, "
            "field selectors run relative to each row.",
        ),
        click.option(
            "--threshold",
            "-t",
            type=int,
            default=10,
            show_default=True,
            help="Heuristic minimum items per column.",
        ),
        click.option("--headers", help="Extra request headers as JSON."),
        click.option("--cookies-file", type=click.Path(exists=True), help="JSON file of cookies."),
        click.option("--user-agent"),
        click.option(
            "--storage-state", type=click.Path(), help="Playwright storage_state JSON path."
        ),
        click.option(
            "--profile",
            "profile_name",
            help="Use a saved login profile (see `sandpaper profile login`).",
        ),
        click.option("--proxy", help="Proxy server, e.g. http://user:pw@host:port"),
        click.option("--proxies", help="Comma list of proxies, randomly chosen per worker."),
        click.option(
            "--proxy-list",
            "proxy_list_file",
            type=click.Path(exists=True),
            help="File with one proxy per line (overrides --proxies).",
        ),
        click.option("--headful", is_flag=True, help="Show the browser window."),
        click.option("--no-scroll", is_flag=True, help="Disable auto-scroll."),
        click.option("--scroll-pause", type=float, default=1.0, show_default=True),
        click.option("--max-scrolls", type=int, default=30, show_default=True),
        click.option("--wait-for", help="CSS selector to wait for."),
        click.option("--extra-wait", type=int, default=0, help="Extra ms wait after load."),
        click.option("--timeout", type=int, default=60000, show_default=True),
        click.option("--retries", type=int, default=2, show_default=True),
        click.option(
            "--rate",
            type=float,
            default=0.0,
            help="Max requests / second per host (0 = unlimited).",
        ),
        click.option("--obey-robots", is_flag=True),
        click.option(
            "--allow-on-robots-error",
            is_flag=True,
            help="If robots.txt cannot be fetched, allow scrape (default: deny).",
        ),
        click.option("--concurrency", "-c", type=int, default=1, show_default=True),
        click.option(
            "--async",
            "async_mode",
            is_flag=True,
            help="Use async Playwright with one shared browser; "
            "scales to high concurrency without per-thread browsers.",
        ),
        click.option("--auto-paginate", is_flag=True),
        click.option("--max-auto-pages", type=int, default=100, show_default=True),
        click.option(
            "--max-pages-limit",
            type=int,
            default=10000,
            show_default=True,
            help="Hard cap on expanded page lists.",
        ),
        click.option("--deduplicate", is_flag=True),
        click.option("--provenance", is_flag=True, help="Write provenance sidecar."),
        click.option(
            "--quality-report",
            is_flag=True,
            help="Write quality report sidecar (row counts, types, null ratios).",
        ),
        click.option("--preset", help="Preset name."),
        click.option(
            "--min-text-length",
            type=int,
            default=1,
            show_default=True,
            help="Drop heuristic cells shorter than N characters.",
        ),
        click.option(
            "--max-text-length",
            type=int,
            default=4000,
            show_default=True,
            help="Drop heuristic cells longer than N characters (kills nav blobs).",
        ),
        click.option(
            "--near-dup-ratio",
            type=float,
            default=0.85,
            show_default=True,
            help="Drop columns whose unique ratio is below 1 - this value.",
        ),
        click.option(
            "--csv-safe",
            is_flag=True,
            help="Escape leading =, +, -, @ in CSV cells (formula injection).",
        ),
        click.option(
            "--keep-empty-columns", is_flag=True, help="Keep columns where every cell is empty."
        ),
        click.option("--sort-keys", is_flag=True, help="Sort keys in JSON/JSONL output."),
        click.option("--sort-columns", is_flag=True, help="Sort columns alphabetically."),
        click.option(
            "--normalize-keys", is_flag=True, help="Slugify column names in JSON/JSONL output."
        ),
        click.option(
            "--typed",
            is_flag=True,
            help="Use schema-coerced DataFrame for output (Parquet/SQLite recommended).",
        ),
        click.option(
            "--cache-dir", type=click.Path(), help="Directory for HTML cache (per-URL SHA1 keyed)."
        ),
        click.option(
            "--cache-ttl", type=int, default=0, help="Cache entry TTL in seconds (0 = no expiry)."
        ),
        click.option("--rotate-user-agents", is_flag=True),
        click.option(
            "--random-delay", type=int, default=0, help="Random delay 0..N ms before each request."
        ),
        click.option(
            "--block-resources",
            default="image,media,font",
            show_default=True,
            help="Comma list of resource types to block "
            "(image, media, font, stylesheet, ...). Empty to load everything.",
        ),
        click.option(
            "--no-dismiss-overlays", is_flag=True, help="Disable cookie/popup auto-dismiss."
        ),
        click.option(
            "--no-prefer-records",
            is_flag=True,
            help="Disable record-set extraction; use the flat fallback only.",
        ),
        click.option("--max-fields-per-record", type=int, default=30, show_default=True),
        click.option(
            "--follow",
            help="Field name in the list extraction whose value is "
            "a URL to follow into a detail page.",
        ),
        click.option(
            "--follow-selectors",
            help="JSON map of column to selector (or selector@attr) "
            "to extract from each detail page.",
        ),
        click.option(
            "--follow-row-selector",
            help="If detail pages contain repeating rows, use this "
            "as the row selector (rare; defaults to single-record).",
        ),
        click.option("--follow-concurrency", type=int, default=4, show_default=True),
        click.option(
            "--follow-fail-on-error",
            is_flag=True,
            help="Abort the run if any detail-page fetch fails "
            "(default: skip the row and continue).",
        ),
        click.option("--follow-url-prefix", help="Prefix prepended to relative follow URLs."),
        click.option("--rename-columns", help="JSON map of original column name to new name."),
        click.option("--keep-columns", help="Comma list of columns to keep (drops the rest)."),
        click.option("--drop-columns", help="Comma list of columns to drop."),
        click.option(
            "--required-columns", help="Comma list of columns; rows missing any are dropped."
        ),
        click.option("--no-trim", is_flag=True, help="Disable whitespace trimming on cell values."),
        click.option(
            "--null-policy",
            type=click.Choice(["empty", "null", "skip"]),
            default="empty",
            show_default=True,
            help="JSON output: empty keeps '', null writes null, skip omits the key from the row.",
        ),
        click.option(
            "--schema-lock-after",
            type=int,
            default=0,
            help="Infer schema from first N rows; drop columns absent there.",
        ),
    ]
    for dec in reversed(decorators):
        func = dec(func)
    return func


@main.command()
@_common_scrape_options
@click.option("--dry-run", is_flag=True, help="Print preview without writing to disk.")
@click.pass_context
def run(ctx: click.Context, dry_run: bool, **kwargs) -> None:
    """Run a non-interactive scrape from CLI flags."""
    base_cfg: ScrapeConfig = ctx.obj["config"]
    flag_cfg = _config_from_options(**kwargs)
    cfg = base_cfg.merge(flag_cfg)
    if dry_run:
        cfg.output = None

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("[cyan]starting", total=1)
        cb = _make_progress_callback(progress, task)
        result = scrape(cfg, on_progress=cb)
    _print_summary(result, dry_run=dry_run)


@main.command()
@click.pass_context
def interactive(ctx: click.Context) -> None:
    """Open the interactive prompt-based menu."""
    from .menu import run_interactive

    base: ScrapeConfig = ctx.obj["config"]
    chosen = run_interactive(base)
    if chosen is None:
        sys.exit(1)
    cfg = base.merge(chosen)

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("[cyan]starting", total=1)
        cb = _make_progress_callback(progress, task)
        result = scrape(cfg, on_progress=cb)
    _print_summary(result)


@main.command("watch")
@_common_scrape_options
@click.option("--every", type=int, required=True, help="Seconds between runs.")
@click.option("--iterations", type=int, default=None, help="Stop after N runs (default: forever).")
@click.pass_context
def watch_cmd(ctx: click.Context, every: int, iterations: Optional[int], **kwargs) -> None:
    """Run a scrape on a fixed interval."""
    from .watch import watch

    base_cfg: ScrapeConfig = ctx.obj["config"]
    cfg = base_cfg.merge(_config_from_options(**kwargs))
    watch(
        cfg,
        interval_seconds=every,
        iterations=iterations,
        on_run=lambda r: console.print(f"[green]ok[/green] rows={r.rows}"),
    )


@main.command("schedule")
@_common_scrape_options
@click.option("--cron", required=True, help="Cron expression, e.g. '0 * * * *'.")
@click.pass_context
def schedule_cmd(ctx: click.Context, cron: str, **kwargs) -> None:
    """Run a scrape on a cron schedule (blocking)."""
    from .watch import schedule

    base_cfg: ScrapeConfig = ctx.obj["config"]
    cfg = base_cfg.merge(_config_from_options(**kwargs))
    schedule(cfg, cron_expression=cron)


@main.command("pick")
@click.argument("url")
@click.option(
    "--save",
    "save_path",
    type=click.Path(path_type=Path),
    help="Save the result as a JSON preset file.",
)
@click.option(
    "--save-preset", "preset_name", help="Save directly as a named preset usable via --preset."
)
@click.option(
    "--timeout",
    type=int,
    default=600,
    show_default=True,
    help="Seconds before the picker auto-closes.",
)
def pick_cmd(
    url: str,
    save_path: Optional[Path],
    preset_name: Optional[str],
    timeout: int,
) -> None:
    """Pattern-aware visual element picker.

    Click one element, SandPaper auto-detects the row pattern.
    Click fields inside one row; selectors are computed relative to the row
    so every row aligns. Output is a preset (row_selector + selectors).
    """
    from .visual import pick_pattern

    result = pick_pattern(url, timeout_seconds=timeout)
    if not result.row_selector:
        console.print("[yellow]No row pattern was selected.[/yellow]")
        raise SystemExit(1)
    if not result.selectors:
        console.print("[yellow]No fields were captured.[/yellow]")
        raise SystemExit(1)

    table = Table(title=f"Picked {result.row_count} rows", show_lines=False)
    for col in result.selectors:
        table.add_column(col)
    preview_rows = min(5, result.row_count)
    for i in range(preview_rows):
        table.add_row(
            *[
                (result.samples.get(col, [""])[i] if i < len(result.samples.get(col, [])) else "")[
                    :60
                ]
                for col in result.selectors
            ]
        )
    console.print(table)
    console.print(f"[bold]row_selector:[/bold] {result.row_selector}")
    for col, sel in result.selectors.items():
        console.print(f"  [cyan]{col}[/cyan]: {sel}")

    payload = result.to_preset_dict()
    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        console.print(f"[green]wrote {save_path}[/green]")

    if preset_name:
        cfg = ScrapeConfig(
            extractor="selector",
            row_selector=result.row_selector,
            selectors=result.selectors,
        )
        path = save_preset(preset_name, cfg)
        console.print(
            f"[green]saved preset {preset_name!r} at {path}[/green]\n"
            f"use it with: [bold]sandpaper run --url <URL> --preset {preset_name}[/bold]"
        )


@main.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", type=int, default=8000, show_default=True)
def serve_cmd(host: str, port: int) -> None:
    """Start the HTTP API and web UI."""
    from .api import serve

    serve(host=host, port=port)


@main.command("record")
@click.argument("url")
@click.option(
    "--output",
    "-o",
    "output_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Where to save the recipe JSON.",
)
@click.option("--name", help="Recipe name (default: file stem).")
@click.option(
    "--timeout",
    type=int,
    default=3600,
    show_default=True,
    help="Seconds before the recorder auto-closes.",
)
def record_cmd(url: str, output_path: Path, name: Optional[str], timeout: int) -> None:
    """Record a browser session as a replayable recipe.

    Opens a real Chromium window. Click, type, and navigate normally; SandPaper
    captures every interaction. Click 'Capture extract' on the toolbar to
    open the pattern picker and add an extract step. Click 'Save & finish'
    when you are done. The recipe is written to --output.
    """
    from .visual import record_session

    saved = record_session(url, save_to=output_path, name=name, timeout_seconds=timeout)
    console.print(f"[green]recipe saved at {saved}[/green]")
    console.print(f"replay it with: [bold]sandpaper run-recipe {saved}[/bold]")


@main.command("run-recipe")
@click.argument("recipe_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--param", "-p", "params", multiple=True, help="Parameter override as key=value (repeatable)."
)
@click.option(
    "--output", "-o", type=click.Path(), help="Output file path (overrides recipe.output)."
)
@click.option(
    "--format",
    "-f",
    "format",
    type=click.Choice(_available_formats()),
    default=None,
    help="Output format (overrides recipe.output.format).",
)
@click.option("--encoding", default="utf-8", show_default=True)
@click.option("--headful", is_flag=True, help="Show the browser while running.")
@click.option("--rate", type=float, default=0.0, help="Max requests/sec per host.")
@click.option(
    "--concurrency",
    type=int,
    default=1,
    show_default=True,
    help="Parallel workers for follow steps.",
)
@click.option("--provenance", is_flag=True, help="Write provenance sidecar.")
@click.option("--quality-report", is_flag=True, help="Write quality sidecar.")
@click.option("--profile", "profile_name", help="Use a saved login profile.")
@click.option("--storage-state", type=click.Path(), help="Playwright storage_state JSON path.")
@click.option("--cache-dir", type=click.Path(), help="Per-URL HTML cache directory.")
@click.option("--rotate-user-agents", is_flag=True)
@click.option("--obey-robots", is_flag=True)
def run_recipe_cmd(
    recipe_path: Path,
    params: tuple[str, ...],
    output: Optional[str],
    format: Optional[str],
    encoding: str,
    headful: bool,
    rate: float,
    concurrency: int,
    provenance: bool,
    quality_report: bool,
    profile_name: Optional[str],
    storage_state: Optional[str],
    cache_dir: Optional[str],
    rotate_user_agents: bool,
    obey_robots: bool,
) -> None:
    """Replay a recipe file."""
    from .recipe_runner import RecipeRunner
    from .recipes import load_recipe, parse_param_overrides

    recipe = load_recipe(recipe_path)
    overrides = parse_param_overrides(list(params))

    out_path = output
    out_format = format
    if recipe.output:
        out_path = out_path or recipe.output.get("path")
        out_format = out_format or recipe.output.get("format")

    cfg = ScrapeConfig(
        output=out_path,
        format=out_format or "json",
        encoding=encoding,
        headless=not headful,
        rate_per_second=rate,
        follow_concurrency=concurrency,
        write_provenance=provenance,
        quality_report=quality_report,
        storage_state=_resolve_storage_state(storage_state, profile_name),
        cache_dir=cache_dir,
        rotate_user_agents=rotate_user_agents,
        obey_robots=obey_robots,
    )

    runner = RecipeRunner(recipe, cfg, params=overrides)
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"[cyan]{recipe.name}", total=len(recipe.steps))

        def cb(index: int, total: int, action: str, status: str) -> None:
            progress.update(task, total=total, completed=index, description=f"[cyan]{action}")
            if status not in {"ok", "running"}:
                log.warning("step %d %s %s", index, action, status)

        result = runner.run(on_progress=cb)
    _print_summary(result)


@main.group()
def preset() -> None:
    """Manage saved per-site presets."""


@preset.command("list")
def preset_list() -> None:
    names = list_presets()
    if not names:
        console.print("[yellow]no presets saved[/yellow]")
        return
    for name in names:
        console.print(f"- {name}")


@preset.command("show")
@click.argument("name")
def preset_show(name: str) -> None:
    cfg = load_preset(name)
    console.print_json(data=asdict(cfg))


@preset.command("save")
@click.argument("name")
@_common_scrape_options
def preset_save(name: str, **kwargs) -> None:
    cfg = _config_from_options(**kwargs)
    path = save_preset(name, cfg)
    console.print(f"[green]saved preset {name!r} at {path}[/green]")


@preset.command("delete")
@click.argument("name")
def preset_delete(name: str) -> None:
    if delete_preset(name):
        console.print(f"[green]deleted preset {name!r}[/green]")
    else:
        console.print(f"[yellow]no preset {name!r}[/yellow]")


@main.group("config")
def config_group() -> None:
    """Manage the global config file."""


@config_group.command("path")
def config_path_cmd() -> None:
    console.print(str(default_config_path()))


@config_group.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    cfg: ScrapeConfig = ctx.obj["config"]
    console.print_json(data=asdict(cfg))


@config_group.command("init")
def config_init() -> None:
    path = save_config(ScrapeConfig())
    console.print(f"[green]wrote {path}[/green]")


@main.group("profile")
def profile_group() -> None:
    """Manage saved login profiles (Playwright storage_state)."""


@profile_group.command("login")
@click.argument("url")
@click.option("--as", "name", required=True, help="Name to save the resulting profile under.")
@click.option(
    "--timeout",
    type=int,
    default=1800,
    show_default=True,
    help="Seconds before the login window auto-closes.",
)
def profile_login(url: str, name: str, timeout: int) -> None:
    """Open a headful browser, sign in, save the session as a profile."""
    from .visual import login_session

    target = _profile_path(name)
    login_session(url, save_to=target, timeout_seconds=timeout)
    console.print(f"[green]saved profile {name!r} at {target}[/green]")
    console.print(f"use it with: [bold]sandpaper run --url <URL> --profile {name}[/bold]")


@profile_group.command("list")
def profile_list() -> None:
    d = _profiles_dir()
    if not d.exists():
        console.print("[yellow]no profiles saved[/yellow]")
        return
    names = sorted(p.stem for p in d.glob("*.json"))
    if not names:
        console.print("[yellow]no profiles saved[/yellow]")
        return
    for n in names:
        console.print(f"- {n}")


@profile_group.command("path")
@click.argument("name")
def profile_path_cmd(name: str) -> None:
    console.print(str(_profile_path(name)))


@profile_group.command("delete")
@click.argument("name")
def profile_delete(name: str) -> None:
    path = _profile_path(name)
    if path.exists():
        path.unlink()
        console.print(f"[green]deleted profile {name!r}[/green]")
    else:
        console.print(f"[yellow]no profile {name!r}[/yellow]")


if __name__ == "__main__":
    main()
