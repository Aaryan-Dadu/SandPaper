from __future__ import annotations

import json
from collections.abc import Callable

import questionary
from rich import print as rprint

from .config import ScrapeConfig
from .presets import find_preset_for_url, list_presets
from .utils import get_site_name, is_valid_url, parse_page_range

BANNER = r"""[bold red]
   _____                 _ _____
  / ____|               | |  __ \
 | (___   __ _ _ __   __| | |__) |_ _ _ __   ___ _ __
  \___ \ / _` | '_ \ / _` |  ___/ _` | '_ \ / _ \ '__|
  ____) | (_| | | | | (_| | |  | (_| | |_) |  __/ |
 |_____/ \__,_|_| |_|\__,_|_|   \__,_| .__/ \___|_|
                                     | |
                                     |_|
[/bold red]"""

BACK_LABEL = "<- Back"
BACK_TOKEN = ":back"


class _Back(Exception):
    pass


class _Abort(Exception):
    pass


def _ask_select(message: str, choices: list, default=None, show_back: bool = True):
    options = [BACK_LABEL, *choices] if show_back else list(choices)
    if default is None or default not in choices:
        default = options[1] if show_back and len(options) > 1 else options[0]
    answer = questionary.select(message, choices=options, default=default).ask()
    if answer is None:
        raise _Abort
    if answer == BACK_LABEL:
        raise _Back
    return answer


def _ask_text(
    message: str,
    default: str = "",
    validate: Callable[[str], object] | None = None,
    show_back: bool = True,
) -> str:
    def wrapped(value: str):
        if show_back and value.strip() == BACK_TOKEN:
            return True
        if validate is None:
            return True
        return validate(value)

    answer = questionary.text(message, default=default, validate=wrapped).ask()
    if answer is None:
        raise _Abort
    if show_back and answer.strip() == BACK_TOKEN:
        raise _Back
    return answer


def _ask_confirm(message: str, default: bool = True) -> bool:
    choice = _ask_select(
        message,
        choices=["Yes", "No"],
        default="Yes" if default else "No",
    )
    return choice == "Yes"


def _validate_url(value: str) -> bool | str:
    if value.strip() == BACK_TOKEN:
        return True
    if not value:
        return "URL cannot be empty"
    if not is_valid_url(value):
        return "Must start with http:// or https://"
    return True


def _validate_template(value: str) -> bool | str:
    if value.strip() == BACK_TOKEN:
        return True
    if not value:
        return "Template cannot be empty"
    if "{page}" not in value:
        return "Template must contain {page}"
    if not is_valid_url(value.replace("{page}", "1")):
        return "Template must be a valid URL"
    return True


def _validate_pages(value: str) -> bool | str:
    if value.strip() == BACK_TOKEN:
        return True
    try:
        parse_page_range(value)
    except Exception as exc:
        return str(exc)
    return True


def _validate_int(min_value: int = 1):
    def check(value: str) -> bool | str:
        if value.strip() == BACK_TOKEN:
            return True
        try:
            n = int(value)
        except ValueError:
            return "Must be an integer"
        if n < min_value:
            return f"Must be >= {min_value}"
        return True

    return check


def _validate_float_min(min_value: float = 0.0):
    def check(value: str) -> bool | str:
        if value.strip() == BACK_TOKEN:
            return True
        try:
            n = float(value)
        except ValueError:
            return "Must be a number"
        if n < min_value:
            return f"Must be >= {min_value}"
        return True

    return check


def _validate_json_dict(value: str) -> bool | str:
    if value.strip() == BACK_TOKEN or value.strip() == "":
        return True
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON: {exc.msg}"
    if not isinstance(parsed, dict):
        return "Must be a JSON object"
    return True


def _step_preset(cfg: ScrapeConfig) -> None:
    presets = list_presets()
    if not presets:
        return
    chosen = _ask_select(
        "Use a saved preset?",
        choices=["(none)", *presets],
        default="(none)",
    )
    cfg.preset = None if chosen == "(none)" else chosen


def _step_mode(cfg: ScrapeConfig) -> str:
    return _ask_select(
        "Scrape mode",
        choices=[
            "Single URL",
            "URL template with page range",
            "Custom URL list",
            "Auto-paginate",
        ],
    )


def _step_target(cfg: ScrapeConfig, mode: str) -> None:
    if mode == "Single URL":
        cfg.url = _ask_text("Target URL", validate=_validate_url)
        cfg.page_template = None
        cfg.url_list = []
        cfg.auto_paginate = False
        if cfg.preset is None:
            suggested = find_preset_for_url(cfg.url)
            if suggested and _ask_confirm(
                f"Found preset '{suggested}' for this host. Use it?", default=True
            ):
                cfg.preset = suggested
    elif mode == "URL template with page range":
        cfg.page_template = _ask_text("URL template (use {page})", validate=_validate_template)
        cfg.pages = _ask_text(
            "Page range (e.g. 1-5,7,10-12)", default="1-5", validate=_validate_pages
        )
        cfg.url = None
        cfg.url_list = []
        cfg.auto_paginate = False
    elif mode == "Custom URL list":
        urls_raw = _ask_text("Comma-separated URLs")
        candidates = [u.strip() for u in urls_raw.split(",") if u.strip()]
        invalid = [u for u in candidates if not is_valid_url(u)]
        if invalid:
            rprint(f"[bold red]Invalid URLs:[/bold red] {', '.join(invalid)}")
            raise _Back
        if not candidates:
            rprint("[bold red]No URLs provided.[/bold red]")
            raise _Back
        cfg.url_list = candidates
        cfg.url = None
        cfg.page_template = None
        cfg.auto_paginate = False
    else:
        cfg.url = _ask_text("Start URL", validate=_validate_url)
        cfg.auto_paginate = True
        cfg.max_auto_pages = int(
            _ask_text("Max pages to follow", default="20", validate=_validate_int(1))
        )
        cfg.page_template = None
        cfg.url_list = []


def _step_extractor(cfg: ScrapeConfig) -> None:
    cfg.extractor = _ask_select(
        "Extractor", choices=["heuristic", "selector"], default=cfg.extractor or "heuristic"
    )
    if cfg.extractor == "selector":
        raw = _ask_text(
            'Selectors as JSON (e.g. {"title": "h2.title"})',
            validate=_validate_json_dict,
        )
        cfg.selectors = json.loads(raw) if raw.strip() else {}
        if not cfg.selectors:
            rprint("[bold red]Selector mode needs at least one selector.[/bold red]")
            raise _Back
    else:
        cfg.threshold = int(
            _ask_text(
                "Filter threshold (min items per column)",
                default=str(cfg.threshold),
                validate=_validate_int(1),
            )
        )


def _step_format(cfg: ScrapeConfig) -> None:
    cfg.format = _ask_select(
        "Output format",
        choices=["csv", "json", "jsonl", "excel", "parquet", "sqlite"],
        default=cfg.format or "csv",
    )
    if cfg.format in {"csv", "json", "jsonl"}:
        cfg.encoding = _ask_text("Encoding", default=cfg.encoding or "utf-8")


def _step_output(cfg: ScrapeConfig) -> None:
    suffix = {"excel": "xlsx", "sqlite": "db"}.get(cfg.format, cfg.format)
    base = get_site_name(cfg.url or (cfg.url_list[0] if cfg.url_list else "scrape"))
    default_name = f"{base}.{suffix}"
    cfg.output = _ask_text("Output path", default=cfg.output or default_name)


def _step_advanced(cfg: ScrapeConfig) -> None:
    if not _ask_confirm("Configure advanced options?", default=False):
        return
    cfg.headless = _ask_confirm("Run browser headless?", default=cfg.headless)
    cfg.retries = int(
        _ask_text("Retries per URL", default=str(cfg.retries), validate=_validate_int(0))
    )
    cfg.rate_per_second = float(
        _ask_text(
            "Max requests / second per host (0 = unlimited)",
            default=str(cfg.rate_per_second),
            validate=_validate_float_min(0.0),
        )
    )
    cfg.concurrency = int(
        _ask_text(
            "Concurrent workers",
            default=str(cfg.concurrency),
            validate=_validate_int(1),
        )
    )
    cfg.obey_robots = _ask_confirm("Obey robots.txt?", default=cfg.obey_robots)
    cfg.deduplicate = _ask_confirm("Deduplicate rows after merge?", default=cfg.deduplicate)
    cfg.write_provenance = _ask_confirm("Write provenance sidecar?", default=cfg.write_provenance)
    headers_raw = _ask_text(
        "Extra headers as JSON (or empty)",
        default=json.dumps(cfg.headers) if cfg.headers else "",
        validate=_validate_json_dict,
    )
    cfg.headers = json.loads(headers_raw) if headers_raw.strip() else {}


def _step_confirm(cfg: ScrapeConfig) -> None:
    choice = _ask_select(
        "Start scrape?",
        choices=["Yes", "No"],
        default="Yes",
    )
    if choice == "No":
        raise _Abort


def run_interactive(initial: ScrapeConfig | None = None) -> ScrapeConfig | None:
    rprint(BANNER)
    rprint("[bold green]Welcome to SandPaper[/bold green]\n")

    cfg = initial or ScrapeConfig()
    mode_holder: dict[str, str] = {}

    steps: list[Callable[[ScrapeConfig], None]] = [
        _step_preset,
        lambda c: mode_holder.update(value=_step_mode(c)),
        lambda c: _step_target(c, mode_holder["value"]),
        _step_extractor,
        _step_format,
        _step_output,
        _step_advanced,
        _step_confirm,
    ]

    index = 0
    while index < len(steps):
        try:
            steps[index](cfg)
            index += 1
        except _Back:
            if index == 0:
                rprint("[yellow]Already at the first question.[/yellow]")
                continue
            index -= 1
        except _Abort:
            rprint("\n[bold yellow]Aborted.[/bold yellow]")
            return None

    return cfg
