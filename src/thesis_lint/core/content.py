"""Rules for the content of the abstract, the hypothesis, the methods and the results."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from itertools import chain
from typing import TYPE_CHECKING

from thesis_lint.core.abbreviations import GlossaryParams, is_abbreviation
from thesis_lint.core.sources import VL02, ref
from thesis_lint.core.structure import chapter_figures, concat, prose_units
from thesis_lint.model import Severity
from thesis_lint.registry import Finding, rule
from thesis_lint.text import sentences
from thesis_lint.typst.document import PLACEHOLDERS

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from thesis_lint.context import Context
    from thesis_lint.project import Project
    from thesis_lint.typst.document import Heading, Unit

_TOKEN = re.compile(r"[^\W_]+")
_ROMAN = re.compile(r"[IVXLCDM]+[ab]?")
_CONTENT_WORD = re.compile(r"[^\W\d_]+")


# Shared helpers


def _glossary_text(project: Project, key: str) -> str:
    """Return the text that a glossary call shows in full: the term name or the long form."""
    term = project.terms.get(key)
    if term is not None:
        return term.name
    acronym = project.acronyms.get(key)
    return acronym.long if acronym is not None else key


def expanded_text(unit: Unit, project: Project) -> str:
    """Return the unit text with each glossary key replaced by its full text."""
    uses = sorted(unit.glossary, key=lambda use: use.span.start)
    starts = [0, *(use.span.end for use in uses)]
    pieces = (
        unit.text[start : use.span.start] + _glossary_text(project, use.key)
        for start, use in zip(starts, uses, strict=False)
    )
    return "".join(pieces) + unit.text[starts[-1] :]


def _covered(unit: Unit, index: int) -> bool:
    """Return True if `index` is in a quote, a formula, raw text or a glossary call."""
    spans = chain(unit.quotes, unit.maths, unit.raws, (use.span for use in unit.glossary))
    return any(span.start <= index < span.end for span in spans)


def _heading_anywhere(ctx: Context, title: str) -> Heading | None:
    """Return the first heading of any level with this title, or None."""
    return next((h for h in ctx.project.document.headings if h.text == title), None)


def _chapters(ctx: Context, titles: Iterable[str]) -> list[Heading]:
    """Return the level-1 headings with the given titles, in the order of `titles`."""
    return [heading for title in titles if (heading := ctx.heading_by_title(title)) is not None]


@cache
def _compiled(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    """Return the patterns compiled. The match ignores the case."""
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


def _first_match(patterns: tuple[str, ...], text: str) -> re.Match[str] | None:
    return next((m for p in _compiled(patterns) if (m := p.search(text)) is not None), None)


def _plain(text: str) -> str:
    """Return the text without placeholders and without white space at the ends."""
    return "".join(char for char in text if char not in PLACEHOLDERS).strip()


# Abstract rules


@dataclass(frozen=True, slots=True)
class AbstractAbbrevParams:
    """Parameters of `core.abstract.no-abbreviations`."""

    allowed: tuple[str, ...] = GlossaryParams().allowed
    roman_numerals: bool = True


@rule(
    "core.abstract.no-abbreviations",
    summary="The abstract contains no abbreviations and no acronyms of the glossary.",
    severity=Severity.ERROR,
    sources=[ref(VL02, "Folie 60", "Keine Abkürzungen, sofern nicht allgemein bekannt")],
    params=AbstractAbbrevParams(),
)
def abstract_no_abbreviations(ctx: Context, params: AbstractAbbrevParams) -> Iterator[Finding]:
    """Report acronym calls and raw abbreviations in the abstract.

    A glossary call of a term (not of an acronym) is not an abbreviation.
    """
    unit = ctx.project.abstract
    if unit is None:
        return
    acronyms = ctx.project.acronyms
    yield from (
        Finding(
            concat(
                f"the abstract uses the acronym {acronyms[use.key].short!r}. ",
                f"Write the full term {acronyms[use.key].long!r}.",
            ),
            use.location,
        )
        for use in unit.glossary
        if use.key in acronyms
    )
    allowed = frozenset(params.allowed)
    yield from (
        Finding(
            f"the abstract contains the abbreviation {token.group(0)!r}. Write the full term.",
            unit.location(token.start(), token.end()),
        )
        for token in _TOKEN.finditer(unit.text)
        if is_abbreviation(token.group(0))
        and token.group(0) not in allowed
        and not (params.roman_numerals and _ROMAN.fullmatch(token.group(0)))
        and not _covered(unit, token.start())
    )


@dataclass(frozen=True, slots=True)
class PatternsParams:
    """Regular expressions that a rule looks for. The match ignores the case."""

    patterns: tuple[str, ...] = ()


@rule(
    "core.abstract.no-outline",
    summary="The abstract is no outline of the chapters and no story of the work steps.",
    severity=Severity.WARNING,
    sources=[
        ref(
            VL02,
            "Folie 62",
            "Das Abstract ist keine ... Inhaltsangabe ... Beschreibung des zeitlichen Ablaufs",
        )
    ],
    params=PatternsParams(
        patterns=(
            r"\b(?:Kapitel|Abschnitt)\s+\d",
            r"\bgliedert\s+sich\b",
            r"(?-i:\b(?:Zuerst|Zunächst|Erstens)\b[^\n]*?\b(?:Dann|Danach|Anschließend)\b)",
        )
    ),
)
def abstract_no_outline(ctx: Context, params: PatternsParams) -> Iterator[Finding]:
    """Report chapter references and sequences of work steps in the abstract."""
    unit = ctx.project.abstract
    if unit is None:
        return
    yield from (
        Finding(
            concat(
                f"the abstract describes the outline or the work steps ({match.group(0)!r}). ",
                "State the question, the method and the results instead.",
            ),
            unit.location(match.start(), match.end()),
        )
        for pattern in _compiled(params.patterns)
        for match in pattern.finditer(unit.text)
    )


@dataclass(frozen=True, slots=True)
class ElementsParams:
    """Parameters of `core.abstract.elements`.

    Each tuple holds regular expressions that show one element. The match ignores the case.
    """

    hypothesis: tuple[str, ...] = (r"\bHypothese", r"\bThese\b", r"\bvermute[nt]?\b")
    method: tuple[str, ...] = (
        r"\bMethode",
        r"\bLiteraturarbeit",
        r"\bLiteraturrecherche",
        r"\bAnalyse",
        r"\bwerte[nt]?\b[^.!?]*\baus\b",
        r"\buntersuch",
    )
    result: tuple[str, ...] = (
        r"\bErgebnis",
        r"\bzeig(?:t|en)\b",
        r"\bbestätig",
        r"\bwiderleg",
        r"\bkann\b[^.!?]*\bnicht\b",
    )


@rule(
    "core.abstract.elements",
    summary="The abstract names the hypothesis, the method and the result.",
    severity=Severity.WARNING,
    sources=[
        ref(
            VL02,
            "Folie 60",
            "Motivation, Hypothese, Methoden und Ergebnisse müssen erkennbar sein",
        ),
        ref(VL02, "Folie 59", "Verifizierung oder Falsifizierung der Hypothese"),
    ],
    params=ElementsParams(),
)
def abstract_elements(ctx: Context, params: ElementsParams) -> Iterator[Finding]:
    """Report each element that has no signal word in the abstract."""
    unit = ctx.project.abstract
    if unit is None:
        return
    text = expanded_text(unit, ctx.project)
    elements = (
        ("hypothesis", params.hypothesis, "'Die Hypothese lautet ...'"),
        ("method", params.method, "'Die Arbeit wertet ... aus'"),
        ("result", params.result, "'Die Ergebnisse zeigen ...'"),
    )
    yield from (
        Finding(
            f"the abstract does not name the {name}. Add it, for example {example}.",
            unit.start_location,
        )
        for name, patterns, example in elements
        if patterns and _first_match(patterns, text) is None
    )


@dataclass(frozen=True, slots=True)
class OverlapParams:
    """Parameters of `core.abstract.conclusion-overlap`."""

    chapter: str = "Zusammenfassung"
    min_share: float = 0.3
    min_length: int = 5
    stopwords: tuple[str, ...] = (
        "aber",
        "allen",
        "alle",
        "bereits",
        "dabei",
        "daher",
        "damit",
        "deren",
        "dessen",
        "diese",
        "diesem",
        "diesen",
        "dieser",
        "dieses",
        "durch",
        "einem",
        "einen",
        "einer",
        "eines",
        "gegen",
        "haben",
        "ihrer",
        "jedoch",
        "keine",
        "keinen",
        "können",
        "könnte",
        "nicht",
        "seine",
        "seiner",
        "solche",
        "solchen",
        "sowie",
        "unter",
        "welche",
        "werden",
        "wurde",
        "wurden",
        "zudem",
        "zwischen",
    )


def content_words(text: str, min_length: int, stopwords: frozenset[str]) -> frozenset[str]:
    """Return the lowercase words with at least `min_length` letters, without stopwords."""
    return frozenset(
        word
        for match in _CONTENT_WORD.finditer(text)
        if len(word := match.group(0).casefold()) >= min_length and word not in stopwords
    )


@rule(
    "core.abstract.conclusion-overlap",
    summary="The abstract contains the main statements of the conclusion (word overlap).",
    severity=Severity.WARNING,
    sources=[
        ref(
            VL02,
            "Folie 65",
            "Die wichtigsten Aussagen der Conclusion müssen im Abstract enthalten sein",
        )
    ],
    params=OverlapParams(),
)
def abstract_conclusion_overlap(ctx: Context, params: OverlapParams) -> Iterator[Finding]:
    """Report a low share of conclusion content words that also occur in the abstract."""
    unit = ctx.project.abstract
    heading = ctx.heading_by_title(params.chapter)
    if unit is None or heading is None:
        return
    stopwords = frozenset(word.casefold() for word in params.stopwords)
    conclusion = content_words(
        " ".join(expanded_text(u, ctx.project) for u in prose_units(heading.all_units())),
        params.min_length,
        stopwords,
    )
    abstract = content_words(expanded_text(unit, ctx.project), params.min_length, stopwords)
    if not conclusion:
        return
    share = len(conclusion & abstract) / len(conclusion)
    if share < params.min_share:
        yield Finding(
            concat(
                f"the abstract contains only {share:.0%} of the content words of the chapter ",
                f"{params.chapter!r}. Use at least {params.min_share:.0%}. ",
                "Put the main statements of the conclusion into the abstract.",
            ),
            unit.start_location,
        )


# Hypothesis rules


@dataclass(frozen=True, slots=True)
class StatementParams:
    """Parameters of `core.hypothesis.statement`."""

    title: str = "Arbeitshypothese"
    placeholder_pattern: str = r"^\[.*\]$"


@rule(
    "core.hypothesis.statement",
    summary="The working hypothesis is a statement: it ends with a period and has no question.",
    severity=Severity.ERROR,
    sources=[
        ref(VL02, "Folie 26", "Eine Hypothese ist eine überprüfbare Aussage"),
        ref(
            VL02,
            "Folie 28",
            "Die wissenschaftliche Fragestellung wird als Arbeitshypothese formuliert",
        ),
    ],
    params=StatementParams(),
)
def hypothesis_statement(ctx: Context, params: StatementParams) -> Iterator[Finding]:
    """Report question marks in the hypothesis section and a text without a final period."""
    heading = _heading_anywhere(ctx, params.title)
    if heading is None:
        return
    units = list(prose_units(heading.all_units()))
    text = _plain(" ".join(unit.text for unit in units))
    if not text or re.fullmatch(params.placeholder_pattern, text, re.DOTALL):
        return
    yield from (
        Finding(
            concat(
                "the hypothesis contains a question mark. ",
                "Write the hypothesis as a statement that the work can test.",
            ),
            unit.location(index, index + 1),
        )
        for unit in units
        for index, char in enumerate(unit.text)
        if char == "?" and not unit.is_quoted(index)
    )
    if not text.endswith("."):
        last = units[-1]
        end = len(last.text.rstrip())
        yield Finding(
            "the hypothesis does not end with a period. Write it as a full statement.",
            last.location(max(end - 1, 0), end),
        )


@dataclass(frozen=True, slots=True)
class VerdictParams:
    """Parameters of `core.hypothesis.verdict`.

    `subject` is a regular expression for the hypothesis. `verbs` are whole words.
    The match ignores the case.
    """

    chapters: tuple[str, ...] = ("Diskussion", "Zusammenfassung")
    subject: str = r"hypothese"
    verbs: tuple[str, ...] = (
        "bestätigt",
        "widerlegt",
        "verifiziert",
        "falsifiziert",
        "stützen",
        "stützt",
        "angenommen",
        "verworfen",
        "abgelehnt",
    )


@rule(
    "core.hypothesis.verdict",
    summary="The discussion or the conclusion says if the hypothesis is confirmed or rejected.",
    severity=Severity.WARNING,
    sources=[
        ref(VL02, "Folie 59", "Verifizierung oder Falsifizierung der Hypothese"),
        ref(VL02, "Folie 74", "Wie sind die Ergebnisse aus Sicht des Autors zu bewerten?"),
    ],
    params=VerdictParams(),
)
def hypothesis_verdict(ctx: Context, params: VerdictParams) -> Iterator[Finding]:
    """Report when no sentence in the chapters has the hypothesis and a verdict verb."""
    chapters = _chapters(ctx, params.chapters)
    if not chapters or not params.verbs:
        return
    subject = re.compile(params.subject, re.IGNORECASE)
    verbs = re.compile(
        rf"(?<!\w)(?:{'|'.join(re.escape(verb) for verb in params.verbs)})(?!\w)", re.IGNORECASE
    )
    found = any(
        subject.search(sentence.text) and verbs.search(sentence.text)
        for heading in chapters
        for unit in prose_units(heading.all_units())
        for sentence in sentences(unit)
    )
    if not found:
        names = " or ".join(repr(heading.text) for heading in chapters)
        yield Finding(
            concat(
                f"the chapter {names} does not say if the hypothesis is confirmed. ",
                "Add a sentence like 'Die Ergebnisse bestätigen die Hypothese'.",
            ),
            chapters[0].location,
        )


# Methods rules


@dataclass(frozen=True, slots=True)
class LiteratureSearchParams:
    """Parameters of `core.methods.literature-search`.

    `systems` are names that must start a word. The other lists are regular
    expressions. Each match ignores the case.
    """

    chapter: str = "Methoden"
    systems: tuple[str, ...] = (
        "EDDI",
        "Nautos",
        "PubMed",
        "IEEE Xplore",
        "Google Scholar",
        "ScienceDirect",
        "Cochrane",
        "Scopus",
        "Web of Science",
        "arXiv",
        "Consensus",
        "KVK",
        "Springer",
    )
    search_terms: tuple[str, ...] = (r"Suchbegriff", r"Suchstring", r"Schlagw(?:o|ö)rt")
    period: tuple[str, ...] = (r"\b(?:19|20)\d{2}\b", r"Zeitraum")
    criteria: tuple[str, ...] = (r"Kriteri", r"Einschluss", r"Ausschluss")


@rule(
    "core.methods.literature-search",
    summary="The methods name the search systems, search terms, period and selection criteria.",
    severity=Severity.WARNING,
    sources=[
        ref(
            VL02,
            "Folie 71",
            "Wann, wo, in welchem Kontext und über welchen Zeitraum wurden die Daten erhoben?",
        ),
        ref(
            VL02,
            "Folie 72",
            "Gut: Angabe wo und wie gesucht wurde",
        ),
    ],
    params=LiteratureSearchParams(),
)
def methods_literature_search(ctx: Context, params: LiteratureSearchParams) -> Iterator[Finding]:
    """Report each part of the literature search that the methods chapter does not name."""
    heading = ctx.heading_by_title(params.chapter)
    if heading is None:
        return
    text = " ".join(expanded_text(unit, ctx.project) for unit in heading.all_units())
    systems = tuple(rf"(?<!\w){re.escape(name)}" for name in params.systems)
    parts = (
        ("the search systems", systems, "for example 'PubMed' or 'IEEE Xplore'"),
        ("the search terms", params.search_terms, "for example 'Suchbegriffe: ...'"),
        ("the period of the search", params.period, "for example 'von 2015 bis 2025'"),
        ("the selection criteria", params.criteria, "for example 'Einschlusskriterien: ...'"),
    )
    yield from (
        Finding(
            f"the chapter {params.chapter!r} does not name {name}. Add them, {example}.",
            heading.location,
        )
        for name, patterns, example in parts
        if patterns and _first_match(patterns, text) is None
    )


# Results rules


@dataclass(frozen=True, slots=True)
class ResultsParams:
    """Parameters of `core.results.has-figure`."""

    chapter: str = "Ergebnisse"


@rule(
    "core.results.has-figure",
    summary="The results chapter shows the results in at least one figure or table.",
    severity=Severity.WARNING,
    sources=[
        ref(
            VL02,
            "Folie 73",
            "nicht geeignet: Beschreibung der Daten in verbaler Form",
        )
    ],
    params=ResultsParams(),
)
def results_has_figure(ctx: Context, params: ResultsParams) -> Iterator[Finding]:
    """Report a results chapter without a figure, a table or an image."""
    heading = ctx.heading_by_title(params.chapter)
    if heading is None:
        return
    if next(chapter_figures(ctx.project.document, (params.chapter,)), None) is None:
        yield Finding(
            concat(
                f"the chapter {params.chapter!r} has no figure and no table. ",
                "Summarize the results in a table or a diagram.",
            ),
            heading.location,
        )


@dataclass(frozen=True, slots=True)
class NotInDiscussionParams:
    """Parameters of `core.results.not-in-discussion`."""

    chapters: tuple[str, ...] = ("Diskussion", "Zusammenfassung")


@rule(
    "core.results.not-in-discussion",
    summary="The discussion and the conclusion contain no figures and no tables.",
    severity=Severity.WARNING,
    sources=[
        ref(
            VL02,
            "Folie 104",
            concat(
                "Ergebnisse werden im Diskussionsteil, der Zusammenfassung oder dem Ausblick ",
                "erstmals präsentiert",
            ),
        )
    ],
    params=NotInDiscussionParams(),
)
def results_not_in_discussion(ctx: Context, params: NotInDiscussionParams) -> Iterator[Finding]:
    """Report figures, tables and images in the discussion and the conclusion."""
    return (
        Finding(
            concat(
                "this figure or table is in the discussion or the conclusion. ",
                "Show the results in the results chapter and refer to them there.",
            ),
            source.node_location(node),
        )
        for source, node in chapter_figures(ctx.project.document, params.chapters)
    )
