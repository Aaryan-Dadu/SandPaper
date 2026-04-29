from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

from .config import ScrapeConfig
from .exceptions import LoadError, SandpaperError
from .extractors import HeuristicExtractor, SelectorExtractor
from .extractors.base import Extractor
from .loaders.playwright_loader import LoaderOptions, PlaywrightLoader
from .pagination import detect_next_link, expand_template, is_same_origin
from .plugins import get_exporter
from .presets import load_preset
from .provenance import write_quality_report, write_sidecar
from .throttle import RateLimiter
from .types import ExtractedTable, Provenance, ScrapeResult
from .utils import is_valid_url, merge_columns, package_version, parse_page_range

log = logging.getLogger("sandpaper.core")


def _build_loader(
    cfg: ScrapeConfig,
    shared_limiter: Optional[RateLimiter] = None,
) -> PlaywrightLoader:
    options = LoaderOptions(
        headless=cfg.headless,
        timeout_ms=cfg.timeout_ms,
        scroll=cfg.scroll,
        scroll_pause=cfg.scroll_pause,
        max_scrolls=cfg.max_scrolls,
        wait_for_selector=cfg.wait_for_selector,
        extra_wait_ms=cfg.extra_wait_ms,
        user_agent=cfg.user_agent or LoaderOptions().user_agent,
        rotate_user_agents=cfg.rotate_user_agents,
        headers=dict(cfg.headers),
        cookies=list(cfg.cookies),
        storage_state=cfg.storage_state,
        proxy=cfg.proxy,
        proxies=tuple(cfg.proxies or ()),
        retries=cfg.retries,
        rate_per_second=cfg.rate_per_second,
        random_delay_ms=cfg.random_delay_ms,
        obey_robots=cfg.obey_robots,
        allow_on_robots_error=cfg.allow_on_robots_error,
        cache_dir=cfg.cache_dir,
        cache_ttl_seconds=cfg.cache_ttl_seconds,
        block_resources=tuple(cfg.block_resources or ()),
        dismiss_overlays=cfg.dismiss_overlays,
    )
    return PlaywrightLoader(options, shared_limiter=shared_limiter)


def _build_extractor(cfg: ScrapeConfig) -> Extractor:
    if cfg.extractor == "selector":
        if not cfg.selectors:
            raise SandpaperError("extractor=selector requires non-empty selectors")
        return SelectorExtractor(selectors=cfg.selectors, row_selector=cfg.row_selector)
    if cfg.extractor == "heuristic":
        return HeuristicExtractor(
            threshold=cfg.threshold,
            min_text_length=cfg.min_text_length,
            max_text_length=cfg.max_text_length,
            skip_class_keywords=cfg.skip_class_keywords or None,
            near_dup_ratio=cfg.near_dup_ratio,
            prefer_records=cfg.prefer_records,
            max_fields_per_record=cfg.max_fields_per_record,
        )
    from .plugins import get_extractor

    return get_extractor(cfg.extractor)


def _resolve_urls(cfg: ScrapeConfig) -> list[str]:
    if cfg.url_list:
        return list(cfg.url_list)
    if cfg.page_template and cfg.pages:
        pages = parse_page_range(cfg.pages, max_pages=cfg.max_pages_limit)
        return expand_template(cfg.page_template, pages)
    if cfg.url:
        return [cfg.url]
    raise SandpaperError("no URLs to scrape")


def _apply_preset(cfg: ScrapeConfig) -> ScrapeConfig:
    if cfg.preset:
        return load_preset(cfg.preset).merge(cfg)
    return cfg


def _scrape_serial(
    urls: list[str],
    loader: PlaywrightLoader,
    extractor: Extractor,
    on_progress=None,
) -> tuple[dict[str, list[str]], list[str]]:
    columns: dict[str, list[str]] = {}
    visited: list[str] = []
    for index, url in enumerate(urls, start=1):
        if on_progress:
            on_progress(index, len(urls), url, None)
        try:
            result = loader.load(url)
            table = extractor.extract(result.html, source_url=url)
            merge_columns(columns, table.columns)
            visited.append(url)
            if on_progress:
                on_progress(index, len(urls), url, "ok")
        except SandpaperError as exc:
            log.error("%s: %s", url, exc)
            if on_progress:
                on_progress(index, len(urls), url, f"error: {exc}")
    return columns, visited


def _scrape_concurrent(
    urls: list[str],
    cfg: ScrapeConfig,
    extractor: Extractor,
    on_progress=None,
) -> tuple[dict[str, list[str]], list[str]]:
    columns: dict[str, list[str]] = {}
    visited: list[str] = []
    lock = threading.Lock()
    local = threading.local()
    loaders: list[PlaywrightLoader] = []
    loaders_lock = threading.Lock()
    shared_limiter = RateLimiter(cfg.rate_per_second)

    def get_loader() -> PlaywrightLoader:
        loader = getattr(local, "loader", None)
        if loader is None:
            loader = _build_loader(cfg, shared_limiter=shared_limiter)
            local.loader = loader
            with loaders_lock:
                loaders.append(loader)
        return loader

    def worker(url: str) -> Optional[ExtractedTable]:
        loader = get_loader()
        result = loader.load(url)
        return extractor.extract(result.html, source_url=url)

    try:
        with ThreadPoolExecutor(max_workers=cfg.concurrency) as ex:
            futures = {ex.submit(worker, u): u for u in urls}
            for index, fut in enumerate(as_completed(futures), start=1):
                url = futures[fut]
                try:
                    table = fut.result()
                    with lock:
                        if table is not None:
                            merge_columns(columns, table.columns)
                            visited.append(url)
                    if on_progress:
                        on_progress(index, len(urls), url, "ok")
                except SandpaperError as exc:
                    log.error("%s: %s", url, exc)
                    if on_progress:
                        on_progress(index, len(urls), url, f"error: {exc}")
    finally:
        for loader in loaders:
            try:
                loader.close()
            except Exception:
                pass
    return columns, visited


def _scrape_auto(
    start_url: str,
    cfg: ScrapeConfig,
    loader: PlaywrightLoader,
    extractor: Extractor,
    on_progress=None,
) -> tuple[dict[str, list[str]], list[str]]:
    columns: dict[str, list[str]] = {}
    visited: list[str] = []
    seen: set[str] = set()
    current: Optional[str] = start_url
    count = 0
    while current and count < cfg.max_auto_pages:
        if current in seen:
            break
        seen.add(current)
        count += 1
        if on_progress:
            on_progress(count, cfg.max_auto_pages, current, None)
        try:
            result = loader.load(current)
            table = extractor.extract(result.html, source_url=current)
            merge_columns(columns, table.columns)
            visited.append(current)
            if on_progress:
                on_progress(count, cfg.max_auto_pages, current, "ok")
            next_url = detect_next_link(result.html, current)
            if next_url and is_same_origin(start_url, next_url):
                current = next_url
            else:
                current = None
        except LoadError as exc:
            log.error("%s", exc)
            if on_progress:
                on_progress(count, cfg.max_auto_pages, current, f"error: {exc}")
            break
    return columns, visited


def _resolve_follow_url(value: str, base: Optional[str], prefix: Optional[str]) -> Optional[str]:
    candidate = (value or "").strip()
    if not candidate:
        return None
    if prefix and not candidate.startswith(("http://", "https://")):
        candidate = prefix.rstrip("/") + "/" + candidate.lstrip("/")
    if not candidate.startswith(("http://", "https://")) and base:
        candidate = urljoin(base, candidate)
    return candidate if is_valid_url(candidate) else None


def _columns_to_records(columns: dict[str, list[str]]) -> tuple[list[str], list[dict[str, str]]]:
    keys = list(columns.keys())
    if not keys:
        return keys, []
    n = max((len(v) for v in columns.values()), default=0)
    rows: list[dict[str, str]] = []
    for i in range(n):
        rows.append({k: columns[k][i] if i < len(columns[k]) else "" for k in keys})
    return keys, rows


def _records_to_columns(keys: list[str], rows: list[dict[str, str]]) -> dict[str, list[str]]:
    columns: dict[str, list[str]] = {k: [] for k in keys}
    for row in rows:
        for k in keys:
            columns[k].append(row.get(k, ""))
    return columns


def _run_follows(
    base_keys: list[str],
    rows: list[dict[str, str]],
    cfg: ScrapeConfig,
    on_progress=None,
) -> tuple[list[str], list[dict[str, str]]]:
    if not cfg.follow_field or not cfg.follow_selectors or not rows:
        return base_keys, rows

    follow_extractor = SelectorExtractor(
        selectors=cfg.follow_selectors,
        row_selector=cfg.follow_row_selector,
    )
    follow_keys = list(cfg.follow_selectors.keys())
    merged_keys = list(base_keys)
    for k in follow_keys:
        if k not in merged_keys:
            merged_keys.append(k)

    def detail_for(loader: PlaywrightLoader, url: str) -> dict[str, str]:
        result = loader.load(url)
        if cfg.follow_row_selector:
            table = follow_extractor.extract(result.html, source_url=url)
            return {k: (table.columns[k][0] if table.columns.get(k) else "") for k in follow_keys}
        return follow_extractor.extract_one(result.html, source_url=url)

    base_url = cfg.url
    total = len(rows)
    log.info("following %s links from %d rows", cfg.follow_field, total)

    if cfg.follow_concurrency <= 1:
        loader = _build_loader(cfg)
        try:
            for index, row in enumerate(rows, start=1):
                target = _resolve_follow_url(
                    row.get(cfg.follow_field, ""), base_url, cfg.follow_url_prefix
                )
                if target is None:
                    if on_progress:
                        on_progress(index, total, "(skipped)", "no-url")
                    continue
                try:
                    detail = detail_for(loader, target)
                    row.update({k: detail.get(k, "") for k in follow_keys})
                    if on_progress:
                        on_progress(index, total, target, "ok")
                except SandpaperError as exc:
                    log.error("follow %s: %s", target, exc)
                    if on_progress:
                        on_progress(index, total, target, f"error: {exc}")
                    if not cfg.follow_skip_on_error:
                        raise
        finally:
            loader.close()
        return merged_keys, rows

    # concurrent fan-out, per-thread persistent loader, shared rate limit
    local = threading.local()
    loaders: list[PlaywrightLoader] = []
    loaders_lock = threading.Lock()
    shared_limiter = RateLimiter(cfg.rate_per_second)

    def get_loader() -> PlaywrightLoader:
        loader = getattr(local, "loader", None)
        if loader is None:
            loader = _build_loader(cfg, shared_limiter=shared_limiter)
            local.loader = loader
            with loaders_lock:
                loaders.append(loader)
        return loader

    def worker(row: dict[str, str], target: str) -> Optional[dict[str, str]]:
        return detail_for(get_loader(), target)

    targets: list[tuple[int, dict[str, str], str]] = []
    for index, row in enumerate(rows):
        url = _resolve_follow_url(row.get(cfg.follow_field, ""), base_url, cfg.follow_url_prefix)
        if url:
            targets.append((index, row, url))

    completed = 0
    try:
        with ThreadPoolExecutor(max_workers=cfg.follow_concurrency) as ex:
            futures = {ex.submit(worker, row, url): (idx, row, url) for idx, row, url in targets}
            for future in as_completed(futures):
                idx, row, url = futures[future]
                completed += 1
                try:
                    follow_detail: Optional[dict[str, str]] = future.result()
                    if follow_detail:
                        row.update({k: follow_detail.get(k, "") for k in follow_keys})
                    if on_progress:
                        on_progress(completed, total, url, "ok")
                except SandpaperError as exc:
                    log.error("follow %s: %s", url, exc)
                    if on_progress:
                        on_progress(completed, total, url, f"error: {exc}")
                    if not cfg.follow_skip_on_error:
                        raise
    finally:
        for loader in loaders:
            try:
                loader.close()
            except Exception:
                pass

    return merged_keys, rows


def _trim_columns(columns: dict[str, list[str]]) -> dict[str, list[str]]:
    return {k: [v.strip() if isinstance(v, str) else v for v in vs] for k, vs in columns.items()}


def _rename_columns(columns: dict[str, list[str]], mapping: dict[str, str]) -> dict[str, list[str]]:
    if not mapping:
        return columns
    out: dict[str, list[str]] = {}
    seen: dict[str, int] = {}
    for key, values in columns.items():
        new_key = mapping.get(key, key)
        if new_key in out:
            count = seen.get(new_key, 1) + 1
            seen[new_key] = count
            new_key = f"{new_key}_{count}"
        out[new_key] = values
    return out


def _select_columns(
    columns: dict[str, list[str]],
    keep: list[str],
    drop: list[str],
) -> dict[str, list[str]]:
    if keep:
        kept = {k: columns[k] for k in keep if k in columns}
        if not kept:
            log.warning("--keep-columns matched no extracted columns: %s", keep)
        return kept
    if drop:
        return {k: v for k, v in columns.items() if k not in drop}
    return columns


def _enforce_required(columns: dict[str, list[str]], required: list[str]) -> dict[str, list[str]]:
    if not required:
        return columns
    missing = [c for c in required if c not in columns]
    if missing:
        log.warning("required columns missing from extraction: %s; keeping rows as-is", missing)
        required = [c for c in required if c in columns]
    if not required:
        return columns
    keys = list(columns.keys())
    n = max((len(v) for v in columns.values()), default=0)
    keep_indices = [
        i
        for i in range(n)
        if all(
            (
                columns[c][i].strip()
                if i < len(columns[c]) and isinstance(columns[c][i], str)
                else ""
            )
            for c in required
        )
    ]
    if len(keep_indices) == n:
        return columns
    log.info(
        "required columns filter: kept %d of %d rows (required=%s)",
        len(keep_indices),
        n,
        required,
    )
    return {k: [columns[k][i] if i < len(columns[k]) else "" for i in keep_indices] for k in keys}


def _apply_schema_lock(columns: dict[str, list[str]], lock_after: int) -> dict[str, list[str]]:
    """Infer schema from the first lock_after rows; drop later columns not in schema."""
    if lock_after <= 0 or not columns:
        return columns
    n = max((len(v) for v in columns.values()), default=0)
    if n <= lock_after:
        return columns
    locked: list[str] = []
    for key, values in columns.items():
        head = values[:lock_after]
        if any((v.strip() if isinstance(v, str) else v) for v in head):
            locked.append(key)
    dropped = [k for k in columns if k not in locked]
    if dropped:
        log.info(
            "schema lock: dropped %d columns absent in first %d rows: %s",
            len(dropped),
            lock_after,
            dropped,
        )
    return {k: columns[k] for k in locked}


def _post_process(columns: dict[str, list[str]], cfg: ScrapeConfig) -> dict[str, list[str]]:
    if cfg.trim_cells:
        columns = _trim_columns(columns)
    columns = _select_columns(columns, cfg.keep_columns, cfg.drop_columns)
    columns = _rename_columns(columns, cfg.rename_columns)
    columns = _enforce_required(columns, cfg.required_columns)
    columns = _apply_schema_lock(columns, cfg.schema_lock_after)
    return columns


def _build_async_loader(cfg: ScrapeConfig, max_pages: int):
    from .loaders.async_loader import AsyncPlaywrightLoader

    options = LoaderOptions(
        headless=cfg.headless,
        timeout_ms=cfg.timeout_ms,
        scroll=cfg.scroll,
        scroll_pause=cfg.scroll_pause,
        max_scrolls=cfg.max_scrolls,
        wait_for_selector=cfg.wait_for_selector,
        extra_wait_ms=cfg.extra_wait_ms,
        user_agent=cfg.user_agent or LoaderOptions().user_agent,
        rotate_user_agents=cfg.rotate_user_agents,
        headers=dict(cfg.headers),
        cookies=list(cfg.cookies),
        storage_state=cfg.storage_state,
        proxy=cfg.proxy,
        proxies=tuple(cfg.proxies or ()),
        retries=cfg.retries,
        rate_per_second=cfg.rate_per_second,
        random_delay_ms=cfg.random_delay_ms,
        obey_robots=cfg.obey_robots,
        allow_on_robots_error=cfg.allow_on_robots_error,
        cache_dir=cfg.cache_dir,
        cache_ttl_seconds=cfg.cache_ttl_seconds,
        block_resources=tuple(cfg.block_resources or ()),
        dismiss_overlays=cfg.dismiss_overlays,
    )
    return AsyncPlaywrightLoader(options, max_pages=max_pages)


def _scrape_async(
    urls: list[str],
    cfg: ScrapeConfig,
    extractor: Extractor,
    on_progress=None,
) -> tuple[dict[str, list[str]], list[str]]:
    import asyncio

    columns: dict[str, list[str]] = {}
    visited: list[str] = []

    async def runner() -> None:
        loader = _build_async_loader(cfg, max_pages=cfg.concurrency)
        sem = asyncio.Semaphore(max(1, cfg.concurrency))

        async def fetch(url: str, index: int) -> None:
            async with sem:
                try:
                    result = await loader.load(url)
                    table = extractor.extract(result.html, source_url=url)
                    columns_lock.acquire()
                    try:
                        merge_columns(columns, table.columns)
                        visited.append(url)
                    finally:
                        columns_lock.release()
                    if on_progress:
                        on_progress(index, len(urls), url, "ok")
                except SandpaperError as exc:
                    log.error("%s: %s", url, exc)
                    if on_progress:
                        on_progress(index, len(urls), url, f"error: {exc}")

        try:
            await loader._ensure_browser()
            await asyncio.gather(*(fetch(u, i + 1) for i, u in enumerate(urls)))
        finally:
            await loader.close()

    columns_lock = threading.Lock()
    asyncio.run(runner())
    return columns, visited


def _deduplicate(columns: dict[str, list[str]]) -> dict[str, list[str]]:
    if not columns:
        return columns
    max_len = max(len(v) for v in columns.values())
    rows: list[tuple] = []
    seen_rows: set[tuple] = set()
    keys = list(columns.keys())
    for i in range(max_len):
        row = tuple(columns[k][i] if i < len(columns[k]) else "" for k in keys)
        if row in seen_rows:
            continue
        seen_rows.add(row)
        rows.append(row)
    out: dict[str, list[str]] = {k: [] for k in keys}
    for row in rows:
        for k, v in zip(keys, row):
            out[k].append(v)
    return out


def scrape(cfg: ScrapeConfig, on_progress=None) -> ScrapeResult:
    cfg = _apply_preset(cfg)

    extractor = _build_extractor(cfg)
    started = datetime.now(timezone.utc).isoformat()

    if cfg.auto_paginate and cfg.url:
        loader = _build_loader(cfg)
        try:
            columns, visited = _scrape_auto(cfg.url, cfg, loader, extractor, on_progress)
        finally:
            loader.close()
    else:
        urls = _resolve_urls(cfg)
        if cfg.async_mode and len(urls) > 1:
            columns, visited = _scrape_async(urls, cfg, extractor, on_progress)
        elif cfg.concurrency > 1 and len(urls) > 1:
            columns, visited = _scrape_concurrent(urls, cfg, extractor, on_progress)
        else:
            loader = _build_loader(cfg)
            try:
                columns, visited = _scrape_serial(urls, loader, extractor, on_progress)
            finally:
                loader.close()

    if cfg.follow_field and cfg.follow_selectors:
        keys, rows = _columns_to_records(columns)
        keys, rows = _run_follows(keys, rows, cfg, on_progress)
        columns = _records_to_columns(keys, rows)

    columns = _post_process(columns, cfg)

    if cfg.deduplicate:
        columns = _deduplicate(columns)

    table = ExtractedTable(columns=columns, source_url=cfg.url)
    finished = datetime.now(timezone.utc).isoformat()

    provenance = Provenance(
        source_urls=visited,
        started_at=started,
        finished_at=finished,
        extractor=cfg.extractor,
        loader="playwright",
        selectors=dict(cfg.selectors),
        sandpaper_version=package_version(),
        options={
            "format": cfg.format,
            "threshold": cfg.threshold,
            "deduplicate": cfg.deduplicate,
            "auto_paginate": cfg.auto_paginate,
            "concurrency": cfg.concurrency,
            "min_text_length": cfg.min_text_length,
            "max_text_length": cfg.max_text_length,
            "near_dup_ratio": cfg.near_dup_ratio,
            "obey_robots": cfg.obey_robots,
            "allow_on_robots_error": cfg.allow_on_robots_error,
            "rotate_user_agents": cfg.rotate_user_agents,
            "random_delay_ms": cfg.random_delay_ms,
            "csv_safe": cfg.csv_safe,
            "typed": cfg.typed,
            "follow_field": cfg.follow_field,
            "follow_selectors": dict(cfg.follow_selectors),
            "follow_concurrency": cfg.follow_concurrency,
        },
    )

    output_path: Optional[str] = None
    if cfg.output:
        if table.row_count() == 0:
            log.warning(
                "no rows extracted from %d URL(s); skipping export to %s",
                len(visited),
                cfg.output,
            )
        else:
            exporter = get_exporter(cfg.format, **_exporter_kwargs(cfg))
            output_path = exporter.export(table, cfg.output)
            if cfg.write_provenance:
                write_sidecar(provenance, output_path)
            if cfg.quality_report:
                write_quality_report(table, output_path)

    return ScrapeResult(table=table, provenance=provenance, output_path=output_path)


def _exporter_kwargs(cfg: ScrapeConfig) -> dict:
    if cfg.format == "csv":
        return {
            "encoding": cfg.encoding,
            "safe": cfg.csv_safe,
            "drop_empty_columns": cfg.json_drop_empty,
            "sort_columns": cfg.sort_columns,
            "typed": cfg.typed,
        }
    if cfg.format in {"json", "jsonl"}:
        return {
            "encoding": cfg.encoding,
            "drop_empty_columns": cfg.json_drop_empty,
            "sort_keys": cfg.json_sort_keys,
            "sort_columns": cfg.sort_columns,
            "normalize_keys": cfg.json_normalize_keys,
            "null_policy": cfg.null_policy,
        }
    if cfg.format in {"parquet", "excel", "sqlite"}:
        return {
            "typed": cfg.typed,
            "drop_empty_columns": cfg.json_drop_empty,
            "sort_columns": cfg.sort_columns,
        }
    return {}


def scrape_urls(urls: Iterable[str], output: Optional[str] = None, **overrides) -> ScrapeResult:
    cfg = ScrapeConfig(url_list=list(urls), output=output, **overrides)
    return scrape(cfg)


def scrape_url(url: str, output: Optional[str] = None, **overrides) -> ScrapeResult:
    cfg = ScrapeConfig(url=url, output=output, **overrides)
    return scrape(cfg)
