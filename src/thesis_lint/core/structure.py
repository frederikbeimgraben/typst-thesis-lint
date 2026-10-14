"""Rules for headings, sections and the outline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from itertools import chain, pairwise
from typing import TYPE_CHECKING

from thesis_lint.context import top_heading
from thesis_lint.core.sources import BRINK, HW, VORLAGE, ref
from thesis_lint.model import Severity
from thesis_lint.registry import Finding, NoParams, rule
from thesis_lint.text import sentences, word_count
from thesis_lint.typst.document import MATH_MARK, PLACEHOLDERS, UnitKind
from thesis_lint.typst.parse import call_name, named_arg, walk
from thesis_lint.typst.values import evaluate

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from thesis_lint.context import Context
    from thesis_lint.typst.document import Document, Heading, Unit
    from thesis_lint.typst.parse import Node, SourceFile

# Unit kinds that hold running text of a section.
PROSE_KINDS = frozenset(
    {UnitKind.PARAGRAPH, UnitKind.ITEM, UnitKind.ENUM_ITEM, UnitKind.TERM, UnitKind.QUOTE_BLOCK}
)
# Finite verb forms that show a full sentence. The list is a heuristic.
FINITE_VERBS = (
    "ist",
    "sind",
    "war",
    "waren",
    "wird",
    "werden",
    "wurde",
    "wurden",
    "hat",
    "haben",
    "hatte",
    "hatten",
    "habe",
    "bin",
    "kann",
    "können",
    "konnte",
    "muss",
    "müssen",
    "musste",
    "soll",
    "sollen",
    "sollte",
    "darf",
    "dürfen",
    "lässt",
    "lassen",
    "gibt",
    "zeigt",
    "zeigen",
)
_WORD = re.compile(r"[^\W\d_][\w-]*")
_STOPWORDS = frozenset(
    {
        "unter",
        "zwischen",
        "durch",
        "gegen",
        "sowie",
        "einer",
        "eines",
        "einem",
        "einen",
        "deren",
        "dessen",
        "dieser",
        "diese",
        "dieses",
        "welche",
        "anhand",
        "innerhalb",
        "außerhalb",
        "bezüglich",
        "hinsichtlich",
        "wegen",
        "während",
        "seiner",
        "ihrer",
    }
)


# Shared helpers. The module `figures` uses them too.


def concat(*parts: str) -> str:
    """Join the parts of a long message or quote without a separator."""
    return "".join(parts)


def chapter(heading: Heading | None) -> str | None:
    """Return the title of the level-1 chapter that contains `heading`."""
    return None if heading is None else top_heading(heading).text


def heading_at(document: Document, order: int) -> Heading | None:
    """Return the last heading before the document position `order`."""
    return max(
        (h for h in document.headings if h.order < order), key=lambda h: h.order, default=None
    )


def words(text: str) -> list[str]:
    """Return the words of a text that start with a letter."""
    return _WORD.findall(text)


def finite_verb(text: str, verbs: Iterable[str]) -> str | None:
    """Return the first finite verb form in `text`, or None."""
    known = frozenset(verb.casefold() for verb in verbs)
    return next((word for word in words(text) if word.casefold() in known), None)


def prose_units(units: Iterable[Unit]) -> Iterator[Unit]:
    """Yield the units that are running text."""
    return (unit for unit in units if unit.kind in PROSE_KINDS)


def sentence_count(units: Iterable[Unit]) -> int:
    """Return the number of sentences in the running text of `units`."""
    return sum(len(sentences(unit)) for unit in prose_units(units))


def set_rules(document: Document, function: str) -> Iterator[tuple[SourceFile, Node]]:
    """Yield the call nodes of every `set <function>(...)` rule in the sources."""
    return (
        (source, call)
        for source in document.files
        for node in walk(source.root)
        if node.type == "set"
        for call in node.children
        if call.type == "call" and call_name(call, source) == function
    )


def calls(document: Document, function: str) -> Iterator[tuple[SourceFile, Node]]:
    """Yield the calls of `function` in the sources, except the calls in `set` rules."""
    return (
        (source, node)
        for source in document.files
        for node in walk(source.root)
        if node.type == "call"
        and call_name(node, source) == function
        and (node.parent is None or node.parent.type != "set")
    )


def arg_text(node: Node, name: str, source: SourceFile) -> str | None:
    """Return the source text of the named argument `name`, or None."""
    value = named_arg(node, name, source)
    return None if value is None else source.node_text(value)


def outline_children(heading: Heading, depth: int) -> list[Heading]:
    """Return the child headings that the outline shows."""
    return [child for child in heading.children if child.outlined and child.level <= depth]


def _sibling_groups(document: Document, depth: int) -> Iterator[list[Heading]]:
    top = [h for h in document.top_headings if h.outlined]
    children = (outline_children(h, depth) for h in document.headings)
    return (group for group in chain([top], children) if group)


def _first_word(heading: Heading) -> str:
    found = words(heading.text)
    return found[0].casefold() if found else ""


def _casefolded(values: Iterable[str]) -> frozenset[str]:
    return frozenset(value.casefold() for value in values)


@cache
def _word_pattern(alternatives: tuple[str, ...], endings: str = "") -> re.Pattern[str]:
    joined = "|".join(re.escape(word) for word in sorted(alternatives, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{joined}){endings}(?!\w)", re.IGNORECASE)


# Heading rules


@dataclass(frozen=True, slots=True)
class OutlineParams:
    """Parameters of the rules that count headings in the outline."""

    outline_depth: int = 3


@rule(
    "core.heading.min-children",
    summary="A heading with subsections has at least two subsections.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 146 f.",
            "Keinesfalls darf zu einem Oberpunkt nur ein einziger Unterpunkt eingerichtet werden.",
        ),
        ref(
            HW, "S. 67", "Eine Gliederungsebene darf nicht nur ein einziges Unterkapitel beinhalten"
        ),
    ],
    params=OutlineParams(),
)
def min_children(ctx: Context, params: OutlineParams) -> Iterator[Finding]:
    """Report headings with exactly one child heading in the outline."""
    return (
        Finding(
            f"heading {heading.text!r} has only one subsection. Add a second one or remove it.",
            heading.location,
        )
        for heading in ctx.project.document.headings
        if len(outline_children(heading, params.outline_depth)) == 1
    )


@rule(
    "core.heading.duplicate",
    summary="Each heading is unique and no heading repeats the title of the thesis.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Titel und Überschriften",
            concat(
                "Überschriften dürfen sich nicht wiederholen, sondern müssen eindeutig ",
                "voneinander ",
                "zu unterscheiden sein.",
            ),
        ),
        ref(
            BRINK,
            "S. 169",
            concat(
                "Eine doppelte Belegung von Überschriften auf unterschiedlichen Gliederungsebenen ",
                "ist zu vermeiden.",
            ),
        ),
    ],
)
def duplicate(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report headings that repeat another heading or the thesis title."""
    title = _normalize(ctx.project.setting_text("title") or "")
    seen: dict[str, Heading] = {}
    for heading in ctx.project.document.headings:
        key = _normalize(heading.text)
        if not key:
            continue
        if key == title:
            yield Finding(
                f"heading {heading.text!r} is the same as the thesis title. Make it more specific.",
                heading.location,
            )
        first = seen.setdefault(key, heading)
        if first is not heading:
            yield Finding(
                concat(
                    f"heading {heading.text!r} is the same as the heading in ",
                    f"{first.location.path.name}:{first.location.line}. Use a different title.",
                ),
                heading.location,
            )


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


@dataclass(frozen=True, slots=True)
class SiblingParams:
    """Parameters of `core.heading.max-siblings`."""

    max_siblings: int = 6
    outline_depth: int = 3


@rule(
    "core.heading.max-siblings",
    summary="A heading has at most six subsections.",
    severity=Severity.WARNING,
    sources=[
        ref(
            BRINK,
            "S. 146",
            "sollten maximal sechs Gliederungspunkte auf einer Ebene unterschieden werden",
        ),
        ref(
            BRINK,
            "S. 172 f.",
            concat(
                "Es gibt praktisch keine Problemstellung, bei der es nicht möglich wäre, ",
                "mit sechs oder weniger Unterpunkten auszukommen.",
            ),
        ),
    ],
    params=SiblingParams(),
)
def max_siblings(ctx: Context, params: SiblingParams) -> Iterator[Finding]:
    """Report headings with too many child headings in the outline."""
    for heading in ctx.project.document.headings:
        children = outline_children(heading, params.outline_depth)
        if len(children) > params.max_siblings:
            yield Finding(
                concat(
                    f"heading {heading.text!r} has {len(children)} subsections. ",
                    f"Use at most {params.max_siblings} and group related subsections.",
                ),
                heading.location,
            )


@dataclass(frozen=True, slots=True)
class UnnumberedParams:
    """Parameters of `core.heading.unnumbered`."""

    exempt_chapter: str = "Anhang"
    exempt_level: int = 4


@rule(
    "core.heading.unnumbered",
    summary="All headings are numbered and in the outline, except the improvement entries.",
    severity=Severity.ERROR,
    sources=[
        ref(
            HW,
            "S. 88",
            concat(
                "dass alle Überschriften, die Sie in der Endfassung Ihres Textes verwenden, ",
                "nummeriert werden und somit im Inhaltsverzeichnis auftauchen müssen",
            ),
        ),
        ref(
            BRINK,
            "S. 186 f.",
            concat(
                "weitere Überschriften zu formulieren, die im Inhaltsverzeichnis der Arbeit ",
                "nicht auftreten",
            ),
        ),
    ],
    params=UnnumberedParams(),
)
def unnumbered(ctx: Context, params: UnnumberedParams) -> Iterator[Finding]:
    """Report headings with `numbering: none` or `outlined: false`."""
    document = ctx.project.document
    for heading in document.headings:
        if heading.numbered and heading.outlined:
            continue
        if chapter(heading) == params.exempt_chapter and heading.level >= params.exempt_level:
            continue
        yield Finding(
            concat(
                f"heading {heading.text!r} has no number or is not in the outline. ",
                "Remove `numbering: none` and `outlined: false`.",
            ),
            heading.location,
        )
    for source, call in set_rules(document, "heading"):
        if arg_text(call, "numbering", source) == "none" or (
            arg_text(call, "outlined", source) == "false"
        ):
            yield Finding(
                "this set rule removes the heading numbers or the outline entries. Remove it.",
                source.node_location(call),
            )


@dataclass(frozen=True, slots=True)
class PunctuationParams:
    """Parameters of `core.heading.punctuation`."""

    characters: str = "?.:;!–—"


@rule(
    "core.heading.punctuation",
    summary="A heading has no punctuation marks, dashes or formulas.",
    severity=Severity.ERROR,
    sources=[
        ref(
            HW,
            "S. 88",
            concat(
                "Abkürzungen, Formeln und unbekannte Symbole sollten ebenfalls nicht in ",
                "Kapitelüberschriften verwendet werden",
            ),
        ),
        ref(
            BRINK,
            "S. 167 f.",
            concat(
                "Die Überschriften der einzelnen Gliederungspunkte dürfen weder Formeln noch ",
                "(unbekannte) Symbole oder Satzzeichen enthalten.",
            ),
        ),
    ],
    params=PunctuationParams(),
)
def punctuation(ctx: Context, params: PunctuationParams) -> Iterator[Finding]:
    """Report punctuation marks and formulas in headings."""
    for heading in ctx.project.document.headings:
        text = heading.title.text
        hits = [i for i in range(len(text)) if _is_bad_mark(text, i, params.characters)]
        if hits:
            shown = "".join(dict.fromkeys(_mark_name(text, i) for i in hits))
            yield Finding(
                concat(
                    f"heading {heading.text!r} contains {shown!r}. ",
                    "Remove punctuation marks, dashes and formulas.",
                ),
                heading.title.location(hits[0], hits[0] + 1),
            )


def _is_bad_mark(text: str, index: int, characters: str) -> bool:
    char = text[index]
    if char == MATH_MARK:
        return True
    if char == "-":
        return text[index - 1 : index] == " " and text[index + 1 : index + 2] == " "
    if char not in characters:
        return False
    if char == ".":
        # A version number or a decimal number like "2.0" is not punctuation.
        return not (text[index - 1 : index].isdigit() and text[index + 1 : index + 2].isdigit())
    return True


def _mark_name(text: str, index: int) -> str:
    return "$...$" if text[index] == MATH_MARK else text[index]


@rule(
    "core.heading.capital",
    summary="A heading starts with a capital letter.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 168",
            concat(
                "Überschriften sind als Titel von Gliederungsabschnitten zu interpretieren, [...] ",
                "und beginnen wie jeder Titel mit einem Großbuchstaben.",
            ),
        )
    ],
)
def capital(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report headings that start with a lowercase letter."""
    for heading in ctx.project.document.headings:
        title = heading.title
        index = next(
            (i for i, c in enumerate(title.text) if c.isalpha() or c in PLACEHOLDERS), None
        )
        if index is None or title.text[index] in PLACEHOLDERS:
            continue
        if any(use.span.start <= index < use.span.end for use in title.glossary):
            continue
        if title.text[index].islower():
            yield Finding(
                concat(
                    f"heading {heading.text!r} starts with a lowercase letter. ",
                    "Start it with a capital letter.",
                ),
                title.location(index, index + 1),
            )


_QUOTE_CHARS = frozenset('„“”"»«')


@rule(
    "core.heading.quotes",
    summary="A heading has no quotation marks.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 88",
            "Verwenden Sie auch keine Zitate in doppelten oder einfachen Anführungszeichen",
        )
    ],
)
def quotes(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report headings with quotation marks."""
    return (
        Finding(
            f"heading {heading.text!r} contains quotation marks. Remove them.",
            heading.location,
        )
        for heading in ctx.project.document.headings
        if heading.title.quotes or _QUOTE_CHARS & set(heading.title.text)
    )


@dataclass(frozen=True, slots=True)
class WordsParams:
    """A list of words that a rule looks for."""

    words: tuple[str, ...] = ()


@rule(
    "core.heading.first-person",
    summary="A heading has no first person words like 'ich' or 'mein'.",
    severity=Severity.ERROR,
    sources=[ref(HW, "S. 89", "Überschriften objektiv formulieren (daher nie 1. Pers. Sing.).")],
    params=WordsParams(
        words=("ich", "mich", "mir", "mein", "meine", "meiner", "meines", "meinem", "meinen")
    ),
)
def first_person(ctx: Context, params: WordsParams) -> Iterator[Finding]:
    """Report headings with first person singular words."""
    return _word_findings(
        ctx,
        params.words,
        "",
        "heading {title!r} uses the first person {word!r}. Write it objectively.",
    )


@rule(
    "core.heading.evaluative",
    summary="A heading contains no evaluative words.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 168 f.",
            concat(
                "Auf keinen Fall dürfen Überschriften eine Wertung enthalten (wie etwa: ",
                "Voraussetzungen erfolgreicher Fertigungskonzepte, Notwendigkeit der ",
                "Finanzplanung ",
                "oder Due Diligence als Erfolgsfaktor für Unternehmensakquisitionen).",
            ),
        )
    ],
    params=WordsParams(
        words=(
            "erfolgreich",
            "Erfolgsfaktor",
            "notwendig",
            "Notwendigkeit",
            "optimal",
            "ideal",
            "perfekt",
            "hervorragend",
            "gelungen",
            "unverzichtbar",
            "unerlässlich",
            "mangelhaft",
            "schlecht",
            "vorbildlich",
            "überragend",
            "beste",
            "bessere",
        )
    ),
)
def evaluative(ctx: Context, params: WordsParams) -> Iterator[Finding]:
    """Report headings with evaluative words. Inflected forms match too."""
    return _word_findings(
        ctx,
        params.words,
        "(?:e|en|er|es|em|n|s)?",
        "heading {title!r} contains the evaluative word {word!r}. Write it neutrally.",
    )


def _word_findings(
    ctx: Context, vocabulary: tuple[str, ...], endings: str, template: str
) -> Iterator[Finding]:
    pattern = _word_pattern(vocabulary, endings)
    for heading in ctx.project.document.headings:
        match = pattern.search(heading.title.text)
        if match is not None:
            yield Finding(
                template.format(title=heading.text, word=match.group(0)),
                heading.title.location(match.start(), match.end()),
            )


@rule(
    "core.heading.verb",
    summary="A heading is in the nominal style and is not a sentence (heuristic).",
    severity=Severity.WARNING,
    sources=[
        ref(
            BRINK,
            "S. 168",
            concat(
                "Gliederungen dürfen keine kompletten Sätze beinhalten; der Verfasser darf sich ",
                "keiner Verben, sondern nur ihrer substantivierten Form bedienen (Nominalstil).",
            ),
        )
    ],
    params=WordsParams(words=FINITE_VERBS),
)
def verb(ctx: Context, params: WordsParams) -> Iterator[Finding]:
    """Report headings that contain a finite verb from the list."""
    for heading in ctx.project.document.headings:
        found = finite_verb(heading.title.text, params.words)
        if found is not None:
            yield Finding(
                concat(
                    f"heading {heading.text!r} looks like a sentence (verb {found!r}). ",
                    "Use the nominal style.",
                ),
                heading.location,
            )


@dataclass(frozen=True, slots=True)
class MiscParams:
    """Parameters of `core.heading.other-misc`."""

    misc_words: tuple[str, ...] = (
        "Weitere",
        "Weiterer",
        "Weiteres",
        "Sonstige",
        "Sonstiger",
        "Sonstiges",
    )
    min_before: int = 2
    forbidden: tuple[str, ...] = ("Exkurs",)
    outline_depth: int = 3


@rule(
    "core.heading.other-misc",
    summary="'Weitere'/'Sonstige' only after two named siblings, and no 'Exkurs'.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 147",
            concat(
                "so darf dieses lediglich erfolgen, wenn in den (gleichrangigen) ",
                "Gliederungspunkten ",
                "zuvor mindestens zwei, besser drei Gesichtspunkte (namentlich) einzeln ",
                "angeführt sind",
            ),
        ),
        ref(
            BRINK,
            "S. 217",
            "Exkurse würden den logischen Aufbau der Arbeit nur stören",
        ),
    ],
    params=MiscParams(),
)
def other_misc(ctx: Context, params: MiscParams) -> Iterator[Finding]:
    """Report early catch-all headings and digressions."""
    misc = _casefolded(params.misc_words)
    for group in _sibling_groups(ctx.project.document, params.outline_depth):
        for index, heading in enumerate(group):
            if _first_word(heading) in misc and index < params.min_before:
                yield Finding(
                    concat(
                        f"heading {heading.text!r} collects other topics, but only {index} ",
                        "sibling(s) ",
                        f"come before it. Name at least {params.min_before} topics first.",
                    ),
                    heading.location,
                )
    forbidden = _word_pattern(params.forbidden, r"\w*")
    for heading in ctx.project.document.headings:
        if forbidden.search(heading.text):
            yield Finding(
                concat(
                    f"heading {heading.text!r} is a digression. ",
                    "Put the topic into the outline or remove it.",
                ),
                heading.location,
            )


@dataclass(frozen=True, slots=True)
class PlaceholderParams:
    """Parameters of `core.heading.placeholder-first`."""

    words: tuple[str, ...] = ("Vorbemerkung", "Vorbemerkungen", "Einführung", "Überblick")
    outline_depth: int = 3


@rule(
    "core.heading.placeholder-first",
    summary="The first of two subsections is not a general 'Einführung' or 'Überblick'.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 147",
            concat(
                "wobei sie den ersten mit einer allgemeinen Überschrift belegen, wie etwa ",
                "Vorbemerkungen, Einführung oder Überblick. Auch dieses ist nicht zulässig",
            ),
        )
    ],
    params=PlaceholderParams(),
)
def placeholder_first(ctx: Context, params: PlaceholderParams) -> Iterator[Finding]:
    """Report a general first subsection when a heading has exactly two subsections."""
    general = _casefolded(params.words)
    for heading in ctx.project.document.headings:
        children = outline_children(heading, params.outline_depth)
        if len(children) == 2 and _first_word(children[0]) in general:
            yield Finding(
                concat(
                    f"subsection {children[0].text!r} is only a general introduction to ",
                    f"{heading.text!r}. Give it a specific topic or remove the subdivision.",
                ),
                children[0].location,
            )


@dataclass(frozen=True, slots=True)
class ArticleParams:
    """Parameters of `core.heading.article-consistent`."""

    articles: tuple[str, ...] = (
        "der",
        "die",
        "das",
        "des",
        "dem",
        "den",
        "ein",
        "eine",
        "einer",
        "eines",
        "einem",
        "einen",
    )
    outline_depth: int = 3


@rule(
    "core.heading.article-consistent",
    summary="Sibling headings all start with an article or all start without one.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 172",
            concat(
                "so muss doch zumindest bei den zusammengehörenden Überschriften einer ",
                "Gliederungsebene stets entweder mit oder ohne einführenden Artikel gearbeitet ",
                "werden",
            ),
        )
    ],
    params=ArticleParams(),
)
def article_consistent(ctx: Context, params: ArticleParams) -> Iterator[Finding]:
    """Report the minority of sibling headings when articles are mixed."""
    articles = _casefolded(params.articles)
    for group in _sibling_groups(ctx.project.document, params.outline_depth):
        flags = [_first_word(heading) in articles for heading in group]
        with_article = sum(flags)
        if with_article in {0, len(group)}:
            continue
        minority = with_article * 2 <= len(group)
        state = "starts with an article" if minority else "has no article"
        yield from (
            Finding(
                concat(
                    f"heading {heading.text!r} {state}, but most sibling headings do not. ",
                    "Use the same form for all siblings.",
                ),
                heading.location,
            )
            for heading, flag in zip(group, flags, strict=True)
            if flag == minority
        )


_DOTTED_ABBREVIATION = re.compile(
    r"(?<!\w)(?:z\.\s?B|d\.\s?h|u\.\s?a|bzw|ggf|usw|etc|vgl|sog|bspw|evtl|inkl|ca)\.", re.IGNORECASE
)
_CAPITAL_TOKEN = re.compile(r"(?<![\w-])[^\W\d_]*[A-ZÄÖÜ][^\W\d_]*[A-ZÄÖÜ][^\W\d_]*(?![\w])")
_ROMAN = re.compile(r"[IVXLC]+")


@rule(
    "core.heading.abbreviation",
    summary="A heading contains no abbreviations and no glossary references.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 88",
            concat(
                "Abkürzungen, Formeln und unbekannte Symbole sollten ebenfalls nicht in ",
                "Kapitelüberschriften verwendet werden",
            ),
        )
    ],
)
def abbreviation(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report abbreviations and `#gls` uses in headings."""
    for heading in ctx.project.document.headings:
        title = heading.title
        found = [
            *(title.text[use.span.start : use.span.end] for use in title.glossary),
            *(
                match.group(0)
                for match in _CAPITAL_TOKEN.finditer(title.text)
                if not _ROMAN.fullmatch(match.group(0))
                and not any(u.span.start <= match.start() < u.span.end for u in title.glossary)
            ),
            *(match.group(0) for match in _DOTTED_ABBREVIATION.finditer(title.text)),
        ]
        if found:
            shown = ", ".join(dict.fromkeys(found))
            yield Finding(
                concat(
                    f"heading {heading.text!r} contains the abbreviation(s) {shown}. ",
                    "Write the full term.",
                ),
                heading.location,
            )


@dataclass(frozen=True, slots=True)
class RepeatParams:
    """Parameters of `core.heading.repeats-parent`."""

    min_length: int = 5


@rule(
    "core.heading.repeats-parent",
    summary="A subsection heading does not repeat a content word of its parent heading.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 88",
            concat(
                "Es sieht zudem unschön aus, wenn Formulierungen in Überschriften der ersten ",
                "Gliederungsebene in der zweiten Gliederungsebene wiederholt werden.",
            ),
        )
    ],
    params=RepeatParams(),
)
def repeats_parent(ctx: Context, params: RepeatParams) -> Iterator[Finding]:
    """Report child headings that repeat a word of their parent heading."""
    for heading in ctx.project.document.headings:
        if heading.parent is None:
            continue
        parent_words = _content_words(heading.parent.title.text, params.min_length)
        repeated = [w for w in words(heading.title.text) if w.casefold() in parent_words]
        if repeated:
            yield Finding(
                concat(
                    f"heading {heading.text!r} repeats {repeated[0]!r} from the parent heading ",
                    f"{heading.parent.text!r}. Remove the repetition.",
                ),
                heading.location,
            )


def _content_words(text: str, min_length: int) -> frozenset[str]:
    return frozenset(
        word.casefold()
        for word in words(text)
        if len(word) >= min_length and word.casefold() not in _STOPWORDS
    )


@dataclass(frozen=True, slots=True)
class PhrasesParams:
    """A list of phrases that a rule looks for. The match ignores the case."""

    phrases: tuple[str, ...] = ()


@rule(
    "core.heading.suspense",
    summary="A heading uses no suspense phrases like 'Was nun' or an ellipsis.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 88",
            concat(
                "Ebenso wenig eignen sich Spannung erzeugende Mittel und Formulierungen ",
                "(z. B. Was nun … ?)",
            ),
        )
    ],
    params=PhrasesParams(phrases=("Was nun", "Zum Schluss", "…")),
)
def suspense(ctx: Context, params: PhrasesParams) -> Iterator[Finding]:
    """Report headings with suspense phrases."""
    for heading in ctx.project.document.headings:
        text = heading.title.text.casefold()
        found = next((p for p in params.phrases if p.casefold() in text), None)
        if found is not None:
            yield Finding(
                concat(
                    f"heading {heading.text!r} uses the suspense phrase {found!r}. ",
                    "State the topic of the section.",
                ),
                heading.location,
            )


@rule(
    "core.heading.numbering-format",
    summary="Heading numbers have no final period ('2.1', not '2.1.').",
    severity=Severity.ERROR,
    sources=[
        ref(
            HW,
            "S. 88",
            concat(
                "Folgt man DIN 1421, stehen nach den Ziffern der Kapitelnummerierung ",
                "(also Kapitel 1, 2, 3 …) keine Punkte",
            ),
        ),
        ref(BRINK, "S. 143 f.", "Der Schlusspunkt entfällt jeweils."),
    ],
)
def numbering_format(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report heading numbering patterns that end with a period."""
    document = ctx.project.document
    for source, call in chain(set_rules(document, "heading"), calls(document, "heading")):
        value_node = named_arg(call, "numbering", source)
        if value_node is None:
            continue
        value = evaluate(value_node, source)
        if isinstance(value, str) and value.rstrip().endswith("."):
            yield Finding(
                concat(
                    f"the heading numbering {value!r} ends with a period. ",
                    "Remove the final period, for example '1.1'.",
                ),
                source.node_location(value_node),
            )


@rule(
    "core.heading.citation",
    summary="A heading contains no citation, reference or footnote.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 229",
            "Ein Fußnotenzeichen steht niemals an der Überschrift eines Kapitels",
        )
    ],
)
def citation(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report references and footnotes in headings."""
    for heading in ctx.project.document.headings:
        title = heading.title
        if title.references or title.footnotes:
            yield Finding(
                concat(
                    f"heading {heading.text!r} contains a citation, reference or footnote. ",
                    "Move it into the text.",
                ),
                heading.location,
            )


# Section rules


@dataclass(frozen=True, slots=True)
class SectionParams:
    """Parameters of `core.section.min-sentences`."""

    min_sentences: int = 3
    excluded_chapters: tuple[str, ...] = (
        "Literaturverzeichnis",
        "Danksagungen",
        "Eidesstattliche Erklärung",
        "Anhang",
    )


@rule(
    "core.section.min-sentences",
    summary="A section without subsections has at least three sentences.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Gliederung des Textes",
            concat(
                "dass ein mit einer Überschrift versehener Textblock nicht nur aus einem oder ",
                "wenigen Sätzen bestehen darf",
            ),
        ),
        ref(
            BRINK,
            "S. 174",
            concat(
                "Als absolutes Minimum eines Gliederungspunktes werden in dieser Schrift ",
                "drei Sätze empfohlen",
            ),
        ),
    ],
    params=SectionParams(),
)
def min_sentences(ctx: Context, params: SectionParams) -> Iterator[Finding]:
    """Report leaf sections with too few sentences."""
    for heading in ctx.project.document.headings:
        if heading.children or chapter(heading) in params.excluded_chapters:
            continue
        count = sentence_count(heading.units)
        if count < params.min_sentences:
            yield Finding(
                concat(
                    f"section {heading.text!r} has {count} sentence(s). ",
                    f"Write at least {params.min_sentences} or merge it with another section.",
                ),
                heading.location,
            )


@dataclass(frozen=True, slots=True)
class PreambleParams:
    """Parameters of `core.section.preamble`."""

    max_sentences: int = 2
    outline_depth: int = 3


@rule(
    "core.section.preamble",
    summary="The text between a heading and its first subsection has at most two sentences.",
    severity=Severity.WARNING,
    sources=[
        ref(
            BRINK,
            "S. 173 f.",
            concat(
                "Allenfalls kurze einführende Sätze, die auf das weitere Vorgehen hinweisen, ",
                "[...] können akzeptiert werden",
            ),
        )
    ],
    params=PreambleParams(),
)
def preamble(ctx: Context, params: PreambleParams) -> Iterator[Finding]:
    """Report long text before the first subsection."""
    for heading in ctx.project.document.headings:
        if not outline_children(heading, params.outline_depth):
            continue
        count = sentence_count(heading.units)
        if count > params.max_sentences:
            yield Finding(
                concat(
                    f"heading {heading.text!r} has {count} sentences before its first subsection. ",
                    f"Use at most {params.max_sentences} or move the text into a subsection.",
                ),
                heading.location,
            )


@dataclass(frozen=True, slots=True)
class BalanceParams:
    """Parameters of `core.section.balance`."""

    chapters: tuple[str, ...] = ("Methoden", "Ergebnisse", "Diskussion")
    max_factor: float = 3.0


@rule(
    "core.section.balance",
    summary="The main chapters have a similar length (factor at most 3).",
    severity=Severity.WARNING,
    sources=[
        ref(
            BRINK,
            "S. 155",
            concat(
                "dass die Gliederungshauptpunkte (ohne Einleitung und Schluss) in einem annähernd ",
                "gleichen Textumfang bearbeitet werden",
            ),
        )
    ],
    params=BalanceParams(),
)
def balance(ctx: Context, params: BalanceParams) -> Iterator[Finding]:
    """Report a main chapter that is much shorter than the longest one."""
    found = [
        (heading, sum(word_count(u.text) for u in prose_units(heading.all_units())))
        for title in params.chapters
        if (heading := ctx.heading_by_title(title)) is not None
    ]
    if len(found) < 2:
        return
    shortest, low = min(found, key=lambda item: item[1])
    longest, high = max(found, key=lambda item: item[1])
    if high > params.max_factor * low:
        yield Finding(
            concat(
                f"chapter {shortest.text!r} has {low} words, but {longest.text!r} has {high}. ",
                f"Keep the factor at {params.max_factor:g} or less.",
            ),
            shortest.location,
        )


@dataclass(frozen=True, slots=True)
class ChapterParams:
    """The title of the chapter that a rule checks."""

    chapter: str = ""


@rule(
    "core.intro.no-figure",
    summary="The introduction contains no figures and no tables.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 184",
            concat(
                "Die Unterbringung von Abbildungen oder Tabellen verbietet sich angesichts des ",
                "knappen Seitenumfangs ebenfalls.",
            ),
        )
    ],
    params=ChapterParams(chapter="Einleitung"),
)
def intro_no_figure(ctx: Context, params: ChapterParams) -> Iterator[Finding]:
    """Report figures, tables and images in the introduction."""
    document = ctx.project.document
    figures = (
        (figure.source, figure.node)
        for figure in document.figures
        if chapter(figure.heading) == params.chapter
    )
    blocks = (
        (call.source, call.node)
        for call in document.calls
        if call.name in {"table", "image"}
        and chapter(heading_at(document, call.order)) == params.chapter
    )
    return (
        Finding(
            concat(
                f"the chapter {params.chapter!r} contains a figure or table. ",
                "Move it into a later chapter.",
            ),
            source.node_location(node),
        )
        for source, node in chain(figures, blocks)
    )


@dataclass(frozen=True, slots=True)
class ApologyParams:
    """Parameters of `core.conclusion.apology`."""

    chapter: str = "Zusammenfassung"
    patterns: tuple[str, ...] = (
        r"\bleider\b",
        r"\bkonnten?\b[^.!?]*\bnicht\b",
        r"\baus Zeitgründen\b",
        r"\bin der Kürze der Zeit\b",
        r"\b(?:wesentlich|wichtig|bedeutend|entscheidend|groß)\w*\s+(?:Fortschritt|Beitrag)",
        r"\bist (?:es )?gelungen\b",
        r"\berfolgreich (?:gezeigt|bewiesen|gelöst)\b",
    )


@rule(
    "core.conclusion.apology",
    summary="The conclusion has no apology and no evaluation of the own work.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 199",
            concat(
                "Eine Entschuldigung für die eigene, vielleicht unzulängliche Leistung, eine ",
                "Beurteilung der eigenen Arbeit [...] haben strikt zu unterbleiben.",
            ),
        )
    ],
    params=ApologyParams(),
)
def conclusion_apology(ctx: Context, params: ApologyParams) -> Iterator[Finding]:
    """Report apologies and self-evaluation in the conclusion chapter."""
    heading = ctx.heading_by_title(params.chapter)
    if heading is None:
        return
    patterns = [re.compile(p, re.IGNORECASE) for p in params.patterns]
    for unit in prose_units(heading.all_units()):
        for pattern in patterns:
            for match in pattern.finditer(unit.text):
                if not unit.is_quoted(match.start()):
                    yield Finding(
                        concat(
                            f"the conclusion contains {match.group(0)!r}. ",
                            "Do not apologize for or evaluate the own work.",
                        ),
                        unit.location(match.start(), match.end()),
                    )


@rule(
    "core.appendix.referenced",
    summary="The main text refers to the appendix at least once.",
    severity=Severity.ERROR,
    sources=[
        ref(
            HW,
            "S. 194",
            concat(
                "Wenn Sie einen Anhang anlegen, müssen Sie in Ihrem Fließtext mindestens ein Mal ",
                "darauf verweisen.",
            ),
        ),
        ref(
            BRINK,
            "S. 200",
            concat(
                "hat zumindest an einer Stelle des Textteils der Arbeit ein Verweis auf den ",
                "Anhang ",
                "[...] zu erfolgen",
            ),
        ),
    ],
    params=ChapterParams(chapter="Anhang"),
)
def appendix_referenced(ctx: Context, params: ChapterParams) -> Iterator[Finding]:
    """Report an appendix that no reference outside the appendix points to."""
    document = ctx.project.document
    appendix = ctx.heading_by_title(params.chapter)
    if appendix is None:
        return
    targets = {
        *(h.label for h in document.headings if chapter(h) == params.chapter),
        *(f.label for f in document.figures if chapter(f.heading) == params.chapter),
        *(e.label for e in document.equations if chapter(e.heading) == params.chapter),
    } - {None}
    referenced = any(
        reference.key in targets
        for unit, reference in document.references()
        if chapter(unit.heading) != params.chapter
    )
    if not referenced:
        yield Finding(
            concat(
                f"the text does not refer to the chapter {params.chapter!r}. ",
                "Add a label in the appendix and refer to it with @label.",
            ),
            appendix.location,
        )


# List rules

_ITEM_KINDS = frozenset({UnitKind.ITEM, UnitKind.ENUM_ITEM})
_CONJUNCTION = re.compile(r"(?:^|[\s,])(?:und|sowie|oder)$")
_SENTENCE_END = (".", "!", "?")


@dataclass(frozen=True, slots=True)
class ListItem:
    """A list item and the information if a nested list follows it."""

    unit: Unit
    has_children: bool

    @property
    def ending(self) -> str:
        """Return the item text without the final white space and reference marks."""
        return self.unit.text.rstrip().rstrip("".join(PLACEHOLDERS)).rstrip()


def item_lists(document: Document) -> list[list[ListItem]]:
    """Return the lists of the document. A list holds sibling items of one kind and depth."""
    units = [unit for unit in document.units if unit.kind != UnitKind.FOOTNOTE]
    parents = {
        id(item)
        for item, after in pairwise(units)
        if item.kind in _ITEM_KINDS and after.kind in _ITEM_KINDS and after.depth > item.depth
    }
    lists: list[list[ListItem]] = []
    current: dict[int, list[ListItem]] = {}
    for unit in units:
        if unit.kind not in _ITEM_KINDS:
            current.clear()
            continue
        for depth in [d for d in current if d > unit.depth]:
            del current[depth]
        siblings = current.get(unit.depth)
        if siblings is None or siblings[-1].unit.kind != unit.kind:
            siblings = list[ListItem]()
            lists.append(siblings)
            current[unit.depth] = siblings
        siblings.append(ListItem(unit, has_children=id(unit) in parents))
    return lists


def _checked_lists(ctx: Context, excluded: tuple[str, ...]) -> Iterator[list[ListItem]]:
    return (
        items
        for items in item_lists(ctx.project.document)
        if len(items) >= 2 and chapter(items[0].unit.heading) not in excluded
    )


def _is_sentence_list(items: list[ListItem]) -> bool:
    return all(item.ending.endswith(_SENTENCE_END) for item in items)


def _continues(item: ListItem) -> bool:
    """Return True if the item ends like an element of an enumeration that goes on."""
    ending = item.ending
    return (
        ending.endswith(",")
        or bool(_CONJUNCTION.search(ending))
        or (item.has_children and ending.endswith(":"))
    )


def _is_enumeration(items: list[ListItem]) -> bool:
    return all(_continues(item) for item in items[:-1])


@dataclass(frozen=True, slots=True)
class ListShareParams:
    """Parameters of `core.list.share`."""

    max_share: float = 0.5
    excluded_chapters: tuple[str, ...] = ("Eidesstattliche Erklärung",)


@rule(
    "core.list.share",
    summary="Lists take at most half of a section.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 97",
            concat(
                "Aufzählungen sollten nicht einen ganzen Abschnitt einnehmen, sondern nur für ",
                "wenige Hervorhebungen innerhalb eines Abschnittes eingesetzt werden.",
            ),
        )
    ],
    params=ListShareParams(),
    submission=True,
)
def list_share(ctx: Context, params: ListShareParams) -> Iterator[Finding]:
    """Report sections whose text is mostly list items."""
    for heading in ctx.project.document.headings:
        if chapter(heading) in params.excluded_chapters:
            continue
        units = list(prose_units(heading.units))
        total = sum(len(unit.text) for unit in units)
        listed = sum(len(unit.text) for unit in units if unit.kind in _ITEM_KINDS)
        if total and listed / total > params.max_share:
            yield Finding(
                concat(
                    f"lists take {listed / total:.0%} of the section {heading.text!r}. ",
                    "Write the content as running text.",
                ),
                heading.location,
            )


@dataclass(frozen=True, slots=True)
class ListParams:
    """Parameters of the list rules."""

    excluded_chapters: tuple[str, ...] = ("Eidesstattliche Erklärung",)


@rule(
    "core.list.consistent",
    summary="The items of a list all end with a period or all end without one.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 34",
            concat(
                "Achten Sie auf einen einheitlichen Stil: Formulieren Sie entweder ganze Sätze ",
                "oder geben Sie die Schritte stichpunktartig wieder.",
            ),
        )
    ],
    params=ListParams(),
)
def list_consistent(ctx: Context, params: ListParams) -> Iterator[Finding]:
    """Report the minority of items when a list mixes sentences and fragments."""
    for items in _checked_lists(ctx, params.excluded_chapters):
        if _is_enumeration(items):
            continue
        flags = [item.ending.endswith(".") for item in items]
        with_period = sum(flags)
        if with_period in {0, len(items)}:
            continue
        minority = with_period * 2 <= len(items)
        state = "ends with a period" if minority else "has no final period"
        yield from (
            Finding(
                concat(
                    f"this list item {state}, but most items of the list do not. ",
                    "End all items in the same way.",
                ),
                item.unit.start_location,
            )
            for item, flag in zip(items, flags, strict=True)
            if flag == minority
        )


@rule(
    "core.list.punctuation",
    summary="Enumerations have commas, 'und'/'sowie'/'oder' before the last item and a period.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 195",
            concat(
                "Aufzählungen sind in der Form vorzunehmen, dass hinter jedem Element der ",
                "Aufzählung ein Komma gesetzt wird. Das vorletzte und letzte Element der ",
                "Aufzählung sind durch und, sowie bzw. oder zu verbinden. Nach dem letzten ",
                "Element der Aufzählung ist ein Punkt zu setzen.",
            ),
        )
    ],
    params=ListParams(),
)
def list_punctuation(ctx: Context, params: ListParams) -> Iterator[Finding]:
    """Report enumeration items with wrong punctuation. Lists of full sentences are exempt."""
    for items in _checked_lists(ctx, params.excluded_chapters):
        if _is_sentence_list(items):
            continue
        yield from (
            Finding(problem, item.unit.location(len(item.ending) - 1, len(item.ending)))
            for index, item in enumerate(items)
            if (problem := _punctuation_problem(item, index, len(items))) is not None
        )


def _punctuation_problem(item: ListItem, index: int, count: int) -> str | None:
    ending = item.ending
    if index == count - 1:
        return None if ending.endswith(".") else "end the last item of the list with a period."
    if index == count - 2:
        if _CONJUNCTION.search(ending) or (item.has_children and ending.endswith(":")):
            return None
        return "connect the last two items with 'und', 'sowie' or 'oder'."
    if ending.endswith(",") or (item.has_children and ending.endswith(":")):
        return None
    return "end this list item with a comma."
