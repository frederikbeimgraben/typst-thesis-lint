"""Helpers for the source rules of the SAT pack."""

from __future__ import annotations

from typing import TYPE_CHECKING

from thesis_lint.model import Location
from thesis_lint.typst.parse import walk
from thesis_lint.typst.values import find_let

if TYPE_CHECKING:
    from collections.abc import Iterator

    from thesis_lint.context import Context
    from thesis_lint.typst.document import Heading
    from thesis_lint.typst.parse import Node

# The chapter with the declaration. The style rules do not check it.
DECLARATION_TITLE = "Eidesstattliche Erklärung"


def main_location(ctx: Context) -> Location:
    """Return the location of the main file."""
    return Location(ctx.root / ctx.config.paths.main)


def settings_location(ctx: Context) -> Location:
    """Return the location of the settings dictionary, or of the main file."""
    source = ctx.project.settings_source
    if source is None:
        return main_location(ctx)
    node = find_let(source, ctx.config.paths.metadata_variable)
    return source.node_location(node) if node is not None else Location(source.path)


def setting_location(ctx: Context, name: str) -> Location:
    """Return the location of one setting, or of the settings dictionary."""
    valued = ctx.project.settings.get(name)
    source = ctx.project.settings_source
    if valued is None or source is None:
        return settings_location(ctx)
    return source.node_location(valued.node)


def listed_keys(ctx: Context) -> set[str]:
    """Return the keys of the entries that the bibliography prints.

    With `full: true`, the bibliography prints all entries. Otherwise it
    prints the cited entries.
    """
    entries = ctx.project.bibliography.entries
    if any(call.full for call in ctx.project.bibliography_calls):
        return set(entries)
    return {ref.key for _, ref in ctx.project.document.references() if ref.key in entries}


def child_heading(parent: Heading, title: str) -> Heading | None:
    """Return the first descendant heading with this title, or None."""
    return next((h for h in descendants(parent) if h.text == title), None)


def descendants(heading: Heading) -> Iterator[Heading]:
    """Yield all headings below a heading, in document order."""
    for child in heading.children:
        yield child
        yield from descendants(child)


def section_nodes(ctx: Context, heading: Heading) -> Iterator[Node]:
    """Yield the syntax nodes of a section in the file of its heading.

    The section ends at the next heading of the same or a higher level in the
    same file. Included files are not part of the result.
    """
    headings = ctx.project.document.headings
    index = next(i for i, h in enumerate(headings) if h is heading)
    end = next(
        (
            h.node.start_byte
            for h in headings[index + 1 :]
            if h.source is heading.source and h.level <= heading.level
        ),
        len(heading.source.data),
    )
    start = heading.node.end_byte
    return (
        node
        for node in walk(heading.source.root)
        if node.start_byte >= start and node.end_byte <= end
    )
