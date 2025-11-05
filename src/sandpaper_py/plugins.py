from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import Any

from .exceptions import ConfigError

log = logging.getLogger("sandpaper.plugins")

EXPORTER_GROUP = "sandpaper.exporters"
EXTRACTOR_GROUP = "sandpaper.extractors"
LOADER_GROUP = "sandpaper.loaders"


def _load_group(group: str) -> dict[str, type]:
    try:
        eps = entry_points(group=group)
    except TypeError:
        eps = entry_points().get(group, [])
    result: dict[str, type] = {}
    for ep in eps:
        try:
            result[ep.name] = ep.load()
        except Exception as exc:
            log.warning("failed to load plugin %s from group %s: %s", ep.name, group, exc)
    return result


def load_exporters() -> dict[str, type]:
    return _load_group(EXPORTER_GROUP)


def load_extractors() -> dict[str, type]:
    return _load_group(EXTRACTOR_GROUP)


def load_loaders() -> dict[str, type]:
    return _load_group(LOADER_GROUP)


def get_exporter(name: str, **kwargs: Any):
    cls = load_exporters().get(name)
    if cls is None:
        raise ConfigError(f"unknown exporter {name!r}, available: {sorted(load_exporters())}")
    return cls(**kwargs)


def get_extractor(name: str, **kwargs: Any):
    cls = load_extractors().get(name)
    if cls is None:
        raise ConfigError(f"unknown extractor {name!r}, available: {sorted(load_extractors())}")
    return cls(**kwargs)


def get_loader(name: str, **kwargs: Any):
    cls = load_loaders().get(name)
    if cls is None:
        raise ConfigError(f"unknown loader {name!r}, available: {sorted(load_loaders())}")
    return cls(**kwargs)
