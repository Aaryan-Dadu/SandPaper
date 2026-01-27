"""Tests for the recipe format, runner, and CLI surface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from sandpaper_py.cli import main
from sandpaper_py.config import ScrapeConfig
from sandpaper_py.exceptions import ConfigError
from sandpaper_py.recipe_runner import RecipeRunner
from sandpaper_py.recipes import (
    Recipe,
    RecipeParam,
    interpolate,
    load_recipe,
    parse_param_overrides,
    resolve_params,
    save_recipe,
    validate_recipe,
)

# --------------------------------------------------------------- format


def test_load_recipe_round_trip(tmp_path: Path):
    recipe = Recipe(
        name="example",
        description="example recipe",
        params={"q": RecipeParam(name="q", type="string", default="hi")},
        steps=[
            {"action": "goto", "url": "https://example.com"},
            {"action": "extract", "selectors": {"title": "h1"}},
        ],
    )
    path = tmp_path / "r.json"
    save_recipe(recipe, path)
    loaded = load_recipe(path)
    assert loaded.name == "example"
    assert loaded.params["q"].default == "hi"
    assert len(loaded.steps) == 2


def test_load_recipe_missing_file(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_recipe(tmp_path / "missing.json")


def test_load_recipe_bad_json(tmp_path: Path):
    p = tmp_path / "broken.json"
    p.write_text("{ not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_recipe(p)


def test_validate_recipe_rejects_unknown_action():
    recipe = Recipe(name="x", steps=[{"action": "explode"}])
    with pytest.raises(ConfigError, match="unknown action"):
        validate_recipe(recipe)


def test_validate_recipe_requires_steps():
    recipe = Recipe(name="x", steps=[])
    with pytest.raises(ConfigError, match="no steps"):
        validate_recipe(recipe)


def test_validate_recipe_step_required_keys():
    recipe = Recipe(name="x", steps=[{"action": "fill"}])
    with pytest.raises(ConfigError, match="missing"):
        validate_recipe(recipe)


def test_validate_extract_needs_selectors_or_heuristic():
    recipe = Recipe(name="x", steps=[{"action": "extract"}])
    with pytest.raises(ConfigError, match="extract"):
        validate_recipe(recipe)


def test_validate_wait_for_needs_one_of():
    recipe = Recipe(name="x", steps=[{"action": "wait_for"}])
    with pytest.raises(ConfigError, match="wait_for"):
        validate_recipe(recipe)


# ------------------------------------------------------- params + interp


def test_resolve_params_uses_defaults():
    declared = {"q": RecipeParam(name="q", type="string", default="hi")}
    assert resolve_params(declared, {}) == {"q": "hi"}


def test_resolve_params_required_missing():
    declared = {"q": RecipeParam(name="q", type="string", required=True)}
    with pytest.raises(ConfigError, match="required"):
        resolve_params(declared, {})


def test_resolve_params_coerces_types():
    declared = {
        "n": RecipeParam(name="n", type="int"),
        "f": RecipeParam(name="f", type="float"),
        "b": RecipeParam(name="b", type="bool"),
    }
    out = resolve_params(declared, {"n": "5", "f": "1.25", "b": "yes"})
    assert out == {"n": 5, "f": 1.25, "b": True}


def test_resolve_params_keeps_extras():
    out = resolve_params({}, {"extra": "v"})
    assert out == {"extra": "v"}


def test_interpolate_string():
    assert interpolate("q={{q}}", {"q": "laptops"}) == "q=laptops"


def test_interpolate_dict_recursive():
    out = interpolate(
        {"url": "https://e.com/?q={{q}}", "fields": ["{{f}}"]},
        {"q": "x", "f": "y"},
    )
    assert out == {"url": "https://e.com/?q=x", "fields": ["y"]}


def test_interpolate_unknown_param_raises():
    with pytest.raises(ConfigError, match="unknown param"):
        interpolate("{{missing}}", {})


def test_parse_param_overrides_basic():
    assert parse_param_overrides(["a=1", "name=hello"]) == {"a": "1", "name": "hello"}


def test_parse_param_overrides_invalid():
    with pytest.raises(ConfigError, match="key=value"):
        parse_param_overrides(["bad"])


# ------------------------------------------------------- runner with stub


class _StubSession:
    """A session stub that pretends to be a Playwright BrowserSession."""

    def __init__(self, url_to_html: dict[str, str]):
        self.url_to_html = url_to_html
        self._url = ""
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def goto(self, url: str) -> None:
        self.calls.append(("goto", {"url": url}))
        self._url = url

    def wait_for_selector(self, selector: str, timeout_ms=None) -> None:
        self.calls.append(("wait_for_selector", {"selector": selector}))

    def wait_for_load_state(self, state: str = "networkidle") -> None:
        self.calls.append(("wait_for_load_state", {"state": state}))

    def wait(self, ms: int) -> None:
        self.calls.append(("wait", {"ms": ms}))

    def fill(self, selector: str, value: str) -> None:
        self.calls.append(("fill", {"selector": selector, "value": value}))

    def click(self, selector: str) -> None:
        self.calls.append(("click", {"selector": selector}))

    def press(self, selector: str, key: str) -> None:
        self.calls.append(("press", {"selector": selector, "key": key}))

    def scroll_to_bottom(self, **_kwargs) -> None:
        self.calls.append(("scroll_to_bottom", {}))

    def evaluate(self, script: str) -> Any:
        self.calls.append(("evaluate", {"script": script}))
        return None

    def content(self) -> str:
        return self.url_to_html.get(self._url, "")

    @property
    def url(self) -> str:
        return self._url

    def save_storage_state(self, path: str) -> None:
        Path(path).write_text("{}")

    def __enter__(self) -> _StubSession:
        return self

    def __exit__(self, *args) -> None:
        pass


def _patch_session(monkeypatch, session):
    """Replace BrowserSession() in recipe_runner with a stub session factory."""

    factory = MagicMock(return_value=session)
    monkeypatch.setattr("sandpaper_py.recipe_runner.BrowserSession", factory)
    return factory


def test_runner_executes_actions_in_order(monkeypatch):
    html = (
        "<html><body><ul>"
        + "".join(
            f"<li class='card'><h2 class='name'>name{i}</h2>"
            f"<span class='price'>{i * 10}</span></li>"
            for i in range(5)
        )
        + "</ul></body></html>"
    )
    session = _StubSession({"https://e.com": html})
    _patch_session(monkeypatch, session)

    recipe = Recipe(
        name="basic",
        steps=[
            {"action": "goto", "url": "https://e.com"},
            {"action": "wait_for", "selector": "ul"},
            {
                "action": "extract",
                "row_selector": "li.card",
                "selectors": {"name": "h2.name", "price": "span.price"},
            },
        ],
    )
    cfg = ScrapeConfig()
    runner = RecipeRunner(recipe, cfg)
    result = runner.run()

    assert result.rows == 5
    assert result.table.columns["name"][0] == "name0"
    assert result.table.columns["price"][2] == "20"
    actions = [c[0] for c in session.calls]
    assert actions == ["goto", "wait_for_selector"]


def test_runner_param_interpolation(monkeypatch):
    session = _StubSession({"https://e.com/?q=laptops": "<ul></ul>"})
    _patch_session(monkeypatch, session)

    recipe = Recipe(
        name="search",
        params={"q": RecipeParam(name="q", default="laptops")},
        steps=[
            {"action": "goto", "url": "https://e.com/?q={{q}}"},
            {"action": "extract", "selectors": {"x": "div"}},
        ],
    )
    runner = RecipeRunner(recipe, ScrapeConfig(), params={"q": "laptops"})
    runner.run()
    assert ("goto", {"url": "https://e.com/?q=laptops"}) in session.calls


def test_runner_extract_paginated_stops_at_max_pages(monkeypatch):
    page1 = (
        "<html><body><ul>"
        + "".join(f"<li class='c'><span class='t'>p1-{i}</span></li>" for i in range(3))
        + "</ul></body></html>"
    )
    page2 = (
        "<html><body><ul>"
        + "".join(f"<li class='c'><span class='t'>p2-{i}</span></li>" for i in range(3))
        + "</ul></body></html>"
    )
    session = _StubSession({"https://e.com/p/1": page1, "https://e.com/p/2": page2})
    _patch_session(monkeypatch, session)

    # next link logic: extract_paginated will fall back to detect_next_link or use next_selector
    # The stub's evaluate returns None, so we wire next_selector to return a fixed URL via monkeypatch on detect_next_link.
    monkeypatch.setattr(
        "sandpaper_py.recipe_runner.detect_next_link",
        lambda html, base: "https://e.com/p/2" if "p1-" in html else None,
    )

    recipe = Recipe(
        name="paginated",
        steps=[
            {"action": "goto", "url": "https://e.com/p/1"},
            {
                "action": "extract_paginated",
                "row_selector": "li.c",
                "selectors": {"t": "span.t"},
                "max_pages": 5,
            },
        ],
    )
    result = RecipeRunner(recipe, ScrapeConfig()).run()
    assert result.rows == 6
    assert result.table.columns["t"][0] == "p1-0"
    assert result.table.columns["t"][-1] == "p2-2"


def test_runner_writes_output(monkeypatch, tmp_path: Path):
    html = (
        "<ul>"
        + "".join(f"<li class='c'><span class='t'>row{i}</span></li>" for i in range(5))
        + "</ul>"
    )
    session = _StubSession({"https://e.com": html})
    _patch_session(monkeypatch, session)

    out = tmp_path / "result.json"
    recipe = Recipe(
        name="write",
        steps=[
            {"action": "goto", "url": "https://e.com"},
            {
                "action": "extract",
                "row_selector": "li.c",
                "selectors": {"t": "span.t"},
            },
        ],
    )
    cfg = ScrapeConfig(output=str(out), format="json")
    result = RecipeRunner(recipe, cfg).run()
    assert result.output_path == str(out)
    assert out.exists()
    rows = json.loads(out.read_text())
    assert rows[0] == {"t": "row0"}


def test_runner_unknown_action_raises(monkeypatch):
    session = _StubSession({})
    _patch_session(monkeypatch, session)

    recipe = Recipe(name="bad", steps=[{"action": "fly"}])
    with pytest.raises((ConfigError, AttributeError)):
        RecipeRunner(recipe, ScrapeConfig()).run()


def test_runner_provenance_records_recipe_metadata(monkeypatch):
    session = _StubSession({"https://e.com": "<html><body><ul></ul></body></html>"})
    _patch_session(monkeypatch, session)
    recipe = Recipe(
        name="meta",
        params={"q": RecipeParam(name="q", default="x")},
        steps=[
            {"action": "goto", "url": "https://e.com"},
            {"action": "extract", "selectors": {"a": "div"}},
        ],
    )
    result = RecipeRunner(recipe, ScrapeConfig(), params={"q": "x"}).run()
    opts = result.provenance.options
    assert opts["recipe_name"] == "meta"
    assert opts["params"] == {"q": "x"}
    assert opts["step_count"] == 2


# ------------------------------------------------------- CLI


def test_run_recipe_help_lists_options():
    runner = CliRunner()
    result = runner.invoke(main, ["run-recipe", "--help"])
    assert result.exit_code == 0
    assert "--param" in result.output
    assert "--output" in result.output
    assert "--profile" in result.output


def test_record_help_describes_workflow():
    runner = CliRunner()
    result = runner.invoke(main, ["record", "--help"])
    assert result.exit_code == 0
    assert "browser session" in result.output.lower()
    assert "--output" in result.output


def test_run_recipe_invalid_recipe(tmp_path: Path):
    bad = tmp_path / "broken.json"
    bad.write_text("{ not json")
    runner = CliRunner()
    result = runner.invoke(main, ["run-recipe", str(bad)])
    assert result.exit_code != 0


def test_run_recipe_end_to_end(monkeypatch, tmp_path: Path):
    html = (
        "<ul>"
        + "".join(f"<li class='c'><span class='t'>row{i}</span></li>" for i in range(5))
        + "</ul>"
    )

    class _CLIStub(_StubSession):
        pass

    session = _CLIStub({"https://e.com": html})
    _patch_session(monkeypatch, session)

    recipe_path = tmp_path / "r.json"
    output_path = tmp_path / "out.json"
    save_recipe(
        Recipe(
            name="cli",
            steps=[
                {"action": "goto", "url": "https://e.com"},
                {
                    "action": "extract",
                    "row_selector": "li.c",
                    "selectors": {"t": "span.t"},
                },
            ],
        ),
        recipe_path,
    )

    runner = CliRunner()
    result = runner.invoke(main, ["run-recipe", str(recipe_path), "-o", str(output_path)])
    assert result.exit_code == 0
    assert output_path.exists()
    rows = json.loads(output_path.read_text())
    assert len(rows) == 5
