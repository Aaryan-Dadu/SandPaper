from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w
from platformdirs import user_config_dir

from .exceptions import ConfigError


def default_config_dir() -> Path:
    return Path(user_config_dir("sandpaper"))


def default_config_path() -> Path:
    return default_config_dir() / "config.toml"


@dataclass
class ScrapeConfig:
    url: str | None = None
    pages: str | None = None
    page_template: str | None = None
    url_list: list[str] = field(default_factory=list)
    output: str | None = None
    format: str = "csv"
    encoding: str = "utf-8"
    threshold: int = 10
    extractor: str = "heuristic"
    selectors: dict[str, str] = field(default_factory=dict)
    row_selector: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    cookies: list[dict] = field(default_factory=list)
    user_agent: str | None = None
    storage_state: str | None = None
    proxy: str | None = None
    proxies: list[str] = field(default_factory=list)
    headless: bool = True
    scroll: bool = True
    scroll_pause: float = 1.0
    max_scrolls: int = 30
    wait_for_selector: str | None = None
    extra_wait_ms: int = 0
    timeout_ms: int = 60000
    retries: int = 2
    rate_per_second: float = 0.0
    obey_robots: bool = False
    allow_on_robots_error: bool = False
    concurrency: int = 1
    auto_paginate: bool = False
    max_auto_pages: int = 100
    deduplicate: bool = False
    write_provenance: bool = False
    preset: str | None = None
    log_level: str = "INFO"
    min_text_length: int = 1
    max_text_length: int = 4000
    skip_class_keywords: list[str] = field(
        default_factory=lambda: [
            "nav",
            "menu",
            "footer",
            "header",
            "sidebar",
            "breadcrumb",
            "cookie",
            "banner",
            "subscribe",
            "newsletter",
            "social",
        ]
    )
    near_dup_ratio: float = 0.85
    csv_safe: bool = False
    json_drop_empty: bool = True
    json_sort_keys: bool = False
    json_normalize_keys: bool = False
    typed: bool = False
    quality_report: bool = False
    cache_dir: str | None = None
    cache_ttl_seconds: int = 0
    rotate_user_agents: bool = False
    random_delay_ms: int = 0
    max_pages_limit: int = 10000
    sort_columns: bool = False
    block_resources: list[str] = field(default_factory=lambda: ["image", "media", "font"])
    dismiss_overlays: bool = True
    prefer_records: bool = True
    max_fields_per_record: int = 30
    follow_field: str | None = None
    follow_selectors: dict[str, str] = field(default_factory=dict)
    follow_row_selector: str | None = None
    follow_concurrency: int = 4
    follow_skip_on_error: bool = True
    follow_url_prefix: str | None = None
    rename_columns: dict[str, str] = field(default_factory=dict)
    drop_columns: list[str] = field(default_factory=list)
    keep_columns: list[str] = field(default_factory=list)
    required_columns: list[str] = field(default_factory=list)
    trim_cells: bool = True
    null_policy: str = "empty"  # "empty" | "null" | "skip"
    schema_lock_after: int = 0  # 0 = disabled; otherwise infer schema after first N rows
    async_mode: bool = False  # use async Playwright loader for the list scrape

    def merge(self, other: ScrapeConfig) -> ScrapeConfig:
        merged = ScrapeConfig(**self.__dict__)
        for key, value in other.__dict__.items():
            if isinstance(value, dict) and value:
                merged.__dict__[key] = {**merged.__dict__.get(key, {}), **value}
            elif isinstance(value, list) and value:
                merged.__dict__[key] = list(value)
            elif value is not None and value != _default_value(key):
                merged.__dict__[key] = value
        return merged


def _default_value(key: str) -> Any:
    return getattr(ScrapeConfig(), key, None)


def load_config(path: Path | None = None) -> ScrapeConfig:
    if path is None:
        path = default_config_path()
    if not path.exists():
        return ScrapeConfig()
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except Exception as exc:
        raise ConfigError(f"failed to read config {path}: {exc}") from exc
    return _from_dict(data)


def save_config(config: ScrapeConfig, path: Path | None = None) -> Path:
    if path is None:
        path = default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in config.__dict__.items() if v not in (None, [], {}, "")}
    with open(path, "wb") as fh:
        tomli_w.dump(payload, fh)
    return path


def _from_dict(data: dict) -> ScrapeConfig:
    fields = ScrapeConfig().__dict__.keys()
    payload = {k: v for k, v in data.items() if k in fields}
    return ScrapeConfig(**payload)
