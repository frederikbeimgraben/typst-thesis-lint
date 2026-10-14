"""Evaluate literal Typst values (dicts, arrays, strings, content) without compiling."""

from __future__ import annotations

from dataclasses import dataclass

from thesis_lint.typst.parse import Node, SourceFile, named_children, walk


@dataclass(frozen=True, slots=True)
class Content:
    """A content block `[...]`. `node` is the `content` node."""

    node: Node
    source: SourceFile


@dataclass(frozen=True, slots=True)
class Unknown:
    """A value that is not a literal, e.g. a variable or a function call."""

    node: Node
    source: SourceFile


type Value = (
    str | int | float | bool | Content | Unknown | list["Value"] | dict[str, "Value"] | None
)


@dataclass(frozen=True, slots=True)
class Valued:
    """A value together with the node it came from (for locations)."""

    value: Value
    node: Node


def evaluate(node: Node, source: SourceFile) -> Value:
    """Evaluate a literal expression node."""
    kind = node.type
    if kind == "string":
        return _string(source.node_text(node))
    if kind == "number":
        text = source.node_text(node)
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return Unknown(node, source)
    if kind == "bool":
        return source.node_text(node) == "true"
    if kind == "none":
        return None
    if kind == "content":
        return Content(node, source)
    if kind == "group":
        return _group(node, source)
    return Unknown(node, source)


def evaluate_with_nodes(node: Node, source: SourceFile) -> dict[str, Valued]:
    """Evaluate a dict literal and keep the value node of every key."""
    result: dict[str, Valued] = {}
    if node.type != "group":
        return result
    for member in named_children(node):
        if member.type != "tagged":
            continue
        parts = named_children(member)
        if len(parts) < 2:
            continue
        key = _key(parts[0], source)
        result[key] = Valued(evaluate(parts[-1], source), parts[-1])
    return result


def find_let(source: SourceFile, name: str) -> Node | None:
    """Return the value node of the top-level `#let name = ...`, or None."""
    for node in walk(source.root):
        if node.type != "let":
            continue
        parts = named_children(node)
        if len(parts) >= 2 and parts[0].type == "ident" and source.node_text(parts[0]) == name:
            return parts[-1]
    return None


def _group(node: Node, source: SourceFile) -> Value:
    members = named_children(node)
    if not members:
        # `()` is an empty array, `(:)` an empty dict.
        return {} if ":" in source.node_text(node) else []
    if all(member.type == "tagged" for member in members):
        result: dict[str, Value] = {}
        for member in members:
            parts = named_children(member)
            if len(parts) >= 2:
                result[_key(parts[0], source)] = evaluate(parts[-1], source)
        return result
    if len(members) == 1 and not source.node_text(node).rstrip(")").rstrip().endswith(","):
        # `(x)` is a parenthesized expression, `(x,)` an array.
        return evaluate(members[0], source)
    return [evaluate(member, source) for member in members]


def _key(node: Node, source: SourceFile) -> str:
    text = source.node_text(node)
    return _string(text) if node.type == "string" else text


def _string(literal: str) -> str:
    body = literal[1:-1] if len(literal) >= 2 and literal[0] == '"' else literal
    escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            out.append(escapes.get(body[index + 1], body[index + 1]))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)
