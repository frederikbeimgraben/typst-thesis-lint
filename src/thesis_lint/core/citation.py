"""Rules for citation: quotations, citation keys and phrases that need a source."""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import chain, pairwise
from typing import TYPE_CHECKING

from thesis_lint.core.sources import BRINK, DFG, HW, LANGE, USER, ref
from thesis_lint.model import Location, Severity
from thesis_lint.registry import Finding, NoParams, rule
from thesis_lint.text import sentences, word_count, words
from thesis_lint.typst.document import Reference, Span, Unit, UnitKind, content_unit
from thesis_lint.typst.parse import call_name, named_arg, walk

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from thesis_lint.context import Context
    from thesis_lint.text import Sentence

# Level-1 chapters that the citation rules do not check.
EXCLUDED_TITLES = frozenset({"Eidesstattliche Erklärung"})
_DOUBLE_OPEN = frozenset('„»"“')


@dataclass(frozen=True, slots=True)
class Quotation:
    """A literal quotation: an inline span in double quotes or a whole block quote."""

    unit: Unit
    span: Span
    block: bool

    @property
    def text(self) -> str:
        """Return the quoted text without the quote characters."""
        raw = self.unit.text[self.span.start : self.span.end]
        return raw if self.block else raw[1:-1]

    @property
    def location(self) -> Location:
        """Return the source location of the quotation."""
        return self.unit.location(self.span.start, self.span.end)


def body_units(ctx: Context) -> Iterator[Unit]:
    """Yield the prose units outside the excluded chapters."""
    return ctx.body_units(EXCLUDED_TITLES)


def quotations(unit: Unit) -> list[Quotation]:
    """Return the literal quotations of a unit. A block quote is one quotation."""
    if unit.kind is UnitKind.QUOTE_BLOCK:
        return [Quotation(unit, Span(0, len(unit.text)), block=True)]
    spans = sorted(
        {span for span in unit.quotes if span.end > span.start},
        key=lambda span: (span.start, -span.end),
    )
    outer = [
        span
        for span in spans
        if unit.text[span.start] in _DOUBLE_OPEN
        and not any(o.start <= span.start and span.end <= o.end and o != span for o in spans)
    ]
    return [Quotation(unit, span, block=False) for span in outer]


def all_quotations(ctx: Context) -> Iterator[Quotation]:
    """Yield the quotations of all body units."""
    return chain.from_iterable(quotations(unit) for unit in body_units(ctx))


def unquoted(unit: Unit, start: int = 0, end: int | None = None) -> str:
    """Return the text of a range. Quoted characters become spaces."""
    stop = len(unit.text) if end is None else end
    return "".join(
        " " if unit.is_quoted(index) else unit.text[index] for index in range(start, stop)
    )


def sentence_range(unit: Unit, span: Span) -> tuple[int, int]:
    """Return the range of the sentences that overlap `span`."""
    touched = [
        sentence
        for sentence in sentences(unit)
        if sentence.start < max(span.end, span.start + 1) and span.start < sentence.end
    ]
    if not touched:
        return span.start, span.end
    return min(s.start for s in touched), max(span.end, *(s.end for s in touched))


def citations(ctx: Context, unit: Unit, start: int = 0, end: int | None = None) -> list[Reference]:
    """Return the citations in a range of a unit, with the citations of its footnotes."""
    stop = len(unit.text) if end is None else end
    direct = (
        reference
        for reference in unit.references
        if start <= reference.span.start < stop and ctx.project.is_citation(reference.key)
    )
    in_footnotes = (
        reference
        for span, footnote in unit.footnotes
        if start <= span.start < stop
        for reference in footnote.references
        if ctx.project.is_citation(reference.key)
    )
    return [*direct, *in_footnotes]


def sentence_citations(ctx: Context, sentence: Sentence) -> list[Reference]:
    """Return the citations of a sentence."""
    return citations(ctx, sentence.unit, sentence.start, sentence.end)


def _attribution(unit: Unit) -> Unit | None:
    """Return the `attribution` of the `#quote(block: true)` call of a block quote unit."""
    source = unit.source
    first = unit.byte_at(0)
    node = next(
        (
            node
            for node in walk(source.root)
            if node.type == "call"
            and call_name(node, source) == "quote"
            and node.start_byte <= first < node.end_byte
        ),
        None,
    )
    if node is None:
        return None
    attribution = named_arg(node, "attribution", source)
    return None if attribution is None else content_unit(source, attribution)


def quotation_citations(ctx: Context, quotation: Quotation) -> list[Reference]:
    """Return the citations that belong to a quotation."""
    unit = quotation.unit
    if quotation.block:
        attribution = _attribution(unit)
        extra = [] if attribution is None else citations(ctx, attribution)
        return [*citations(ctx, unit), *extra]
    start, end = sentence_range(unit, quotation.span)
    return citations(ctx, unit, start, end)


def _quotation_has_footnote(quotation: Quotation) -> bool:
    unit = quotation.unit
    start, end = (0, len(unit.text)) if quotation.block else sentence_range(unit, quotation.span)
    return any(start <= span.start < end for span, _ in unit.footnotes)


def _supplements(ctx: Context) -> Iterator[tuple[str, Location]]:
    return (
        (reference.supplement, reference.location)
        for unit in body_units(ctx)
        for reference in unit.references
        if reference.supplement
    )


def _pattern_findings(
    ctx: Context, pattern: re.Pattern[str], message: str, *, supplements: bool = True
) -> Iterator[Finding]:
    """Yield a finding for each match in unquoted text and, optionally, in supplements."""
    in_text = (
        Finding(message.format(match=match.group(0)), unit.location(match.start(), match.end()))
        for unit in body_units(ctx)
        for match in pattern.finditer(unquoted(unit))
    )
    in_supplements = (
        Finding(message.format(match=match.group(0)), location)
        for text, location in (_supplements(ctx) if supplements else ())
        for match in pattern.finditer(text)
    )
    return chain(in_text, in_supplements)


def _phrase_pattern(phrases: Iterable[str]) -> re.Pattern[str]:
    alternatives = "|".join(
        re.escape(phrase).replace(r"\ ", r"\s+")
        for phrase in sorted(phrases, key=len, reverse=True)
    )
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


# --- core.cite.quote-needs-key --------------------------------------------------------


@rule(
    "core.cite.quote-needs-key",
    summary="Each text in double quotes is a quotation with a citation in the same sentence.",
    severity=Severity.ERROR,
    sources=[
        ref(LANGE, "S. 128"),
        ref(HW, "S. 145, 206"),
    ],
)
def quote_needs_key(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report quotations without a citation."""
    yield from (
        Finding(
            "the quotation has no citation in its sentence. Add @key[S. n] or remove the quotes.",
            quotation.location,
        )
        for quotation in all_quotations(ctx)
        if not quotation_citations(ctx, quotation)
    )


# --- core.cite.quote-page -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QuotePageParams:
    """Parameters of `core.cite.quote-page`. The pattern finds a page in a supplement."""

    page_pattern: str = r"S\.\s*\d|p\.\s*\d|pp\.|\d"


@rule(
    "core.cite.quote-page",
    summary="The citation of a quotation gives the page.",
    severity=Severity.ERROR,
    sources=[ref(LANGE, "S. 128 f.")],
    params=QuotePageParams(),
)
def quote_page(ctx: Context, params: QuotePageParams) -> Iterator[Finding]:
    """Report quotations whose citations give no page."""
    pattern = re.compile(params.page_pattern)
    for quotation in all_quotations(ctx):
        found = quotation_citations(ctx, quotation)
        if found and not any(pattern.search(r.supplement or "") for r in found):
            yield Finding(
                " ".join(
                    (
                        f"the citation @{found[0].key} of a quotation gives no page.",
                        f"Add it, for example @{found[0].key}[S. 12].",
                    )
                ),
                found[0].location,
            )


# --- core.cite.ellipsis ---------------------------------------------------------------

_ELLIPSIS = re.compile(r"\[\s*(?:…|\.\.\.)\s*\]|\(\s*(?:…|\.\.\.)\s*\)|…|\.\.\.")
_BRACKETED = re.compile(r"\[\s*(?:…|\.\.\.)\s*\]")


def ellipsis_problems(text: str) -> Iterator[str]:
    """Yield the problems with omissions in a quoted text."""
    stripped = text.strip()
    for match in _ELLIPSIS.finditer(text):
        token = match.group(0)
        if not _BRACKETED.fullmatch(token):
            yield f"the omission {token!r} is not in square brackets. Write [...]."
        elif stripped.startswith(token) or stripped.endswith(token):
            yield "the quotation starts or ends with an omission. Remove the omission."


@rule(
    "core.cite.ellipsis",
    summary="An omission in a quotation is written [...] and not at its start or end.",
    severity=Severity.ERROR,
    sources=[
        ref(LANGE, "S. 100", "Auslassungen durch drei Punkte gekennzeichnet"),
        ref(HW, "S. 145", "(Einfügungen oder Auslassungen) sind mit eckigen Klammern"),
        ref(BRINK, "S. 227", "dass durch die Auslassung keine Verfälschung der Aussage eintritt"),
    ],
)
def ellipsis(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report omissions in round brackets, bare omissions and omissions at the ends."""
    yield from (
        Finding(problem, quotation.location)
        for quotation in all_quotations(ctx)
        for problem in ellipsis_problems(quotation.text)
    )


# --- core.cite.abstract ---------------------------------------------------------------


@rule(
    "core.cite.abstract",
    summary="The abstract has no citations.",
    severity=Severity.ERROR,
    sources=[ref(HW, "S. 110"), ref(BRINK, "S. 214")],
)
def abstract(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report citations in the abstract."""
    unit = ctx.project.abstract
    if unit is None:
        return
    yield from (
        Finding(
            f"the abstract cites @{reference.key}. Remove the citation from the abstract.",
            reference.location,
        )
        for reference in unit.references
        if ctx.project.is_citation(reference.key)
    )


# --- core.cite.consensus --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConsensusParams:
    """Parameters of `core.cite.consensus`."""

    phrases: tuple[str, ...] = (
        "in der Literatur",
        "in der Forschung",
        "herrschende Meinung",
        "h. M.",
        "h.M.",
        "allgemein anerkannt",
        "weitgehend anerkannt",
        "Konsens",
        "einhellig",
        "Einigkeit",
        "die meisten Autoren",
        "viele Autoren",
        "zahlreiche Autoren",
        "zahlreiche Studien",
        "mehrere Studien",
        "mehrere Autoren",
    )
    min_keys: int = 2


@rule(
    "core.cite.consensus",
    summary="A sentence that claims a consensus cites at least two sources.",
    severity=Severity.ERROR,
    sources=[ref(BRINK, "S. 230")],
    params=ConsensusParams(),
)
def consensus(ctx: Context, params: ConsensusParams) -> Iterator[Finding]:
    """Report consensus phrases with too few cited keys in the sentence."""
    pattern = _phrase_pattern(params.phrases)
    for unit in body_units(ctx):
        text = unquoted(unit)
        for sentence in sentences(unit):
            match = pattern.search(text, sentence.start, sentence.end)
            keys = {r.key for r in sentence_citations(ctx, sentence)}
            if match is not None and len(keys) < params.min_keys:
                yield Finding(
                    " ".join(
                        (
                            f"{match.group(0)!r} claims a consensus, but the sentence cites",
                            f"{len(keys)} source(s). Cite at least {params.min_keys}.",
                        )
                    ),
                    unit.location(match.start(), match.end()),
                )


# --- core.cite.statistics -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatisticsParams:
    """Parameters of `core.cite.statistics`. The pattern finds statistical data."""

    pattern: str = (
        r"\d[\d.,]*\s*(?:%|Prozent)|\bProzentpunkt|\bStatistik(?:en)?\b"
        r"|\bstatistisch\w*\s+(?:belegt|signifikant|erhoben|nachgewiesen)"
    )


@rule(
    "core.cite.statistics",
    summary="A sentence with percentages or statistics cites a source.",
    severity=Severity.ERROR,
    sources=[ref(BRINK, "S. 221")],
    params=StatisticsParams(),
)
def statistics(ctx: Context, params: StatisticsParams) -> Iterator[Finding]:
    """Report sentences with statistical data and without a citation."""
    pattern = re.compile(params.pattern)
    for unit in body_units(ctx):
        text = unquoted(unit)
        for sentence in sentences(unit):
            match = pattern.search(text, sentence.start, sentence.end)
            if match is not None and not sentence_citations(ctx, sentence):
                yield Finding(
                    " ".join(
                        (
                            f"the sentence gives statistical data ({match.group(0)!r})",
                            "but cites no source. Add a citation.",
                        )
                    ),
                    unit.location(match.start(), match.end()),
                )


# --- core.cite.laut-subjunctive -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LautSubjunctiveParams:
    """Parameters of `core.cite.laut-subjunctive`."""

    marker_pattern: str = r"^\W*(?:Laut|Nach)\s|\blaut\s"
    verbs: tuple[str, ...] = ("sei", "seien", "habe", "könne", "werde", "müsse")


@rule(
    "core.cite.laut-subjunctive",
    summary="A sentence with 'laut' or 'nach' uses the indicative, not the subjunctive.",
    severity=Severity.ERROR,
    sources=[ref(LANGE, "S. 124", "Wiedergabefloskeln")],
    params=LautSubjunctiveParams(),
)
def laut_subjunctive(ctx: Context, params: LautSubjunctiveParams) -> Iterator[Finding]:
    """Report subjunctive verbs after `laut X` or `nach X`."""
    marker = re.compile(params.marker_pattern)
    verb = _phrase_pattern(params.verbs)
    for unit in body_units(ctx):
        text = unquoted(unit)
        for sentence in sentences(unit):
            found = marker.search(text[sentence.start : sentence.end])
            if found is None:
                continue
            match = verb.search(text, sentence.start + found.end(), sentence.end)
            if match is not None:
                yield Finding(
                    " ".join(
                        (
                            f"{found.group(0).strip()!r} marks the source already.",
                            f"Use the indicative instead of {match.group(0)!r}.",
                        )
                    ),
                    unit.location(match.start(), match.end()),
                )


# --- core.cite.ibid -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IbidParams:
    """Parameters of `core.cite.ibid`."""

    pattern: str = r"(?i)(?<!\w)(?:ebd\.|ebenda\b|a\.\s?a\.\s?O\.|derselbe\b)"


@rule(
    "core.cite.ibid",
    summary="Citations do not use 'ebd.', 'ebenda', 'a.a.O.' or 'derselbe'.",
    severity=Severity.ERROR,
    sources=[ref(BRINK, "S. 225")],
    params=IbidParams(),
)
def ibid(ctx: Context, params: IbidParams) -> Iterator[Finding]:
    """Report short references to an earlier citation."""
    yield from _pattern_findings(
        ctx,
        re.compile(params.pattern),
        "do not use {match!r}. Cite the source again with its key.",
    )


# --- core.cite.ff ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FfParams:
    """Parameters of `core.cite.ff`."""

    pattern: str = r"(?<![^\W\d_])ff\."


@rule(
    "core.cite.ff",
    summary="Citations give exact page ranges and do not use 'ff.'.",
    severity=Severity.ERROR,
    sources=[ref(BRINK, "S. 222 f.", 'darauf folgenden Kürzel "ff." (fortfolgende)')],
    params=FfParams(),
)
def ff(ctx: Context, params: FfParams) -> Iterator[Finding]:
    """Report `ff.` in text and supplements."""
    yield from _pattern_findings(
        ctx, re.compile(params.pattern), "do not use 'ff.'. Give the exact page range."
    )


# --- core.cite.quote-share ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QuoteShareParams:
    """Parameters of `core.cite.quote-share`."""

    max_share: float = 0.10


@rule(
    "core.cite.quote-share",
    summary="At most 10 % of the words are literal quotations.",
    severity=Severity.WARNING,
    sources=[
        ref(HW, "S. 145"),
        ref(LANGE, "S. 101"),
        ref(BRINK, "S. 228"),
    ],
    params=QuoteShareParams(),
)
def quote_share(ctx: Context, params: QuoteShareParams) -> Iterator[Finding]:
    """Report a document with too many quoted words."""
    units = list(body_units(ctx))
    total = sum(word_count(unit.text) for unit in units)
    found = [q for unit in units for q in quotations(unit)]
    quoted = sum(word_count(q.text) for q in found)
    if total and found and quoted / total > params.max_share:
        yield Finding(
            " ".join(
                (
                    f"{quoted / total:.0%} of the words are literal quotations",
                    f"(maximum {params.max_share:.0%}). Paraphrase some quotations.",
                )
            ),
            found[0].location,
        )


# --- core.cite.cluster ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClusterParams:
    """Parameters of `core.cite.cluster`."""

    max_keys: int = 4


_CLUSTER_GAP = re.compile(r"[\s,;]*")


def clusters(ctx: Context, unit: Unit) -> list[list[Reference]]:
    """Return the groups of adjacent citations in a unit."""
    cites = sorted(
        (r for r in unit.references if ctx.project.is_citation(r.key)),
        key=lambda r: r.span.start,
    )
    groups: list[list[Reference]] = [[c] for c in cites[:1]]
    for previous, current in pairwise(cites):
        gap = unit.text[previous.span.end : current.span.start]
        if _CLUSTER_GAP.fullmatch(gap):
            groups[-1].append(current)
        else:
            groups.append([current])
    return groups


@rule(
    "core.cite.cluster",
    summary="A group of adjacent citations has at most four keys.",
    severity=Severity.WARNING,
    sources=[ref(LANGE, "S. 103")],
    params=ClusterParams(),
)
def cluster(ctx: Context, params: ClusterParams) -> Iterator[Finding]:
    """Report citation groups with too many keys."""
    yield from (
        Finding(
            " ".join(
                (
                    f"{len(group)} citations in one group (maximum {params.max_keys}).",
                    "Cite only the most important sources.",
                )
            ),
            group[0].location,
        )
        for unit in body_units(ctx)
        for group in clusters(ctx, unit)
        if len(group) > params.max_keys
    )


# --- core.cite.block-quote ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BlockQuoteParams:
    """Parameters of `core.cite.block-quote`."""

    max_words: int = 40


@rule(
    "core.cite.block-quote",
    summary="A quotation with more than 40 words is a block quote.",
    severity=Severity.ERROR,
    sources=[ref(USER, "APA 6th edition, block quotation")],
    params=BlockQuoteParams(),
)
def block_quote(ctx: Context, params: BlockQuoteParams) -> Iterator[Finding]:
    """Report long inline quotations."""
    yield from (
        Finding(
            " ".join(
                (
                    f"the quotation has {count} words (more than {params.max_words}).",
                    "Use #quote(block: true)[...].",
                )
            ),
            quotation.location,
        )
        for quotation in all_quotations(ctx)
        if not quotation.block and (count := word_count(quotation.text)) > params.max_words
    )


# --- core.cite.secondary --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SecondaryParams:
    """Parameters of `core.cite.secondary`."""

    pattern: str = r"(?i)\bzit(?:\.|iert)\s*nach\b"


@rule(
    "core.cite.secondary",
    summary="Citations do not use secondary sources ('zitiert nach').",
    severity=Severity.WARNING,
    sources=[
        ref(HW, "S. 145", "zit. nach Ebel 2006, 34"),
        ref(BRINK, "S. 230", "[zitiert nach"),
    ],
    params=SecondaryParams(),
)
def secondary(ctx: Context, params: SecondaryParams) -> Iterator[Finding]:
    """Report secondary citations."""
    yield from _pattern_findings(
        ctx,
        re.compile(params.pattern),
        "{match!r} marks a secondary citation. Read and cite the original source.",
    )


# --- core.cite.reporting-unsourced ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReportingParams:
    """Parameters of `core.cite.reporting-unsourced`. `signals` are reporting phrases."""

    signals: tuple[str, ...] = (
        "laut",
        "zufolge",
        "nach Ansicht",
        "nach Auffassung",
        "nach Meinung",
        "betont",
        "betonen",
        "argumentiert",
        "argumentieren",
        "stellt fest",
        "stellen fest",
        "weist darauf hin",
        "weisen darauf hin",
        "behauptet",
        "behaupten",
        "vertritt die Auffassung",
        "vertreten die Auffassung",
        "kritisiert",
        "kritisieren",
        "konstatiert",
        "konstatieren",
        "postuliert",
        "postulieren",
        "hebt hervor",
        "heben hervor",
    )


@rule(
    "core.cite.reporting-unsourced",
    summary="A paragraph that reports the view of others cites a source.",
    severity=Severity.WARNING,
    sources=[ref(LANGE, "S. 125", "Wiedergabefloskeln")],
    params=ReportingParams(),
)
def reporting_unsourced(ctx: Context, params: ReportingParams) -> Iterator[Finding]:
    """Report paragraphs with a reporting phrase and without a citation."""
    pattern = _phrase_pattern(params.signals)
    for unit in body_units(ctx):
        if unit.kind is UnitKind.FOOTNOTE or citations(ctx, unit):
            continue
        match = pattern.search(unquoted(unit))
        if match is not None:
            yield Finding(
                " ".join(
                    (
                        f"{match.group(0)!r} reports the view of others, but the paragraph",
                        "cites no source. Add a citation.",
                    )
                ),
                unit.location(match.start(), match.end()),
            )


# --- core.cite.foreign-quote ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ForeignQuoteParams:
    """Parameters of `core.cite.foreign-quote`.

    A quotation is English if it has at least `min_words` words and the share of
    `stopwords` is at least `min_share`.
    """

    stopwords: tuple[str, ...] = (
        "the",
        "and",
        "of",
        "is",
        "are",
        "to",
        "in",
        "for",
        "with",
        "that",
        "this",
        "it",
        "be",
        "on",
        "as",
        "by",
        "or",
        "not",
        "can",
        "was",
        "were",
        "which",
        "a",
        "an",
    )
    min_share: float = 0.2
    min_words: int = 4


def is_english(text: str, params: ForeignQuoteParams) -> bool:
    """Return True if the text looks English."""
    found = [word.lower() for word in words(text)]
    stopwords = frozenset(params.stopwords)
    return (
        len(found) >= params.min_words
        and sum(word in stopwords for word in found) / len(found) >= params.min_share
    )


@rule(
    "core.cite.foreign-quote",
    summary="An English quotation has a translation in a footnote.",
    severity=Severity.ERROR,
    sources=[ref(BRINK, "S. 228")],
    params=ForeignQuoteParams(),
)
def foreign_quote(ctx: Context, params: ForeignQuoteParams) -> Iterator[Finding]:
    """Report English quotations without a footnote in the same sentence."""
    yield from (
        Finding(
            "the quotation is in English. Add a German translation in a footnote.",
            quotation.location,
        )
        for quotation in all_quotations(ctx)
        if is_english(quotation.text, params) and not _quotation_has_footnote(quotation)
    )


# --- core.cite.software ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SoftwareParams:
    """Parameters of `core.cite.software`. The project config gives the terms."""

    terms: tuple[str, ...] = ()


@rule(
    "core.cite.software",
    summary="A sentence that names software or a data set from the config cites it.",
    severity=Severity.WARNING,
    sources=[ref(DFG, "Leitlinie 7")],
    params=SoftwareParams(),
)
def software(ctx: Context, params: SoftwareParams) -> Iterator[Finding]:
    """Report sentences with a configured term and without a citation."""
    if not params.terms:
        return
    alternatives = "|".join(map(re.escape, sorted(params.terms, key=len, reverse=True)))
    pattern = re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)")
    for unit in body_units(ctx):
        text = unquoted(unit)
        for sentence in sentences(unit):
            match = pattern.search(text, sentence.start, sentence.end)
            if match is not None and not sentence_citations(ctx, sentence):
                yield Finding(
                    " ".join(
                        (
                            f"the sentence names {match.group(0)!r} but cites no source for it.",
                            "Add a citation.",
                        )
                    ),
                    unit.location(match.start(), match.end()),
                )
