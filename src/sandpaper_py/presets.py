from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w

from .config import ScrapeConfig, default_config_dir
from .exceptions import ConfigError


def presets_dir() -> Path:
    return default_config_dir() / "presets"


def list_presets() -> list[str]:
    d = presets_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.toml"))


def load_preset(name: str) -> ScrapeConfig:
    path = presets_dir() / f"{name}.toml"
    if not path.exists():
        raise ConfigError(f"preset {name!r} not found at {path}")
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    fields = ScrapeConfig().__dict__.keys()
    payload = {k: v for k, v in data.items() if k in fields}
    return ScrapeConfig(**payload)


def save_preset(name: str, config: ScrapeConfig) -> Path:
    d = presets_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.toml"
    payload = {k: v for k, v in config.__dict__.items() if v not in (None, [], {}, "")}
    with open(path, "wb") as fh:
        tomli_w.dump(payload, fh)
    return path


def delete_preset(name: str) -> bool:
    path = presets_dir() / f"{name}.toml"
    if path.exists():
        path.unlink()
        return True
    return False


def find_preset_for_url(url: str) -> str | None:
    from urllib.parse import urlparse

    host = urlparse(url).netloc.lower()
    if not host:
        return None
    for name in list_presets():
        if name.lower() == host:
            return name
        if host.endswith("." + name.lower()):
            return name
    return None
