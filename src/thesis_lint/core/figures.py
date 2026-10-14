"""Rules for figures, tables, equations and cross references."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

from thesis_lint.core.sources import BRINK, HW, VL02, VORLAGE, ref
from thesis_lint.core.structure import (
    FINITE_VERBS,
    arg_text,
    calls,
    chapter,
    concat,
    finite_verb,
    set_rules,
)
from thesis_lint.model import Severity
from thesis_lint.registry import Finding, NoParams, rule
from thesis_lint.typst.document import PLACEHOLDERS, content_unit
from thesis_lint.typst.parse import call_name, named_arg, positional_args, walk
from thesis_lint.typst.values import evaluate

if TYPE_CHECKING:
    from collections.abc import Iterator

    from thesis_lint.context import Context
    from thesis_lint.model import Location
    from thesis_lint.typst.document import Document, Figure, Reference
    from thesis_lint.typst.parse import Node, SourceFile

# Calls in a table that are not cells.
_TABLE_PARTS = frozenset({"table.header", "table.footer", "table.hline", "table.vline"})


def _kind_name(figure: Figure) -> str:
    return {"image": "figure", "table": "table", "raw": "listing"}.get(figure.kind, "figure")


def _location(figure: Figure) -> Location:
    return figure.source.node_location(figure.node)


def _first_references(document: Document) -> dict[str, Reference]:
    """Return the first reference to each key, in document order."""
    first: dict[str, Reference] = {}
    for _unit, reference in sorted(document.references(), key=lambda pair: pair[1].order):
        first.setdefault(reference.key, reference)
    return first


def _captioned(document: Document) -> Iterator[tuple[Figure, str]]:
    """Yield the figures that have a caption, with the caption text."""
    return (
        (figure, figure.caption.text)
        for figure in document.figures
        if figure.caption is not None and figure.caption.text.strip()
    )


@rule(
    "core.figure.caption-label-ref",
    summary="Each figure and table has a caption and a label, and the text refers to it.",
    severity=Severity.ERROR,
    sources=[
        ref(
            HW,
            "S. 139",
            concat(
                "Jede Abbildung und jede Tabelle benötigt eine Nummer, damit Sie im Fließtext ",
                "darauf verweisen können",
            ),
        ),
        ref(BRINK, "S. 196", "Jede Darstellung ist mit einem Titel zu versehen."),
    ],
)
def caption_label_ref(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report figures without a caption, without a label or without a reference."""
    document = ctx.project.document
    referenced = {reference.key for _unit, reference in document.references()}
    for figure in document.figures:
        checks = (
            ("a caption", figure.caption is not None and bool(figure.caption.text.strip())),
            ("a label", figure.label is not None),
            ("a reference in the text", figure.label in referenced),
        )
        missing = [name for name, ok in checks if not ok]
        if missing:
            yield Finding(
                concat(
                    f"the {_kind_name(figure)} has no {' and no '.join(missing)}. ",
                    "Add a caption and a <label>, and refer to it with @label.",
                ),
                _location(figure),
            )


@rule(
    "core.figure.ref-before",
    summary="The text refers to a figure or table before it appears.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 196",
            concat(
                "Dabei ist die Abbildung zunächst im Text anzukündigen, anschließend folgen ",
                "Darstellung und Erläuterung",
            ),
        )
    ],
)
def ref_before(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report figures whose first reference comes after the figure."""
    first = _first_references(ctx.project.document)
    for figure in ctx.project.document.figures:
        reference = first.get(figure.label or "")
        if reference is not None and reference.order > figure.order:
            yield Finding(
                concat(
                    f"the first reference to @{reference.key} comes after the ",
                    f"{_kind_name(figure)}. Refer to it in the text before it appears.",
                ),
                reference.location,
            )


@dataclass(frozen=True, slots=True)
class PatternsParams:
    """Regular expressions that a rule looks for. The match ignores the case."""

    patterns: tuple[str, ...] = ()


def _caption_matches(ctx: Context, patterns: tuple[str, ...]) -> Iterator[tuple[Figure, str]]:
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    for figure, text in _captioned(ctx.project.document):
        match = next((m for p in compiled if (m := p.search(text)) is not None), None)
        if match is not None:
            yield figure, match.group(0)


_OWN_MARKERS = r"\beigene[nrs]? (?:Darstellung|Abbildung|Erhebung|Grafik|Tabelle|Text)\b"


@rule(
    "core.figure.own-figure",
    summary="No caption and no note in the text says 'eigene Darstellung' or 'eigener Text'.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Abbildungen",
            concat(
                "Dementsprechend dürfen selbst erstellte Abbildungen nicht mit Angaben wie ",
                "„eigene Abbildung“ o.ä. versehen werden.",
            ),
        ),
        ref(BRINK, "S. 197", "Auf derartige Bemerkungen sollte jedoch verzichtet werden"),
        ref(
            VL02,
            "Folie 114",
            concat(
                "unsinnig bestimmte Teile Ihrer Arbeit mit der Bemerkung „eigener Text“ oder ",
                "„eigene Abbildung“ zu versehen",
            ),
        ),
    ],
    params=PatternsParams(patterns=(_OWN_MARKERS,)),
)
def own_figure(ctx: Context, params: PatternsParams) -> Iterator[Finding]:
    """Report captions and notes in the text that mark a part as the own work.

    In a caption, each match counts. In the running text and in footnotes, a match
    counts only as a note: in parentheses, after 'Quelle', or as a full sentence.
    So a phrase like 'eine eigene Tabelle der Werte' in a sentence is not a finding.
    """
    captions = (
        Finding(
            concat(
                f"the caption contains {found!r}. Remove it. ",
                "A figure without a source is the own work.",
            ),
            _location(figure),
        )
        for figure, found in _caption_matches(ctx, params.patterns)
    )
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in params.patterns]
    notes = (
        Finding(
            concat(
                f"the text marks a part as own work ({match.group(0)!r}). Remove the note. ",
                "All text and figures without a citation are the own work.",
            ),
            unit.location(match.start(), match.end()),
        )
        for unit in ctx.project.document.prose_units()
        for pattern in compiled
        for match in pattern.finditer(unit.text)
        if not unit.is_quoted(match.start()) and _is_note(unit.text, match.start(), match.end())
    )
    return chain(captions, notes)


_NOTE_BEFORE = re.compile(r"(?:\(|\[|Quelle\s*:?|^|[.!?:]|[\u2013\u2014-])\s*$", re.IGNORECASE)
_NOTE_AFTER = re.compile(r"^\s*(?:[)\].;,]|$)")


def _is_note(text: str, start: int, end: int) -> bool:
    """Return True if the match at `start` to `end` stands alone as a note."""
    marks = "".join(PLACEHOLDERS)
    before = text[:start].rstrip(marks)
    after = text[end:].lstrip(marks)
    return bool(_NOTE_BEFORE.search(before)) and bool(_NOTE_AFTER.match(after))


@dataclass(frozen=True, slots=True)
class ForeignSourceParams:
    """Parameters of `core.figure.foreign-source`.

    Each pattern is a regular expression that marks a foreign source. The match is
    case sensitive. Use `(?i)` to ignore the case.
    """

    patterns: tuple[str, ...] = (
        r"(?i)(?<!\w)Quelle(?!\w)",
        r"(?i)(?<!\w)in Anlehnung an(?!\w)",
        r"(?i)(?<!\w)übernommen(?!\w)",
        r"(?i)(?<!\w)verändert nach(?!\w)",
        r"(?<!\w)(?:[Nn]ach|[Aa]us) [A-ZÄÖÜ][\w.-]*(?: [A-ZÄÖÜ&][\w.-]*)* \(",
    )


@rule(
    "core.figure.foreign-source",
    summary="A caption that names a foreign source cites it with @key.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Abbildungen",
            concat(
                "die Quelle der Abbildung muss angegeben und im Literaturverzeichnis ",
                "referenziert werden",
            ),
        ),
        ref(
            HW,
            "S. 145",
            concat(
                "Auch bei der Übernahme von Tabellen und Abbildungen (vgl. Kap. 6.3) muss ",
                "der/die Urheber/in angegeben werden.",
            ),
        ),
        ref(
            VL02,
            "Folie 35",
            "Urheberrechtsverletzungen möglich, wenn Quelle geschütztes Material verwendet",
        ),
        ref(
            VL02,
            "Folie 110",
            "auch das Design (z.B. bei Bildzitaten) bzw. die wörtliche Formulierung sind geschützt",
        ),
    ],
    params=ForeignSourceParams(),
)
def foreign_source(ctx: Context, params: ForeignSourceParams) -> Iterator[Finding]:
    """Report captions with a source marker but without a citation."""
    compiled = [re.compile(pattern) for pattern in params.patterns]
    for figure, text in _captioned(ctx.project.document):
        match = next((m for p in compiled if (m := p.search(text)) is not None), None)
        caption = figure.caption
        if match is None or caption is None:
            continue
        if not any(ctx.project.is_citation(r.key) for r in caption.references):
            yield Finding(
                concat(
                    f"the caption names a source ({match.group(0)!r}) but cites no entry. ",
                    "Add the citation, for example 'nach @key'.",
                ),
                caption.location(match.start(), match.end()),
            )


@dataclass(frozen=True, slots=True)
class PositionParams:
    """Parameters of `core.figure.caption-position`."""

    position: str = "bottom"


@rule(
    "core.figure.caption-position",
    summary="Captions of figures and tables are below the content.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Abbildungen",
            concat(
                "Der Nummer folgt eine kurze Beschreibung zum Bild, die unterhalb des Bildes ",
                "platziert wird.",
            ),
        ),
        ref(
            VORLAGE,
            "Tabellen",
            concat(
                "Auch die Tabellen werden in gleicher Form wie die Abbildungen nummeriert ",
                "und beschriftet.",
            ),
        ),
    ],
    params=PositionParams(),
)
def caption_position(ctx: Context, params: PositionParams) -> Iterator[Finding]:
    """Report `figure.caption(position: ...)` settings that move the caption."""
    document = ctx.project.document
    found = chain(set_rules(document, "figure.caption"), calls(document, "figure.caption"))
    for source, call in found:
        value = named_arg(call, "position", source)
        if value is not None and source.node_text(value) != params.position:
            yield Finding(
                concat(
                    f"the caption position is {source.node_text(value)!r}. ",
                    f"Remove the override. Captions go to the {params.position}.",
                ),
                source.node_location(value),
            )


@dataclass(frozen=True, slots=True)
class CaptionVerbParams:
    """Parameters of `core.figure.caption-period`."""

    verbs: tuple[str, ...] = FINITE_VERBS


@rule(
    "core.figure.caption-period",
    summary="A caption is a title: no final period and no finite verb.",
    severity=Severity.ERROR,
    sources=[
        ref(VORLAGE, "Abbildungen", "Der Nummer folgt eine kurze Beschreibung zum Bild"),
        ref(
            BRINK,
            "S. 196",
            concat(
                "Dabei gilt analog zur Formulierung von Überschriften, dass keine kompletten ",
                "Sätze auftreten dürfen.",
            ),
        ),
    ],
    params=CaptionVerbParams(),
)
def caption_period(ctx: Context, params: CaptionVerbParams) -> Iterator[Finding]:
    """Report captions that end with a period or contain a finite verb."""
    marks = "".join(PLACEHOLDERS)
    for figure, text in _captioned(ctx.project.document):
        stripped = text.rstrip().rstrip(marks).rstrip()
        if stripped.endswith(".") and not stripped.endswith("..."):
            yield Finding("the caption ends with a period. Remove the period.", _location(figure))
        found = finite_verb(text, params.verbs)
        if found is not None:
            yield Finding(
                concat(
                    f"the caption looks like a sentence (verb {found!r}). ",
                    "Write a short title in the nominal style.",
                ),
                _location(figure),
            )


_COUNTER_UPDATE = re.compile(r"counter\(\s*figure\b.*\)\.(?:update|step)", re.DOTALL)


@rule(
    "core.figure.numbering",
    summary="Figures and tables keep the template numbering per chapter and per kind.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Abbildungen",
            concat(
                "Jede Abbildung erhält eine Nummer, die sich aus der Abschnittsnummer der ",
                "Ebene 1 und einer fortlaufenden, in jedem Abschnitt bei Eins beginnenden ",
                "Nummer ergibt.",
            ),
        )
    ],
)
def numbering(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report overrides of the figure numbering and changes of the figure counters."""
    document = ctx.project.document
    overrides = (
        (source, value)
        for source, call in chain(set_rules(document, "figure"), calls(document, "figure"))
        if (value := named_arg(call, "numbering", source)) is not None
    )
    counters = (
        (source, node)
        for source in document.files
        for node in walk(source.root)
        if node.type == "call" and _COUNTER_UPDATE.fullmatch(call_name(node, source) or "")
    )
    return (
        Finding(
            concat(
                "this code changes the figure numbering. Remove it. ",
                "The template numbers figures and tables per chapter.",
            ),
            source.node_location(node),
        )
        for source, node in chain(overrides, counters)
    )


def _tables(document: Document) -> Iterator[tuple[SourceFile, Node]]:
    return calls(document, "table")


def _header(table: Node, source: SourceFile) -> Node | None:
    return next(
        (
            arg
            for arg in positional_args(table)
            if arg.type == "call" and call_name(arg, source) == "table.header"
        ),
        None,
    )


@rule(
    "core.table.header-repeat",
    summary="Each table has a header row that repeats on every page.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Tabellen",
            concat(
                "Ist es erforderlich einen Seitenumbruch zwischen den Zeilen durchzuführen, so ",
                "muss auf der nächsten Seite die Beschriftung der Spalten wiederholt werden.",
            ),
        )
    ],
)
def header_repeat(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report tables without `table.header` and headers with `repeat: false`."""
    document = ctx.project.document
    for source, table in _tables(document):
        header = _header(table, source)
        if header is None:
            yield Finding(
                "the table has no header row. Put the column titles into table.header(...).",
                source.node_location(table),
            )
        elif arg_text(header, "repeat", source) == "false":
            yield Finding(
                "the table header does not repeat. Remove `repeat: false`.",
                source.node_location(header),
            )
    for source, call in set_rules(document, "table.header"):
        if arg_text(call, "repeat", source) == "false":
            yield Finding(
                "this set rule stops the table headers from repeating. Remove it.",
                source.node_location(call),
            )


@rule(
    "core.figure.see-text",
    summary="A caption does not say 'siehe Text'.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 139 f.",
            "Eine Formulierung wie ‚weitere Erläuterungen siehe Text‘ ist zu vermeiden.",
        )
    ],
    params=PatternsParams(patterns=(r"\b(?:siehe|s\.|vgl\.)\s*(?:Text|Fließtext)\b",)),
)
def see_text(ctx: Context, params: PatternsParams) -> Iterator[Finding]:
    """Report captions that point to the text."""
    return (
        Finding(
            concat(
                f"the caption contains {found!r}. ",
                "Make the caption complete without the text.",
            ),
            _location(figure),
        )
        for figure, found in _caption_matches(ctx, params.patterns)
    )


def _column_count(table: Node, source: SourceFile) -> int | None:
    value_node = named_arg(table, "columns", source)
    if value_node is None:
        return 1
    value = evaluate(value_node, source)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return len(value)
    return None


def _cells(table: Node, source: SourceFile) -> list[Node] | None:
    args = positional_args(table)
    if any(arg.type == "elude" for arg in args):
        return None
    return [
        arg for arg in args if not (arg.type == "call" and call_name(arg, source) in _TABLE_PARTS)
    ]


@rule(
    "core.table.single-column",
    summary="A table has more than one column and more than one data row.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 114",
            concat(
                "Sie arbeiten immer dann mit Text, wenn [...] ein mögliche Tabelle nur ",
                "eine Spalte hätte",
            ),
        )
    ],
)
def single_column(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report tables with one column or one data row."""
    for source, table in _tables(ctx.project.document):
        columns = _column_count(table, source)
        cells = _cells(table, source)
        if columns is None or cells is None or columns <= 0:
            continue
        rows = math.ceil(len(cells) / columns)
        if columns == 1 or rows <= 1:
            yield Finding(
                concat(
                    f"the table has {columns} column(s) and {rows} data row(s). ",
                    "Write the content as text instead.",
                ),
                source.node_location(table),
            )


@rule(
    "core.table.footnote",
    summary="A table contains no footnotes.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 121",
            concat(
                "Um Verwechslungen zu vermeiden, sollten Sie als Fußnotenzeichen nicht Zahlen, ",
                "sondern kleine Buchstaben oder Sonderzeichen wie * oder ‡ verwenden.",
            ),
        )
    ],
)
def table_footnote(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report `#footnote` calls inside tables."""
    return (
        Finding(
            concat(
                "the table contains a footnote. ",
                "Put the note into the caption or below the table with a letter mark.",
            ),
            source.node_location(node),
        )
        for source, table in _tables(ctx.project.document)
        for node in walk(table)
        if node.type == "call" and call_name(node, source) == "footnote"
    )


_UNIT_BRACKETS = re.compile(r"\[[^\[\]]+\]")


def _header_cells(table: Node, source: SourceFile) -> list[Node]:
    header = _header(table, source)
    if header is not None:
        return [arg for arg in positional_args(header) if arg.type == "content"]
    cells = _cells(table, source) or []
    columns = _column_count(table, source) or 1
    return [cell for cell in cells[:columns] if cell.type == "content"]


@rule(
    "core.table.unit-brackets",
    summary="The table header gives units without square brackets.",
    severity=Severity.ERROR,
    sources=[
        ref(
            HW,
            "S. 120",
            concat(
                "Verwenden Sie eckige Klammern nur dort, wo sie in den Natur- und ",
                "Ingenieurwissenschaften eine festgelegte Bedeutung haben",
            ),
        )
    ],
)
def unit_brackets(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report header cells like 'Masse [kg]'."""
    for source, table in _tables(ctx.project.document):
        for cell in _header_cells(table, source):
            match = _UNIT_BRACKETS.search(content_unit(source, cell).text)
            if match is not None:
                yield Finding(
                    concat(
                        f"the table header gives the unit as {match.group(0)!r}. ",
                        "Write 'Masse in kg' or 'Masse (kg)'.",
                    ),
                    source.node_location(cell),
                )


@rule(
    "core.math.numbered",
    summary="Each block equation keeps its number.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Formeln",
            concat(
                "Jede Formel ist über eine fortlaufend aufsteigend zu vergebende Nummer ",
                "zu kennzeichnen.",
            ),
        )
    ],
)
def math_numbered(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report `numbering: none` for equations."""
    document = ctx.project.document
    found = chain(set_rules(document, "math.equation"), calls(document, "math.equation"))
    return (
        Finding(
            "this code removes the equation numbers. Remove `numbering: none`.",
            source.node_location(call),
        )
        for source, call in found
        if arg_text(call, "numbering", source) == "none"
    )


@dataclass(frozen=True, slots=True)
class ForwardParams:
    """Parameters of `core.ref.forward`."""

    excluded_chapters: tuple[str, ...] = ()


@rule(
    "core.ref.forward",
    summary=concat(
        "The text does not refer to later sections. The outline overview in the ",
        "introduction is the exception that Brink allows.",
    ),
    severity=Severity.WARNING,
    sources=[
        ref(
            BRINK,
            "S. 195",
            concat(
                "insbesondere Vorverweise sind nur im Ausnahmefall zu verwenden, denn der Autor ",
                "sollte nicht auf Sachverhalte verweisen, die der Leser nicht einschätzen kann",
            ),
        )
    ],
    params=ForwardParams(),
)
def forward(ctx: Context, params: ForwardParams) -> Iterator[Finding]:
    """Report references to headings that come later in the document.

    Brink (S. 195) allows forward references only as an exception. The preset
    excludes the introduction, because its outline overview is that exception.
    """
    document = ctx.project.document
    headings = {h.label: h for h in document.headings if h.label is not None}
    for unit, reference in document.references():
        target = headings.get(reference.key)
        if target is None or target.order < reference.order:
            continue
        if chapter(unit.heading) in params.excluded_chapters:
            continue
        yield Finding(
            concat(
                f"@{reference.key} refers to the later section {target.text!r}. ",
                "Avoid forward references or explain the topic here.",
            ),
            reference.location,
        )
