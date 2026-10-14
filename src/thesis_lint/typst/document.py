"""Document model: headings, prose units, figures, references and glossary uses.

The model walks `main.typ` and every file that it includes, in document order.
It converts the markup to plain prose units. A unit keeps a map from each
character back to its byte offset in the source, so that rules can report
exact locations.

Inline elements that are not prose get one placeholder character from the
Unicode private use area. Rules can find them through the span lists of the unit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from thesis_lint.typst.parse import (
    Node,
    SourceFile,
    call_name,
    named_arg,
    named_children,
    positional_args,
)
from thesis_lint.typst.values import evaluate

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from thesis_lint.model import Location

# Placeholder characters for inline elements that are not prose.
REF_MARK = ""
RAW_MARK = ""
MATH_MARK = ""
FOOTNOTE_MARK = ""
OBJECT_MARK = ""
PLACEHOLDERS = frozenset({REF_MARK, RAW_MARK, MATH_MARK, FOOTNOTE_MARK, OBJECT_MARK})

GLOSSARY_FUNCTIONS = frozenset(
    {"gls", "Gls", "glspl", "Glspl", "glsgen", "glsdat", "acr", "acrshort", "acrlong", "acrfull"}
)
_SHORTHANDS = {
    "~": " ",
    "--": "–",
    "---": "—",
    "...": "…",
    "-?": "­",
}
_INLINE_STYLE_CALLS = frozenset(
    {"emph", "strong", "underline", "text", "smallcaps", "highlight", "overline", "strike", "box"}
)
_BLOCK_CALLS = frozenset(
    {
        "pagebreak",
        "colbreak",
        "outline",
        "bibliography",
        "v",
        "place",
        "grid",
        "columns",
        "block",
        "image",
        "line",
        "rect",
        "metadata",
    }
)
_WS = re.compile(r"\s+")


class UnitKind(StrEnum):
    """Kind of a prose unit."""

    PARAGRAPH = "paragraph"
    ITEM = "item"
    ENUM_ITEM = "enum-item"
    TERM = "term"
    HEADING = "heading"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    QUOTE_BLOCK = "quote-block"
    CELL = "cell"
    CONTENT = "content"


@dataclass(frozen=True, slots=True)
class Span:
    """A range of characters in the text of a unit."""

    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Reference:
    """A reference `@key` or `#cite(<key>)`. It is a citation if `key` is a bib entry."""

    key: str
    supplement: str | None
    span: Span
    location: Location
    order: int


@dataclass(frozen=True, slots=True)
class GlossaryUse:
    """A call like `#gls("key")`."""

    function: str
    key: str
    span: Span
    location: Location


@dataclass(frozen=True, slots=True)
class Styled:
    """An inline style span, for example `*strong*` or `#underline[...]`."""

    style: str
    span: Span


@dataclass(slots=True)
class Unit:
    """A prose unit: a paragraph, a list item, a caption, a footnote, a cell or a heading title."""

    kind: UnitKind
    source: SourceFile
    order: int
    text: str = ""
    offsets: list[int] = field(default_factory=list[int])
    depth: int = 0
    heading: Heading | None = None
    references: list[Reference] = field(default_factory=list[Reference])
    glossary: list[GlossaryUse] = field(default_factory=list[GlossaryUse])
    styles: list[Styled] = field(default_factory=list[Styled])
    quotes: list[Span] = field(default_factory=list[Span])
    maths: list[Span] = field(default_factory=list[Span])
    raws: list[Span] = field(default_factory=list[Span])
    footnotes: list[tuple[Span, Unit]] = field(default_factory=list[tuple[Span, "Unit"]])
    end_byte: int = 0

    def byte_at(self, index: int) -> int:
        """Return the source byte offset of the character at `index`."""
        if not self.offsets:
            return self.end_byte
        if index >= len(self.offsets):
            return self.end_byte
        return self.offsets[max(index, 0)]

    def location(self, start: int, end: int | None = None) -> Location:
        """Return the source location of the character range `start` to `end`."""
        begin = self.byte_at(start)
        if end is None:
            return self.source.location(begin)
        stop = self.byte_at(end - 1) + 1 if end > start else begin
        return self.source.location(begin, max(stop, begin))

    @property
    def start_location(self) -> Location:
        """Return the location of the first character."""
        return self.location(0)

    def is_quoted(self, index: int) -> bool:
        """Return True if the character at `index` is inside a quotation."""
        return any(span.start <= index < span.end for span in self.quotes)

    def in_span(self, index: int, spans: list[Span]) -> bool:
        """Return True if `index` is inside one of `spans`."""
        return any(span.start <= index < span.end for span in spans)


@dataclass(slots=True)
class Heading:
    """A heading from markup (`== Title`) or from a `#heading(...)` call."""

    level: int
    title: Unit
    source: SourceFile
    node: Node
    order: int
    label: str | None = None
    numbered: bool = True
    outlined: bool = True
    parent: Heading | None = None
    children: list[Heading] = field(default_factory=list["Heading"])
    units: list[Unit] = field(default_factory=list[Unit])

    @property
    def text(self) -> str:
        """Return the plain title text."""
        return self.title.text.strip()

    @property
    def location(self) -> Location:
        """Return the location of the heading."""
        return self.source.node_location(self.node)

    def all_units(self) -> Iterator[Unit]:
        """Yield the units of this heading and of all its descendants, in order."""
        yield from self.units
        for child in self.children:
            yield from child.all_units()

    def ancestors(self) -> Iterator[Heading]:
        """Yield the parent headings, nearest first."""
        current = self.parent
        while current is not None:
            yield current
            current = current.parent


@dataclass(slots=True)
class Figure:
    """A `#figure(...)` call."""

    kind: str
    source: SourceFile
    node: Node
    order: int
    heading: Heading | None
    caption: Unit | None = None
    label: str | None = None
    body: Node | None = None


@dataclass(slots=True)
class Equation:
    """A block equation `$ ... $`."""

    source: SourceFile
    node: Node
    order: int
    heading: Heading | None
    label: str | None = None


@dataclass(slots=True)
class Call:
    """A function call in markup that is not prose, for example `#bibliography(...)`."""

    name: str
    source: SourceFile
    node: Node
    order: int


@dataclass(slots=True)
class Document:
    """The model of the whole document."""

    root: Path
    files: list[SourceFile] = field(default_factory=list[SourceFile])
    headings: list[Heading] = field(default_factory=list[Heading])
    units: list[Unit] = field(default_factory=list[Unit])
    figures: list[Figure] = field(default_factory=list[Figure])
    equations: list[Equation] = field(default_factory=list[Equation])
    calls: list[Call] = field(default_factory=list[Call])
    labels: dict[str, int] = field(default_factory=dict[str, int])
    errors: list[str] = field(default_factory=list[str])

    @property
    def top_headings(self) -> list[Heading]:
        """Return the headings without a parent."""
        return [heading for heading in self.headings if heading.parent is None]

    def references(self) -> Iterator[tuple[Unit, Reference]]:
        """Yield every reference with its unit."""
        for unit in self.units:
            for reference in unit.references:
                yield unit, reference

    def prose_units(self) -> Iterator[Unit]:
        """Yield the units that are running text: not headings, captions or cells."""
        excluded = {UnitKind.HEADING, UnitKind.CAPTION, UnitKind.CELL, UnitKind.CONTENT}
        for unit in self.units:
            if unit.kind not in excluded:
                yield unit


def load_document(main: Path, root: Path) -> Document:
    """Parse `main` and every included file, and return the model."""
    document = Document(root=root)
    walker = _Walker(document)
    walker.file(main, depth=0)
    _link_headings(document)
    return document


def content_unit(source: SourceFile, node: Node, kind: UnitKind = UnitKind.CONTENT) -> Unit:
    """Return one unit for a content block, for example the abstract in `metadata.typ`."""
    document = Document(root=source.path.parent)
    walker = _Walker(document)
    builder = _Builder(kind, source, order=0)
    walker.inline_children(node, source, builder)
    return builder.finish()


class _Builder:
    """Collect inline text for one unit."""

    def __init__(self, kind: UnitKind, source: SourceFile, order: int, depth: int = 0) -> None:
        self.unit: Unit = Unit(kind=kind, source=source, order=order, depth=depth)
        self._parts: list[str] = []
        self._offsets: list[int] = []
        self._last_end: int | None = None
        self._open_quotes: list[int] = []

    @property
    def length(self) -> int:
        return len(self._offsets)

    def gap(self, start_byte: int) -> None:
        """Add one space if the source has white space before `start_byte`."""
        source = self.unit.source
        if self._last_end is not None and start_byte > self._last_end:
            between = source.slice(self._last_end, start_byte)
            if between.strip() == "" and between and self._parts and not self._ends_with_space():
                self.add_synthetic(" ", self._last_end)

    def _ends_with_space(self) -> bool:
        return bool(self._parts) and self._parts[-1][-1:] in {" ", " "}

    def add_source_text(self, text: str, start_byte: int, end_byte: int) -> None:
        """Add literal source text. Collapse white space. Map each character to its byte."""
        self.gap(start_byte)
        byte = start_byte
        for char in text:
            width = len(char.encode("utf-8"))
            if char.isspace() and char != " ":
                if not self._ends_with_space() and self._parts:
                    self._append(" ", byte)
            else:
                self._append(char, byte)
            byte += width
        self._last_end = end_byte

    def add_synthetic(self, text: str, byte: int, end_byte: int | None = None) -> None:
        """Add text that is not in the source as written. Map it to `byte`."""
        for char in text:
            self._append(char, byte)
        if end_byte is not None:
            self._last_end = end_byte

    def _append(self, char: str, byte: int) -> None:
        self._parts.append(char)
        self._offsets.append(byte)

    def open_or_close_quote(self, double: bool, start: int, end: int) -> None:  # noqa: FBT001
        """Add a German smart quote and track the quotation span."""
        self.gap(start)
        if self._open_quotes:
            self.add_synthetic("“" if double else "‘", start, end)
            begin = self._open_quotes.pop()
            self.unit.quotes.append(Span(begin, self.length))
        else:
            self._open_quotes.append(self.length)
            self.add_synthetic("„" if double else "‚", start, end)

    def finish(self) -> Unit:
        """Return the unit. Strip white space at both ends."""
        text = "".join(self._parts)
        lead = len(text) - len(text.lstrip())
        trail = len(text.rstrip())
        unit = self.unit
        unit.text = text[lead:trail]
        unit.offsets = self._offsets[lead:trail]
        shift = lead
        if shift:
            unit.references = [
                Reference(r.key, r.supplement, _shift(r.span, shift), r.location, r.order)
                for r in unit.references
            ]
            unit.glossary = [
                GlossaryUse(g.function, g.key, _shift(g.span, shift), g.location)
                for g in unit.glossary
            ]
            unit.styles = [Styled(s.style, _shift(s.span, shift)) for s in unit.styles]
            unit.quotes = [_shift(s, shift) for s in unit.quotes]
            unit.maths = [_shift(s, shift) for s in unit.maths]
            unit.raws = [_shift(s, shift) for s in unit.raws]
            unit.footnotes = [(_shift(s, shift), f) for s, f in unit.footnotes]
        unit.quotes.extend(_literal_quotes(unit.text))
        unit.end_byte = self._last_end if self._last_end is not None else 0
        return unit

    def has_text(self) -> bool:
        return any(not part.isspace() for part in self._parts)


def _shift(span: Span, amount: int) -> Span:
    return Span(max(span.start - amount, 0), max(span.end - amount, 0))


_LITERAL_QUOTE = re.compile("„[^“”„]*[“”]|»[^«]*«")


def _literal_quotes(text: str) -> list[Span]:
    """Return quotation spans that the author typed with literal German quote characters."""
    return [Span(m.start(), m.end()) for m in _LITERAL_QUOTE.finditer(text)]


class _Walker:
    """Walk the syntax trees and fill the document model."""

    def __init__(self, document: Document) -> None:
        self.document: Document = document
        self.order: int = 0
        self.current_heading: Heading | None = None
        self._seen: set[Path] = set()
        self._depth: int = 0

    def next_order(self) -> int:
        self.order += 1
        return self.order

    def file(self, path: Path, depth: int) -> None:
        resolved = path.resolve()
        if resolved in self._seen or depth > 20:
            return
        self._seen.add(resolved)
        try:
            source = SourceFile.read(resolved)
        except OSError as exc:
            self.document.errors.append(f"cannot read {path}: {exc}")
            return
        self.document.files.append(source)
        self._depth = depth
        self.blocks(source.root, source)

    # Block level

    def blocks(self, node: Node, source: SourceFile) -> None:
        builder: _Builder | None = None
        for child in node.children:
            kind = child.type
            if kind in {"section", "content"} and node.type != "call":
                builder = self._flush(builder)
                self.blocks(child, source)
            elif kind == "heading":
                builder = self._flush(builder)
                self._markup_heading(child, source)
            elif kind == "parbreak":
                builder = self._flush(builder)
            elif kind in {"item", "term"}:
                builder = self._flush(builder)
                self._item(child, source, depth=0)
            elif kind == "label":
                builder = self._label(child, source, builder)
            elif kind == "comment":
                continue
            elif kind == "math" and _is_block_math(source.node_text(child)):
                builder = self._flush(builder)
                self.document.equations.append(
                    Equation(source, child, self.next_order(), self.current_heading)
                )
            elif kind == "code":
                builder = self._code_block(child, source, builder)
            else:
                if builder is None:
                    builder = _Builder(UnitKind.PARAGRAPH, source, self.next_order())
                self.inline(child, source, builder)
        self._flush(builder)

    def _flush(self, builder: _Builder | None) -> None:
        if builder is None or not builder.has_text():
            return
        unit = builder.finish()
        unit.heading = self.current_heading
        self._add_unit(unit)

    def _add_unit(self, unit: Unit) -> None:
        self.document.units.append(unit)
        if unit.heading is not None and unit.kind != UnitKind.HEADING:
            unit.heading.units.append(unit)

    def _label(self, node: Node, source: SourceFile, builder: _Builder | None) -> _Builder | None:
        name = source.node_text(node).strip("<>")
        self.document.labels.setdefault(name, self.order)
        last_block = self._last_block()
        if last_block is not None:
            target_order, setter = last_block
            if target_order == self.order:
                setter(name)
        return builder

    def _last_block(self) -> tuple[int, _LabelSetter] | None:
        candidates: list[tuple[int, _LabelSetter]] = []
        if self.document.figures:
            figure = self.document.figures[-1]
            candidates.append((figure.order, _setter(figure)))
        if self.document.equations:
            equation = self.document.equations[-1]
            candidates.append((equation.order, _setter(equation)))
        if self.document.headings:
            heading = self.document.headings[-1]
            candidates.append((heading.order, _setter(heading)))
        if not candidates:
            return None
        return max(candidates, key=lambda candidate: candidate[0])

    def _markup_heading(self, node: Node, source: SourceFile) -> None:
        marker = node.children[0] if node.children else None
        level = len(source.node_text(marker)) if marker is not None else 1
        builder = _Builder(UnitKind.HEADING, source, self.next_order())
        label: str | None = None
        for child in node.children:
            if not child.is_named:
                continue
            if child.type == "label":
                label = source.node_text(child).strip("<>")
                continue
            self.inline(child, source, builder)
        self._add_heading(level, builder, source, node, label=label)

    def _add_heading(  # noqa: PLR0913 - a heading has many attributes
        self,
        level: int,
        builder: _Builder,
        source: SourceFile,
        node: Node,
        *,
        label: str | None = None,
        numbered: bool = True,
        outlined: bool = True,
    ) -> None:
        title = builder.finish()
        heading = Heading(
            level=level,
            title=title,
            source=source,
            node=node,
            order=title.order,
            label=label,
            numbered=numbered,
            outlined=outlined,
        )
        title.heading = heading
        self.document.headings.append(heading)
        self.document.units.append(title)
        if label is not None:
            self.document.labels.setdefault(label, heading.order)
        self.current_heading = heading

    def _item(self, node: Node, source: SourceFile, depth: int) -> None:
        marker = source.node_text(node.children[0]) if node.children else "-"
        kind = {"+": UnitKind.ENUM_ITEM, "/": UnitKind.TERM}.get(marker, UnitKind.ITEM)
        builder = _Builder(kind, source, self.next_order(), depth=depth)
        nested: list[Node] = []
        for child in node.children:
            if not child.is_named:
                continue
            if child.type in {"item", "term"}:
                nested.append(child)
            elif child.type == "code":
                self._inline_code(child, source, builder)
            else:
                self.inline(child, source, builder)
        if builder.has_text():
            unit = builder.finish()
            unit.heading = self.current_heading
            self._add_unit(unit)
        for child in nested:
            self._item(child, source, depth + 1)

    def _code_block(
        self, node: Node, source: SourceFile, builder: _Builder | None
    ) -> _Builder | None:
        expression = next((c for c in node.children if c.is_named), None)
        if expression is None:
            return builder
        kind = expression.type
        if kind == "include":
            builder = self._flush(builder)
            target = next((c for c in named_children(expression) if c.type == "string"), None)
            if target is not None:
                relative = evaluate(target, source)
                if isinstance(relative, str):
                    self.file(source.path.parent / relative, self._depth + 1)
            return None
        if kind in {"let", "set", "show", "import"}:
            return builder
        if kind == "call":
            name = call_name(expression, source) or ""
            if name == "heading":
                builder = self._flush(builder)
                self._call_heading(expression, source)
                return None
            if name == "figure":
                builder = self._flush(builder)
                self._figure(expression, source)
                return None
            if name == "quote" and _bool_arg(expression, "block", source):
                builder = self._flush(builder)
                self._quote_block(expression, source)
                return None
            if name in _BLOCK_CALLS or name == "table":
                builder = self._flush(builder)
                self.document.calls.append(Call(name, source, expression, self.next_order()))
                return None
        if builder is None:
            builder = _Builder(UnitKind.PARAGRAPH, source, self.next_order())
        self._inline_code(node, source, builder)
        return builder

    def _call_heading(self, node: Node, source: SourceFile) -> None:
        level_value = named_arg(node, "level", source)
        level = 1
        if level_value is not None:
            value = evaluate(level_value, source)
            if isinstance(value, int):
                level = value
        builder = _Builder(UnitKind.HEADING, source, self.next_order())
        for arg in positional_args(node):
            if arg.type == "content":
                self.inline_children(arg, source, builder)
        self._add_heading(
            level,
            builder,
            source,
            node,
            numbered=not _is_none_arg(node, "numbering", source),
            outlined=_bool_arg(node, "outlined", source, default=True),
        )

    def _figure(self, node: Node, source: SourceFile) -> None:
        body = next(iter(positional_args(node)), None)
        kind = "content"
        if body is not None and body.type == "call":
            kind = call_name(body, source) or "content"
        explicit = named_arg(node, "kind", source)
        if explicit is not None:
            value = evaluate(explicit, source)
            kind = value if isinstance(value, str) else source.node_text(explicit)
        figure = Figure(kind, source, node, self.next_order(), self.current_heading, body=body)
        caption = named_arg(node, "caption", source)
        if caption is not None and caption.type == "content":
            builder = _Builder(UnitKind.CAPTION, source, figure.order)
            self.inline_children(caption, source, builder)
            unit = builder.finish()
            unit.heading = self.current_heading
            figure.caption = unit
            self.document.units.append(unit)
        self.document.figures.append(figure)
        if body is not None and body.type == "call" and call_name(body, source) == "table":
            self._table_cells(body, source)

    def _table_cells(self, node: Node, source: SourceFile) -> None:
        for arg in positional_args(node):
            target = arg
            if arg.type == "call":
                for inner in positional_args(arg):
                    if inner.type == "content":
                        self._cell(inner, source)
                continue
            if target.type == "content":
                self._cell(target, source)

    def _cell(self, node: Node, source: SourceFile) -> None:
        builder = _Builder(UnitKind.CELL, source, self.next_order())
        self.inline_children(node, source, builder)
        if builder.has_text():
            unit = builder.finish()
            unit.heading = self.current_heading
            self.document.units.append(unit)

    def _quote_block(self, node: Node, source: SourceFile) -> None:
        builder = _Builder(UnitKind.QUOTE_BLOCK, source, self.next_order())
        for arg in positional_args(node):
            if arg.type == "content":
                self.inline_children(arg, source, builder)
        unit = builder.finish()
        unit.quotes.append(Span(0, len(unit.text)))
        unit.heading = self.current_heading
        self._add_unit(unit)

    # Inline level

    def inline_children(self, node: Node, source: SourceFile, builder: _Builder) -> None:
        for child in node.children:
            if child.is_named:
                if child.type == "code":
                    self._inline_code(child, source, builder)
                elif child.type == "parbreak":
                    builder.add_synthetic(" ", child.start_byte, child.end_byte)
                elif child.type in {"item", "term"}:
                    self.inline_children(child, source, builder)
                else:
                    self.inline(child, source, builder)

    def inline(self, node: Node, source: SourceFile, builder: _Builder) -> None:  # noqa: C901, PLR0912 - one branch per node type
        kind = node.type
        if kind == "text":
            self._text(node, source, builder)
        elif kind == "quote":
            builder.open_or_close_quote(
                source.node_text(node) == '"', node.start_byte, node.end_byte
            )
        elif kind == "shorthand":
            text = source.node_text(node)
            builder.gap(node.start_byte)
            builder.add_synthetic(_SHORTHANDS.get(text, text), node.start_byte, node.end_byte)
        elif kind == "ref":
            self._ref(node, source, builder)
        elif kind in {"strong", "emph"}:
            start = builder.length
            for child in node.children:
                if child.is_named:
                    self.inline(child, source, builder)
            builder.unit.styles.append(Styled(kind, Span(start, builder.length)))
        elif kind in {"raw_span", "raw_blck"}:
            self._mark(builder, node, RAW_MARK, builder.unit.raws)
        elif kind == "math":
            self._mark(builder, node, MATH_MARK, builder.unit.maths)
        elif kind == "code":
            self._inline_code(node, source, builder)
        elif kind in {"linebreak", "space"}:
            builder.add_synthetic(" ", node.start_byte, node.end_byte)
        elif kind in {"label", "comment"}:
            return
        elif kind == "escape":
            builder.gap(node.start_byte)
            builder.add_synthetic(source.node_text(node)[1:], node.start_byte, node.end_byte)
        elif kind == "url":
            self._mark(builder, node, OBJECT_MARK, [])
        elif kind in {"content", "section"}:
            self.inline_children(node, source, builder)
        elif node.children:
            for child in node.children:
                if child.is_named:
                    self.inline(child, source, builder)
        else:
            builder.add_source_text(source.node_text(node), node.start_byte, node.end_byte)

    def _text(self, node: Node, source: SourceFile, builder: _Builder) -> None:
        cursor = node.start_byte
        for child in node.children:
            if child.type == "escape":
                if child.start_byte > cursor:
                    builder.add_source_text(
                        source.slice(cursor, child.start_byte), cursor, child.start_byte
                    )
                builder.gap(child.start_byte)
                builder.add_synthetic(source.node_text(child)[1:], child.start_byte, child.end_byte)
                cursor = child.end_byte
        if node.end_byte > cursor:
            builder.add_source_text(source.slice(cursor, node.end_byte), cursor, node.end_byte)

    def _mark(self, builder: _Builder, node: Node, mark: str, spans: list[Span]) -> None:
        builder.gap(node.start_byte)
        start = builder.length
        builder.add_synthetic(mark, node.start_byte, node.end_byte)
        spans.append(Span(start, builder.length))

    def _ref(self, node: Node, source: SourceFile, builder: _Builder) -> None:
        text = source.node_text(node)
        match = re.match(r"@([^\[\s]+)", text)
        key = match.group(1) if match else text.lstrip("@")
        key = key.rstrip(".:,;")
        supplement_node = next((c for c in node.children if c.type == "content"), None)
        supplement = None
        if supplement_node is not None:
            supplement = content_unit(source, supplement_node).text
        builder.gap(node.start_byte)
        start = builder.length
        builder.add_synthetic(REF_MARK, node.start_byte, node.start_byte + 1 + len(key.encode()))
        builder.unit.references.append(
            Reference(
                key,
                supplement,
                Span(start, builder.length),
                source.node_location(node),
                self.next_order(),
            )
        )

    def _inline_code(self, node: Node, source: SourceFile, builder: _Builder) -> None:  # noqa: C901, PLR0912 - one branch per call kind
        expression = (
            node if node.type == "call" else next((c for c in node.children if c.is_named), None)
        )
        if expression is None or expression.type != "call":
            if expression is not None and expression.type not in {"let", "set", "show", "import"}:
                self._mark(builder, node, OBJECT_MARK, [])
            return
        name = call_name(expression, source) or ""
        args = positional_args(expression)
        if name == "footnote":
            footnote = _Builder(UnitKind.FOOTNOTE, source, self.next_order())
            for arg in args:
                if arg.type == "content":
                    self.inline_children(arg, source, footnote)
            unit = footnote.finish()
            unit.heading = self.current_heading
            start = builder.length
            self._mark(builder, node, FOOTNOTE_MARK, [])
            builder.unit.footnotes.append((Span(start, builder.length), unit))
            self._add_unit(unit)
        elif name in GLOSSARY_FUNCTIONS:
            key_node = next((a for a in args if a.type == "string"), None)
            key = evaluate(key_node, source) if key_node is not None else None
            if isinstance(key, str):
                builder.gap(node.start_byte)
                start = builder.length
                builder.add_synthetic(key, node.start_byte, node.end_byte)
                builder.unit.glossary.append(
                    GlossaryUse(name, key, Span(start, builder.length), source.node_location(node))
                )
        elif name == "cite":
            self._cite_call(expression, node, source, builder)
        elif name == "quote":
            builder.open_or_close_quote(True, node.start_byte, node.start_byte)  # noqa: FBT003
            for arg in args:
                if arg.type == "content":
                    self.inline_children(arg, source, builder)
            builder.open_or_close_quote(True, node.end_byte, node.end_byte)  # noqa: FBT003
        elif name in _INLINE_STYLE_CALLS or name == "link":
            start = builder.length
            has_content = False
            for arg in args:
                if arg.type == "content":
                    has_content = True
                    self.inline_children(arg, source, builder)
            if not has_content:
                self._mark(builder, node, OBJECT_MARK, [])
            builder.unit.styles.append(Styled(name, Span(start, builder.length)))
        elif name in {"h", "linebreak"}:
            builder.add_synthetic(" ", node.start_byte, node.end_byte)
        else:
            contents = [arg for arg in args if arg.type == "content"]
            if contents:
                for arg in contents:
                    self.inline_children(arg, source, builder)
            else:
                self._mark(builder, node, OBJECT_MARK, [])

    def _cite_call(self, call: Node, node: Node, source: SourceFile, builder: _Builder) -> None:
        label = next((a for a in positional_args(call) if a.type == "label"), None)
        if label is None:
            self._mark(builder, node, OBJECT_MARK, [])
            return
        key = source.node_text(label).strip("<>")
        supplement_node = named_arg(call, "supplement", source)
        supplement = None
        if supplement_node is not None and supplement_node.type == "content":
            supplement = content_unit(source, supplement_node).text
        builder.gap(node.start_byte)
        start = builder.length
        builder.add_synthetic(REF_MARK, node.start_byte, node.end_byte)
        builder.unit.references.append(
            Reference(
                key,
                supplement,
                Span(start, builder.length),
                source.node_location(node),
                self.next_order(),
            )
        )


type _LabelSetter = _SetLabel


@dataclass(frozen=True, slots=True)
class _SetLabel:
    target: Figure | Equation | Heading

    def __call__(self, name: str) -> None:
        self.target.label = name


def _setter(target: Figure | Equation | Heading) -> _SetLabel:
    return _SetLabel(target)


def _is_block_math(text: str) -> bool:
    inner = text[1:-1]
    return len(inner) >= 2 and inner[0].isspace() and inner[-1].isspace()


def _bool_arg(node: Node, name: str, source: SourceFile, *, default: bool = False) -> bool:
    value_node = named_arg(node, name, source)
    if value_node is None:
        return default
    value = evaluate(value_node, source)
    return value if isinstance(value, bool) else default


def _is_none_arg(node: Node, name: str, source: SourceFile) -> bool:
    value_node = named_arg(node, name, source)
    return value_node is not None and source.node_text(value_node) == "none"


def _link_headings(document: Document) -> None:
    """Set parent and children from the heading levels."""
    stack: list[Heading] = []
    for heading in document.headings:
        while stack and stack[-1].level >= heading.level:
            stack.pop()
        if stack:
            heading.parent = stack[-1]
            stack[-1].children.append(heading)
        stack.append(heading)
