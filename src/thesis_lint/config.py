"""Load `lint.toml` and the presets that it extends."""

from __future__ import annotations

import dataclasses
import importlib.resources
import tomllib
from dataclasses import dataclass, field
from functools import reduce
from typing import TYPE_CHECKING, cast

from thesis_lint.model import Severity
from thesis_lint.registry import (
    ConfigError,
    Rule,
    all_rules,
    apply_params,
    attribute,
    default_enabled,
)

if TYPE_CHECKING:
    from pathlib import Path

CONFIG_NAME = "lint.toml"

# Map from preset name to the package directory that holds the preset files.
# The loader merges all `.toml` files of the directory in name order.
PRESETS: dict[str, tuple[str, str]] = {
    "sat-meti": ("thesis_lint.packs.sat_meti", "preset"),
}

type Table = dict[str, object]


@dataclass(frozen=True, slots=True)
class RuleConfig:
    """The effective settings of one rule."""

    rule: Rule
    severity: Severity
    params: object


@dataclass(frozen=True, slots=True)
class Paths:
    """Project files, relative to the project root."""

    main: str = "main.typ"
    bib: tuple[str, ...] = ("main.bib",)
    metadata: str = "metadata.typ"
    metadata_variable: str = "settings"
    glossary: str = "glossary.typ"
    sources_dir: str = "sources"
    font_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Config:
    """The resolved configuration of a project."""

    root: Path
    paths: Paths
    rules: dict[str, RuleConfig] = field(default_factory=dict[str, RuleConfig])


@dataclass(frozen=True, slots=True)
class _RuleSettings:
    """The settings of one rule as the config file gives them."""

    enabled: bool
    severity: Severity | None
    params: Table


_NO_SETTINGS = _RuleSettings(enabled=True, severity=None, params={})


def find_root(start: Path) -> Path:
    """Return the nearest directory at or above `start` that contains `lint.toml`."""
    current = start.resolve()
    directory = current.parent if current.is_file() else current
    found = next(
        (path for path in (directory, *directory.parents) if (path / CONFIG_NAME).is_file()), None
    )
    if found is None:
        msg = f"no {CONFIG_NAME} found in {start} or its parents"
        raise ConfigError(msg)
    return found


def load(root: Path) -> Config:
    """Read `root/lint.toml`, resolve `extends` and make the effective rule settings."""
    raw = _read_with_extends(root / CONFIG_NAME, frozenset())
    rules = all_rules()
    settings = {
        rule_id: _rule_settings(rule_id, value, rules)
        for rule_id, value in _table(raw, "rules").items()
    }
    disabled = {rule_id for rule_id, s in settings.items() if not s.enabled}
    enabled = (default_enabled() | settings.keys()) - disabled

    def effective(rule_id: str) -> RuleConfig:
        rule = rules[rule_id]
        given = settings.get(rule_id, _NO_SETTINGS)
        return RuleConfig(
            rule=rule,
            severity=given.severity or rule.severity,
            params=apply_params(rule.params, given.params, rule_id),
        )

    return Config(
        root=root,
        paths=_paths(_table(raw, "paths")),
        rules={rule_id: effective(rule_id) for rule_id in sorted(enabled)},
    )


def _rule_settings(rule_id: str, value: object, rules: dict[str, Rule]) -> _RuleSettings:
    if rule_id not in rules:
        msg = f"{CONFIG_NAME}: unknown rule {rule_id!r}"
        raise ConfigError(msg)
    table = _as_table(value, f"rules.{rule_id}")
    state = table.get("enabled", True)
    if not isinstance(state, bool):
        msg = f"rules.{rule_id}.enabled must be a boolean"
        raise ConfigError(msg)
    level = table.get("severity")
    if level is not None and level not in {"error", "warning"}:
        msg = f"rules.{rule_id}.severity must be 'error' or 'warning'"
        raise ConfigError(msg)
    return _RuleSettings(
        enabled=state,
        severity=None if level is None else Severity(cast("str", level)),
        params={k: v for k, v in table.items() if k not in {"enabled", "severity"}},
    )


def _read_with_extends(path: Path, seen: frozenset[str]) -> Table:
    data = _read_toml(path)
    return _merge(_extended(data, path.parent, seen), _without_extends(data))


def _extended(data: Table, base: Path, seen: frozenset[str]) -> Table:
    names = _str_list(data.get("extends", []), "extends")
    cycle = next((name for name in names if name in seen), None)
    if cycle is not None:
        msg = f"extends cycle at {cycle!r}"
        raise ConfigError(msg)
    presets = (_read_preset(name, base, seen | {name}) for name in names)
    return reduce(_merge, presets, {})


def _read_preset(name: str, base: Path, seen: frozenset[str]) -> Table:
    if name not in PRESETS:
        return _read_with_extends((base / name).resolve(), seen)
    package, directory = PRESETS[name]
    files = sorted(
        (
            entry
            for entry in importlib.resources.files(package).joinpath(directory).iterdir()
            if entry.name.endswith(".toml")
        ),
        key=lambda entry: entry.name,
    )
    parts: list[Table] = [tomllib.loads(entry.read_text(encoding="utf-8")) for entry in files]
    data = reduce(_merge, parts, {})
    return _merge(_extended(data, base, seen), _without_extends(data))


def _without_extends(data: Table) -> Table:
    return {key: value for key, value in data.items() if key != "extends"}


def _read_toml(path: Path) -> Table:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:
        msg = f"config file not found: {path}"
        raise ConfigError(msg) from exc
    except tomllib.TOMLDecodeError as exc:
        msg = f"{path}: {exc}"
        raise ConfigError(msg) from exc


def _merge(base: Table, override: Table) -> Table:
    """Merge two tables. Nested tables merge. For other values, `override` wins."""

    def merged(key: str) -> object:
        old, new = base.get(key), override.get(key)
        if key not in override:
            return old
        if isinstance(old, dict) and isinstance(new, dict):
            return _merge(cast("Table", old), cast("Table", new))
        return new

    return {key: merged(key) for key in base.keys() | override.keys()}


def _table(data: Table, key: str) -> Table:
    return _as_table(data.get(key, {}), key)


def _as_table(value: object, where: str) -> Table:
    if not isinstance(value, dict):
        msg = f"{where} must be a table"
        raise ConfigError(msg)
    return cast("Table", value)


def _str_list(value: object, where: str) -> list[str]:
    if isinstance(value, list) and all(isinstance(v, str) for v in cast("list[object]", value)):
        return cast("list[str]", value)
    msg = f"{where} must be a list of strings"
    raise ConfigError(msg)


def _paths(table: Table) -> Paths:
    defaults = Paths()
    known = {f.name for f in dataclasses.fields(defaults)}

    def converted(key: str, value: object) -> object:
        name = key.replace("-", "_")
        if name not in known:
            msg = f"paths: unknown key {key!r}"
            raise ConfigError(msg)
        if isinstance(attribute(defaults, name), tuple):
            return tuple(_str_list(value, f"paths.{key}"))
        if isinstance(value, str):
            return value
        msg = f"paths.{key} must be a string"
        raise ConfigError(msg)

    changes = {key.replace("-", "_"): converted(key, value) for key, value in table.items()}
    return dataclasses.replace(defaults, **changes)
