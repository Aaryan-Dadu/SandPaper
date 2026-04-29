"""Recipe replay engine.

Walks the recipe steps in order against a BrowserSession. Each action
is one method on RecipeRunner. The output is a ScrapeResult so it
plugs into the existing exporter and provenance pipeline.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional, Union

from .config import ScrapeConfig
from .core import _post_process, _records_to_columns, _run_follows
from .exceptions import ConfigError, SandpaperError
from .extractors import HeuristicExtractor, SelectorExtractor
from .loaders.playwright_loader import LoaderOptions
from .loaders.session import BrowserSession
from .pagination import detect_next_link, is_same_origin
from .plugins import get_exporter
from .provenance import write_quality_report, write_sidecar
from .recipes import Recipe, interpolate, resolve_params
from .types import ExtractedTable, Provenance, ScrapeResult
from .utils import package_version

log = logging.getLogger("sandpaper.recipe")


class RecipeRunner:
    """Execute a Recipe against a BrowserSession.

    The runner accumulates rows from extract steps. The last extract sets
    the canonical row set; follow steps enrich it. After the last step,
    the runner returns a ScrapeResult that flows through the same
    exporter and provenance pipeline as `core.scrape()`.
    """

    def __init__(self, recipe: Recipe, cfg: ScrapeConfig, params: Optional[dict[str, Any]] = None):
        self.recipe = recipe
        self.cfg = cfg
        self.params = resolve_params(recipe.params, params or {})
        self.rows: list[dict[str, str]] = []
        self.keys: list[str] = []
        self.visited: list[str] = []

    # ----------------------------------------------------------- main

    def run(self, on_progress=None) -> ScrapeResult:
        started = datetime.now(timezone.utc).isoformat()
        loader_options = self._loader_options()
        with BrowserSession(loader_options) as session:
            for index, raw_step in enumerate(self.recipe.steps, start=1):
                step = interpolate(raw_step, self.params)
                action = step["action"]
                if on_progress:
                    on_progress(index, len(self.recipe.steps), action, "running")
                handler = getattr(self, f"_step_{action}", None)
                if handler is None:
                    raise ConfigError(f"unknown action {action!r} at step {index}")
                handler(session, step)
                if on_progress:
                    on_progress(index, len(self.recipe.steps), action, "ok")
        finished = datetime.now(timezone.utc).isoformat()

        columns = _records_to_columns(self.keys, self.rows)
        columns = _post_process(columns, self.cfg)
        table = ExtractedTable(
            columns=columns, source_url=self.visited[0] if self.visited else None
        )

        provenance = Provenance(
            source_urls=self.visited,
            started_at=started,
            finished_at=finished,
            extractor="recipe",
            loader="playwright-session",
            selectors={},
            sandpaper_version=package_version(),
            options={
                "recipe_name": self.recipe.name,
                "recipe_version": self.recipe.version,
                "recipe_path": str(self.recipe.source_path) if self.recipe.source_path else None,
                "params": self.params,
                "step_count": len(self.recipe.steps),
            },
        )

        output_path: Optional[str] = None
        if self.cfg.output and table.row_count() > 0:
            from .core import _exporter_kwargs

            exporter = get_exporter(self.cfg.format, **_exporter_kwargs(self.cfg))
            output_path = exporter.export(table, self.cfg.output)
            if self.cfg.write_provenance:
                write_sidecar(provenance, output_path)
            if self.cfg.quality_report:
                write_quality_report(table, output_path)
        elif self.cfg.output:
            log.warning(
                "recipe %r produced no rows; skipping export to %s",
                self.recipe.name,
                self.cfg.output,
            )

        return ScrapeResult(table=table, provenance=provenance, output_path=output_path)

    # ----------------------------------------------------------- helpers

    def _loader_options(self) -> LoaderOptions:
        cfg = self.cfg
        return LoaderOptions(
            headless=cfg.headless,
            timeout_ms=cfg.timeout_ms,
            scroll=cfg.scroll,
            scroll_pause=cfg.scroll_pause,
            max_scrolls=cfg.max_scrolls,
            user_agent=cfg.user_agent or LoaderOptions().user_agent,
            rotate_user_agents=cfg.rotate_user_agents,
            headers=dict(cfg.headers),
            cookies=list(cfg.cookies),
            storage_state=cfg.storage_state,
            proxy=cfg.proxy,
            proxies=tuple(cfg.proxies or ()),
            rate_per_second=cfg.rate_per_second,
            random_delay_ms=cfg.random_delay_ms,
            obey_robots=cfg.obey_robots,
            allow_on_robots_error=cfg.allow_on_robots_error,
            cache_dir=cfg.cache_dir,
            cache_ttl_seconds=cfg.cache_ttl_seconds,
            block_resources=tuple(cfg.block_resources or ()),
            dismiss_overlays=cfg.dismiss_overlays,
        )

    def _set_rows(self, table: ExtractedTable) -> None:
        new_keys = list(table.columns.keys())
        for key in new_keys:
            if key not in self.keys:
                self.keys.append(key)
        n = table.row_count()
        for i in range(n):
            self.rows.append(
                {k: (table.columns[k][i] if i < len(table.columns[k]) else "") for k in new_keys}
            )

    # ----------------------------------------------------------- actions

    def _step_goto(self, session: BrowserSession, step: dict) -> None:
        url = step["url"]
        log.info("goto %s", url)
        session.goto(url)
        self.visited.append(url)

    def _step_wait_for(self, session: BrowserSession, step: dict) -> None:
        if step.get("selector"):
            session.wait_for_selector(step["selector"], timeout_ms=step.get("timeout_ms"))
        elif step.get("load_state"):
            session.wait_for_load_state(step["load_state"])

    def _step_wait(self, session: BrowserSession, step: dict) -> None:
        session.wait(int(step["ms"]))

    def _step_fill(self, session: BrowserSession, step: dict) -> None:
        session.fill(step["selector"], str(step["value"]))

    def _step_click(self, session: BrowserSession, step: dict) -> None:
        session.click(step["selector"])
        if step.get("wait_for_navigation"):
            session.wait_for_load_state("networkidle")

    def _step_press(self, session: BrowserSession, step: dict) -> None:
        session.press(step["selector"], str(step["key"]))

    def _step_scroll(self, session: BrowserSession, step: dict) -> None:
        session.scroll_to_bottom(
            max_scrolls=step.get("max_scrolls"),
            pause_ms=step.get("pause_ms"),
        )

    def _step_evaluate(self, session: BrowserSession, step: dict) -> None:
        session.evaluate(step["script"])

    def _step_save_storage_state(self, session: BrowserSession, step: dict) -> None:
        session.save_storage_state(step["path"])

    def _step_extract(self, session: BrowserSession, step: dict) -> None:
        html = session.content()
        url = session.url
        if url not in self.visited:
            self.visited.append(url)
        ex: Union[HeuristicExtractor, SelectorExtractor]
        if step.get("heuristic"):
            ex = HeuristicExtractor(threshold=int(step.get("threshold", 1)))
        else:
            selectors = step.get("selectors") or {}
            if not selectors:
                raise ConfigError("extract step needs 'selectors' or 'heuristic': true")
            ex = SelectorExtractor(
                selectors=selectors,
                row_selector=step.get("row_selector"),
            )
        table = ex.extract(html, source_url=url)
        self._set_rows(table)
        log.info("extract: %d rows / %d columns", table.row_count(), len(table.columns))

    def _step_extract_paginated(self, session: BrowserSession, step: dict) -> None:
        selectors = step["selectors"]
        row_selector = step["row_selector"]
        next_selector = step.get("next_selector")
        max_pages = int(step.get("max_pages", 1))
        same_origin = step.get("same_origin", True)
        ex = SelectorExtractor(selectors=selectors, row_selector=row_selector)

        start_url = session.url
        for page_index in range(1, max_pages + 1):
            url = session.url
            if url not in self.visited:
                self.visited.append(url)
            html = session.content()
            table = ex.extract(html, source_url=url)
            self._set_rows(table)
            log.info(
                "paginated %d/%d: +%d rows from %s", page_index, max_pages, table.row_count(), url
            )
            if page_index >= max_pages:
                break
            next_url = (
                session.evaluate(
                    f"() => {{ const a = document.querySelector({json.dumps(next_selector)}); "
                    "return a ? a.href : null; }}"
                )
                if next_selector
                else detect_next_link(html, url)
            )
            if not next_url:
                log.info("paginated: no next link, stopping")
                break
            if same_origin and not is_same_origin(start_url, next_url):
                log.info("paginated: next link crosses origin, stopping")
                break
            session.goto(next_url)

    def _step_follow(self, session: BrowserSession, step: dict) -> None:
        if not self.rows:
            log.warning("follow step before any extract; nothing to follow")
            return
        field = step["field"]
        selectors = step["selectors"]
        follow_cfg = ScrapeConfig(
            url=session.url,
            extractor="selector",
            selectors=selectors,
            follow_field=field,
            follow_selectors=selectors,
            follow_concurrency=int(step.get("concurrency", self.cfg.follow_concurrency)),
            follow_skip_on_error=bool(step.get("skip_on_error", self.cfg.follow_skip_on_error)),
            follow_url_prefix=step.get("url_prefix") or self.cfg.follow_url_prefix,
            follow_row_selector=step.get("row_selector"),
            **self._loader_passthrough(),
        )
        try:
            self.keys, self.rows = _run_follows(self.keys, self.rows, follow_cfg, on_progress=None)
        except SandpaperError as exc:
            log.error("follow step failed: %s", exc)
            if not follow_cfg.follow_skip_on_error:
                raise

    def _loader_passthrough(self) -> dict[str, Any]:
        cfg = self.cfg
        return {
            "headless": cfg.headless,
            "scroll": cfg.scroll,
            "scroll_pause": cfg.scroll_pause,
            "max_scrolls": cfg.max_scrolls,
            "wait_for_selector": cfg.wait_for_selector,
            "extra_wait_ms": cfg.extra_wait_ms,
            "timeout_ms": cfg.timeout_ms,
            "retries": cfg.retries,
            "rate_per_second": cfg.rate_per_second,
            "obey_robots": cfg.obey_robots,
            "allow_on_robots_error": cfg.allow_on_robots_error,
            "cache_dir": cfg.cache_dir,
            "cache_ttl_seconds": cfg.cache_ttl_seconds,
            "block_resources": list(cfg.block_resources),
            "dismiss_overlays": cfg.dismiss_overlays,
            "rotate_user_agents": cfg.rotate_user_agents,
            "user_agent": cfg.user_agent,
            "headers": dict(cfg.headers),
            "cookies": list(cfg.cookies),
            "storage_state": cfg.storage_state,
            "proxy": cfg.proxy,
            "proxies": list(cfg.proxies),
            "random_delay_ms": cfg.random_delay_ms,
        }
