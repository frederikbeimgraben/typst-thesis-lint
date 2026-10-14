"""Rule registry. The `rule` decorator registers a check function as a rule."""

from __future__ import annotations

import dataclasses
import importlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from thesis_lint.model import Location, Needs, Severity, SourceRef

if TYPE_CHECKING:
    from thesis_lint.context import Context


@dataclass(frozen=True, slots=True)
class NoParams:
    """Parameter type for rules without parameters."""


NO_PARAMS = NoParams()


@dataclass(frozen=True, slots=True)
class Finding:
    """One result of a check.

    If `severity` is set, it replaces the configured severity. If `submission` is set,
    it replaces the submission flag of the rule for this finding only.
    """

    message: str
    location: Location
    severity: Severity | None = None
    submission: bool | None = None


type CheckFn[P] = Callable[[Context, P], Iterable[Finding]]
type ErasedCheck = Callable[[Context, object], Iterable[Finding]]


@dataclass(frozen=True, slots=True)
class Rule:
    """A registered rule.

    The registry erases the parameter type. `params` holds the default parameter
    object of the rule. `check` accepts a parameter object of the same type.
    """

    id: str
    pack: str
    summary: str
    severity: Severity
    sources: tuple[SourceRef, ...]
    needs: Needs
    submission: bool
    params: object
    check: ErasedCheck


# Modules that register the built-in rules on import.
BUILTIN_MODULES = ("thesis_lint.core", "thesis_lint.packs.sat_meti")

_RULES: dict[str, Rule] = {}
_DEFAULT_ENABLED: set[str] = set()


def rule[P](  # noqa: PLR0913 - a rule has many metadata fields
    rule_id: str,
    *,
    summary: str,
    severity: Severity,
    sources: Iterable[SourceRef],
    params: P = NO_PARAMS,
    needs: Needs = Needs.SOURCE,
    submission: bool = False,
    enabled: bool = False,
) -> Callable[[CheckFn[P]], CheckFn[P]]:
    """Register a rule.

    The pack is the first part of the ID. For example, `core.x` is in pack `core`.
    A rule is disabled until a preset or the project config enables it.
    Set `enabled` to enable the rule without config.
    """

    def decorate(fn: CheckFn[P]) -> CheckFn[P]:
        if rule_id in _RULES:
            msg = f"duplicate rule id {rule_id}"
            raise ValueError(msg)

        def erased(ctx: Context, values: object) -> Iterable[Finding]:
            return fn(ctx, cast("P", values))

        _RULES[rule_id] = Rule(
            id=rule_id,
            pack=rule_id.split(".", 1)[0],
            summary=summary,
            severity=severity,
            sources=tuple(sources),
            needs=needs,
            submission=submission,
            params=params,
            check=erased,
        )
        if enabled:
            _DEFAULT_ENABLED.add(rule_id)
        return fn

    return decorate


def all_rules() -> dict[str, Rule]:
    """Return all registered rules by ID. This function imports the built-in packs first."""
    for module in BUILTIN_MODULES:
        importlib.import_module(module)

    return dict(sorted(_RULES.items()))


def default_enabled() -> frozenset[str]:
    """Return the IDs of the rules that are enabled without config."""
    return frozenset(_DEFAULT_ENABLED)


def apply_params(defaults: object, values: dict[str, object], rule_id: str) -> object:
    """Return a copy of `defaults` with `values` applied. Check the names and the types."""
    if not values:
        return defaults
    if not dataclasses.is_dataclass(defaults) or isinstance(defaults, type):
        msg = f"{rule_id}: the rule has no parameters, but the config sets {sorted(values)}"
        raise ConfigError(msg)
    fields = {field.name for field in dataclasses.fields(defaults)}
    changes: dict[str, object] = {}
    for name, value in values.items():
        key = name.replace("-", "_")
        if key not in fields:
            msg = f"{rule_id}: unknown parameter {name!r}. Known parameters: {sorted(fields)}"
            raise ConfigError(msg)
        current = attribute(defaults, key)
        changes[key] = coerce(value, current, f"{rule_id}.{name}")
    return dataclasses.replace(defaults, **changes)


def coerce(value: object, current: object, where: str) -> object:
    """Return `value` converted to the type of `current`. Raise ConfigError if not possible."""
    if isinstance(current, bool):
        if isinstance(value, bool):
            return value
    elif isinstance(current, int):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    elif isinstance(current, float):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    elif isinstance(current, str):
        if isinstance(value, str):
            return value
    elif isinstance(current, tuple) and isinstance(value, list):
        items = cast("list[object]", value)
        if all(isinstance(item, str) for item in items):
            return tuple(cast("list[str]", items))
    expected = type(cast("object", current)).__name__
    msg = f"{where}: expected {expected}, got {type(cast('object', value)).__name__}"
    raise ConfigError(msg)


def attribute(obj: object, name: str) -> object:
    """Return an attribute of a parameter object. The result has type `object`, not `Any`."""
    return cast("object", getattr(obj, name))


class ConfigError(Exception):
    """The config is not valid."""
