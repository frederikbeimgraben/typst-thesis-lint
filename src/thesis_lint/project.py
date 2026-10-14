"""Load a project: document model, bibliography, metadata settings and glossary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from thesis_lint import bib
from thesis_lint.typst.document import Document, Unit, UnitKind, content_unit, load_document
from thesis_lint.typst.parse import OVERRIDES, Node, SourceFile, call_name, named_arg, walk
from thesis_lint.typst.values import (
    Content,
    Value,
    Valued,
    evaluate,
    evaluate_with_nodes,
    find_let,
)

if TYPE_CHECKING:
    from pathlib import Path

    from thesis_lint.config import Config


@dataclass(frozen=True, slots=True)
class Term:
    """A glossary term."""

    key: str
    name: str
    plural: str | None
    genitive: str | None


@dataclass(frozen=True, slots=True)
class Acronym:
    """An acronym. `short` is the abbreviation, `long` the full form."""

    key: str
    short: str
    long: str


@dataclass(frozen=True, slots=True)
class BibliographyCall:
    """A `bibliography(...)` call in the sources."""

    source: SourceFile
    node: Node
    style: str | None
    full: bool


@dataclass(slots=True)
class Project:
    """All inputs of the source rules."""

    config: Config
    document: Document
    bibliography: bib.Bibliography
    settings: dict[str, Valued] = field(default_factory=dict[str, Valued])
    settings_source: SourceFile | None = None
    terms: dict[str, Term] = field(default_factory=dict[str, Term])
    acronyms: dict[str, Acronym] = field(default_factory=dict[str, Acronym])
    glossary_source: SourceFile | None = None
    abstract: Unit | None = None
    bibliography_calls: list[BibliographyCall] = field(default_factory=list[BibliographyCall])

    @property
    def root(self) -> Path:
        """Return the project root."""
        return self.config.root

    def setting_str(self, name: str) -> str | None:
        """Return a string setting, or None."""
        valued = self.settings.get(name)
        if valued is None:
            return None
        return valued.value if isinstance(valued.value, str) else None

    def setting_text(self, name: str) -> str | None:
        """Return a string or content setting as plain text, or None."""
        valued = self.settings.get(name)
        if valued is None or self.settings_source is None:
            return None
        value = valued.value
        if isinstance(value, str):
            return value
        if isinstance(value, Content):
            return content_unit(value.source, value.node).text
        return None

    def is_citation(self, key: str) -> bool:
        """Return True if `key` is an entry of the bibliography."""
        return key in self.bibliography.entries


def load_project(config: Config, overrides: dict[Path, str] | None = None) -> Project:
    """Load the project. `overrides` replaces file contents, for unsaved editor buffers."""
    root = config.root
    paths = config.paths
    OVERRIDES.clear()
    if overrides:
        OVERRIDES.update({path.resolve(): text for path, text in overrides.items()})
    try:
        document = load_document(root / paths.main, root)
        bibliography = bib.load([root / name for name in paths.bib])
        project = Project(config=config, document=document, bibliography=bibliography)
        _load_settings(project, root / paths.metadata, paths.metadata_variable)
        _load_glossary(project, root / paths.glossary)
        project.bibliography_calls = _bibliography_calls(document)
    finally:
        OVERRIDES.clear()
    return project


def _load_settings(project: Project, path: Path, variable: str) -> None:
    if not path.is_file():
        return
    source = SourceFile.read(path)
    node = find_let(source, variable)
    if node is None:
        return
    project.settings = evaluate_with_nodes(node, source)
    project.settings_source = source
    abstract = project.settings.get("abstract")
    if abstract is not None and isinstance(abstract.value, Content):
        unit = content_unit(source, abstract.value.node, UnitKind.CONTENT)
        project.abstract = unit


def _load_glossary(project: Project, path: Path) -> None:
    if not path.is_file():
        return
    source = SourceFile.read(path)
    project.glossary_source = source
    project.terms = {
        key: _term(key, entry)
        for key, entry in _let_dict(source, "terms").items()
        if isinstance(entry, dict)
    }
    project.acronyms = {
        key: acronym
        for key, entry in _let_dict(source, "acronyms").items()
        if (acronym := _acronym(key, entry)) is not None
    }


def _let_dict(source: SourceFile, name: str) -> dict[str, Value]:
    node = find_let(source, name)
    value = None if node is None else evaluate(node, source)
    return value if isinstance(value, dict) else {}


def _text_or(value: Value, default: str | None) -> str | None:
    return value if isinstance(value, str) else default


def _term(key: str, entry: dict[str, Value]) -> Term:
    return Term(
        key=key,
        name=_text_or(entry.get("name"), None) or key,
        plural=_text_or(entry.get("plural"), None),
        genitive=_text_or(entry.get("genitive"), None),
    )


def _acronym(key: str, entry: Value) -> Acronym | None:
    if isinstance(entry, str):
        return Acronym(key, key, entry)
    if isinstance(entry, dict):
        return Acronym(
            key,
            _text_or(entry.get("short"), None) or key,
            _text_or(entry.get("long"), None) or "",
        )
    return None


def _bibliography_calls(document: Document) -> list[BibliographyCall]:
    return [
        _bibliography_call(source, node)
        for source in document.files
        for node in walk(source.root)
        if node.type == "call" and call_name(node, source) == "bibliography"
    ]


def _bibliography_call(source: SourceFile, node: Node) -> BibliographyCall:
    style_node = named_arg(node, "style", source)
    style_value = None if style_node is None else evaluate(style_node, source)
    style = (
        None
        if style_node is None
        else style_value
        if isinstance(style_value, str)
        else source.node_text(style_node)
    )
    full_node = named_arg(node, "full", source)
    return BibliographyCall(
        source, node, style, full_node is not None and source.node_text(full_node) == "true"
    )
