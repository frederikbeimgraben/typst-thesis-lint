"""Thin typed wrapper around the tree-sitter Typst grammar."""

from __future__ import annotations

import warnings
from bisect import bisect_right
from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING

import tree_sitter
import tree_sitter_typst

from thesis_lint.model import Location

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

type Node = tree_sitter.Node

# Unsaved editor buffers by resolved path. The LSP server fills this map.
OVERRIDES: dict[Path, str] = {}


def read_text(path: Path) -> str:
    """Return the text of a file. Use the editor buffer if one exists."""
    resolved = path.resolve()
    if resolved in OVERRIDES:
        return OVERRIDES[resolved]
    return path.read_text(encoding="utf-8")


@cache
def _parser() -> tree_sitter.Parser:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        language = tree_sitter.Language(tree_sitter_typst.language())  # pyright: ignore[reportDeprecated] - the grammar package gives an int pointer
    return tree_sitter.Parser(language)


@dataclass(slots=True)
class SourceFile:
    """A parsed `.typ` file with helpers to map byte offsets to positions."""

    path: Path
    text: str
    data: bytes = field(init=False)
    tree: tree_sitter.Tree = field(init=False)
    _line_starts: list[int] = field(init=False)

    def __post_init__(self) -> None:
        """Encode the text, parse it and index the line starts."""
        self.data = self.text.encode("utf-8")
        self.tree = _parser().parse(self.data)
        starts = [0]
        starts.extend(i + 1 for i, byte in enumerate(self.data) if byte == 0x0A)
        self._line_starts = starts

    @classmethod
    def read(cls, path: Path) -> SourceFile:
        """Read and parse a file."""
        return cls(path=path, text=read_text(path))

    @property
    def root(self) -> Node:
        """Return the root node."""
        return self.tree.root_node

    def node_text(self, node: Node) -> str:
        """Return the source text of a node."""
        return self.data[node.start_byte : node.end_byte].decode("utf-8")

    def slice(self, start: int, end: int) -> str:
        """Return the source text between two byte offsets."""
        return self.data[start:end].decode("utf-8")

    def position(self, byte: int) -> tuple[int, int]:
        """Return the 1-based line and character column of a byte offset."""
        index = bisect_right(self._line_starts, byte) - 1
        start = self._line_starts[index]
        column = len(self.data[start:byte].decode("utf-8", errors="replace")) + 1
        return index + 1, column

    def location(self, start: int, end: int | None = None) -> Location:
        """Return the location of a byte range."""
        line, column = self.position(start)
        if end is None:
            return Location(self.path, line, column)
        end_line, end_column = self.position(end)
        return Location(self.path, line, column, end_line, end_column)

    def node_location(self, node: Node) -> Location:
        """Return the location of a node."""
        return self.location(node.start_byte, node.end_byte)


def walk(node: Node) -> Iterator[Node]:
    """Yield `node` and all its descendants in document order."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def named_children(node: Node) -> list[Node]:
    """Return the named children of a node."""
    return [child for child in node.children if child.is_named]


def call_name(node: Node, source: SourceFile) -> str | None:
    """Return the function name of a `call` node, or None.

    For `quote(block: true)[...]` the grammar nests a call in a call. This returns
    the innermost identifier.
    """
    if node.type != "call":
        return None
    first = node.children[0] if node.children else None
    while first is not None and first.type == "call":
        first = first.children[0] if first.children else None
    if first is None:
        return None
    if first.type == "ident":
        return source.node_text(first)
    if first.type == "field":
        return source.node_text(first)
    return None


def call_args(node: Node) -> list[Node]:
    """Return the argument nodes of a call: group members and trailing content blocks."""
    args: list[Node] = []
    for child in node.children:
        if child.type == "call":
            args.extend(call_args(child))
        elif child.type == "group":
            args.extend(named_children(child))
        elif child.type == "content":
            args.append(child)
    return args


def named_arg(node: Node, name: str, source: SourceFile) -> Node | None:
    """Return the value node of the named argument `name` of a call, or None."""
    for arg in call_args(node):
        if arg.type == "tagged":
            parts = named_children(arg)
            if len(parts) >= 2 and source.node_text(parts[0]) == name:
                return parts[-1]
    return None


def positional_args(node: Node) -> list[Node]:
    """Return the positional arguments (including trailing content blocks) of a call."""
    return [arg for arg in call_args(node) if arg.type != "tagged"]
