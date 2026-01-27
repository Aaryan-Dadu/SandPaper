from pathlib import Path

from sandpaper_py.config import ScrapeConfig, load_config, save_config
from sandpaper_py.presets import load_preset, save_preset


def test_save_and_load(tmp_path: Path):
    cfg = ScrapeConfig(url="https://example.com", threshold=15, format="json")
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.url == "https://example.com"
    assert loaded.threshold == 15
    assert loaded.format == "json"


def test_merge_overrides():
    base = ScrapeConfig(url="https://a.com", threshold=10, format="csv")
    override = ScrapeConfig(threshold=25, format="json")
    merged = base.merge(override)
    assert merged.url == "https://a.com"
    assert merged.threshold == 25
    assert merged.format == "json"


def test_merge_keeps_dict_values():
    base = ScrapeConfig(headers={"X": "1"})
    override = ScrapeConfig(headers={"Y": "2"})
    merged = base.merge(override)
    assert merged.headers == {"X": "1", "Y": "2"}


def test_load_missing_returns_default(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.format == "csv"


def test_preset_round_trip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sandpaper_py.presets.presets_dir", lambda: tmp_path)
    cfg = ScrapeConfig(url="https://example.com", threshold=42)
    save_preset("example.com", cfg)
    loaded = load_preset("example.com")
    assert loaded.threshold == 42
