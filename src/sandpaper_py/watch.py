from __future__ import annotations

import logging
import time
from collections.abc import Callable

from .config import ScrapeConfig
from .core import scrape
from .types import ScrapeResult

log = logging.getLogger("sandpaper.watch")


def watch(
    cfg: ScrapeConfig,
    interval_seconds: int,
    iterations: int | None = None,
    on_run: Callable[[ScrapeResult], None] | None = None,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    count = 0
    while True:
        count += 1
        log.info("watch run #%d", count)
        try:
            result = scrape(cfg)
            if on_run:
                on_run(result)
        except Exception as exc:
            log.error("watch run failed: %s", exc)
        if iterations is not None and count >= iterations:
            return
        time.sleep(interval_seconds)


def schedule(cfg: ScrapeConfig, cron_expression: str) -> None:
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as exc:
        raise RuntimeError(
            "schedule mode needs apscheduler: pip install 'sandpaper-py[schedule]'"
        ) from exc

    scheduler = BlockingScheduler()
    trigger = CronTrigger.from_crontab(cron_expression)
    scheduler.add_job(lambda: scrape(cfg), trigger=trigger)
    log.info("scheduler started with cron %s", cron_expression)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
