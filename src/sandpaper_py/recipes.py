"""Recipe format: a JSON document describing a sequence of browser actions.

A recipe is a portable scraper definition. It captures every step a user
takes on a page (navigate, fill, click, paginate, extract, follow into
detail pages) so the same scrape can be replayed later, or by another
machine, or on a schedule.

Format:

    {
      "name": "amazon-laptops",
      "version": 1,
      "description": "Search Amazon for laptops and scrape results",
      "params": {
        "query": {"type": "string", "default": "laptops"},
        "max_pages": {"type": "int", "default": 5}
      },
      "steps": [
        {"action": "goto", "url": "https://amazon.example.com"},
        {"action": "fill", "selector": "input.search", "value": "{{query}}"},
        {"action": "click", "selector": "button.go"},
        {"action": "extract_paginated",
         "row_selector": "li.item",
         "selectors": {"title": "h2", "url": "a@href"},
         "next_selector": "a[rel=next]",
         "max_pages": "{{max_pages}}"},
        {"action": "follow", "field": "url",
         "selectors": {"description": "div.product-description"}}
      ]
    }

Param interpolation uses ``{{name}}`` syntax. Values are converted to the
declared type from the params block; missing params fall back to defaults.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .exceptions import ConfigError

RECIPE_VERSION = 1

VALID_ACTIONS = frozenset(
    {
        "goto",
        "wait_for",
        "wait",
        "fill",
        "click",
        "press",
        "scroll",
        "evaluate",
        "extract",
        "extract_paginated",
        "follow",
        "save_storage_state",
    }
)

PARAM_REF = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


@dataclass
class RecipeParam:
    name: str
    type: str = "string"
    default: Any = None
    required: bool = False
    description: str | None = None


@dataclass
class Recipe:
    name: str
    steps: list[dict]
    version: int = RECIPE_VERSION
    description: str | None = None
    params: dict[str, RecipeParam] = field(default_factory=dict)
    output: dict | None = None  # optional default output settings (path, format)
    source_path: Path | None = None


def load_recipe(path: str | Path) -> Recipe:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"recipe not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"recipe {p} is not valid JSON: {exc}") from exc
    recipe = _from_dict(data)
    recipe.source_path = p
    validate_recipe(recipe)
    return recipe


def save_recipe(recipe: Recipe, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "name": recipe.name,
        "version": recipe.version,
        "steps": recipe.steps,
    }
    if recipe.description:
        payload["description"] = recipe.description
    if recipe.params:
        payload["params"] = {
            name: {
                "type": p_.type,
                "default": p_.default,
                "required": p_.required,
                **({"description": p_.description} if p_.description else {}),
            }
            for name, p_ in recipe.params.items()
        }
    if recipe.output:
        payload["output"] = recipe.output
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def _from_dict(data: dict) -> Recipe:
    if not isinstance(data, dict):
        raise ConfigError("recipe must be a JSON object")
    if "name" not in data:
        raise ConfigError("recipe missing 'name'")
    if "steps" not in data or not isinstance(data["steps"], list):
        raise ConfigError("recipe missing 'steps' (must be a list)")
    params_in = data.get("params") or {}
    if not isinstance(params_in, dict):
        raise ConfigError("recipe 'params' must be an object")
    params: dict[str, RecipeParam] = {}
    for name, spec in params_in.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"param {name!r} must be an object")
        params[name] = RecipeParam(
            name=name,
            type=str(spec.get("type", "string")),
            default=spec.get("default"),
            required=bool(spec.get("required", False)),
            description=spec.get("description"),
        )
    return Recipe(
        name=str(data["name"]),
        version=int(data.get("version", RECIPE_VERSION)),
        description=data.get("description"),
        params=params,
        steps=list(data["steps"]),
        output=data.get("output"),
    )


def validate_recipe(recipe: Recipe) -> None:
    if recipe.version != RECIPE_VERSION:
        raise ConfigError(
            f"recipe version {recipe.version} not supported (this build expects {RECIPE_VERSION})"
        )
    if not recipe.steps:
        raise ConfigError("recipe has no steps")
    for index, step in enumerate(recipe.steps):
        if not isinstance(step, dict):
            raise ConfigError(f"step {index} is not an object")
        action = step.get("action")
        if not action:
            raise ConfigError(f"step {index} missing 'action'")
        if action not in VALID_ACTIONS:
            raise ConfigError(
                f"step {index}: unknown action {action!r} "
                f"(valid: {', '.join(sorted(VALID_ACTIONS))})"
            )
        _validate_step(index, action, step)


def _validate_step(index: int, action: str, step: dict) -> None:
    needs: dict[str, list[str]] = {
        "goto": ["url"],
        "wait_for": [],  # one of selector or load_state required
        "wait": ["ms"],
        "fill": ["selector", "value"],
        "click": ["selector"],
        "press": ["selector", "key"],
        "scroll": [],
        "evaluate": ["script"],
        "extract": [],  # row_selector + selectors OR heuristic
        "extract_paginated": ["row_selector", "selectors"],
        "follow": ["field", "selectors"],
        "save_storage_state": ["path"],
    }
    for key in needs.get(action, []):
        if key not in step:
            raise ConfigError(f"step {index} ({action}): missing {key!r}")
    if action == "wait_for" and not (step.get("selector") or step.get("load_state")):
        raise ConfigError(f"step {index} (wait_for): need 'selector' or 'load_state'")
    if action == "extract" and not (step.get("selectors") or step.get("heuristic")):
        raise ConfigError(
            f"step {index} (extract): provide 'selectors' "
            f"(optionally with 'row_selector') or 'heuristic': true"
        )


def resolve_params(declared: dict[str, RecipeParam], provided: dict[str, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for name, spec in declared.items():
        if name in provided:
            resolved[name] = _coerce(provided[name], spec.type, name)
        elif spec.default is not None:
            resolved[name] = spec.default
        elif spec.required:
            raise ConfigError(f"param {name!r} is required but not provided")
    for name, value in provided.items():
        if name not in resolved:
            resolved[name] = value
    return resolved


def _coerce(value: Any, type_: str, name: str) -> Any:
    if value is None:
        return None
    try:
        if type_ == "int":
            return int(value)
        if type_ == "float":
            return float(value)
        if type_ == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in {"true", "1", "yes", "y"}
            return bool(value)
        return str(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"param {name!r}: cannot coerce to {type_}: {exc}") from exc


def interpolate(value: Any, params: dict[str, Any]) -> Any:
    """Replace ``{{name}}`` markers in strings; recurse into dicts/lists."""
    if isinstance(value, str):
        if "{{" not in value:
            return value

        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in params:
                raise ConfigError(f"unknown param {name!r} referenced in recipe")
            return str(params[name])

        return PARAM_REF.sub(repl, value)
    if isinstance(value, dict):
        return {k: interpolate(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, params) for v in value]
    return value


def parse_param_overrides(values: list[str]) -> dict[str, Any]:
    """Parse `key=value` CLI overrides into a dict."""
    out: dict[str, Any] = {}
    for raw in values:
        if "=" not in raw:
            raise ConfigError(f"--param expects key=value, got {raw!r}")
        key, _, val = raw.partition("=")
        out[key.strip()] = val
    return out
