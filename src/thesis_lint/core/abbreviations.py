"""Rules for abbreviations, acronyms and glossary terms.

The project defines acronyms and terms in the glossary file. The text must use
them through the glossary functions, for example `#gls("MDR")`. The glossary
functions insert the key into the unit text, so the rules hide glossary uses
with `masked` before they search for raw forms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

from thesis_lint.core.prose import (
    STYLE_KINDS,
    TEXT_KINDS,
    finding,
    flat,
    masked,
    prose_units,
    unit_sentences,
    word_regex,
)
from thesis_lint.core.sources import HW, LANGE, USER, VORLAGE, ref
from thesis_lint.model import Severity
from thesis_lint.registry import Finding, NoParams, rule

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from thesis_lint.context import Context
    from thesis_lint.project import Acronym, Project, Term


@dataclass(frozen=True, slots=True)
class RawForm:
    """A raw text form of a glossary entry. `kind` is 'short', 'long' or 'term'."""

    key: str
    kind: str
    text: str


@dataclass(frozen=True, slots=True)
class FormIndex:
    """One pattern for many raw forms. Group N of the pattern belongs to `forms[N - 1]`."""

    pattern: re.Pattern[str]
    forms: tuple[RawForm, ...]

    def find(self, text: str) -> Iterator[tuple[re.Match[str], RawForm]]:
        """Yield each match with its form. A longer form wins at the same position."""
        return (
            (match, self.forms[(match.lastindex or 1) - 1]) for match in self.pattern.finditer(text)
        )


_PLURAL = r"(?:s|n|en|e|es)?"


def _long_variants(long: str) -> Iterator[str]:
    """Yield the long form and its part before a parenthesis or a comma."""
    yield long
    yield long.split(" (", 1)[0]
    yield long.split(",", 1)[0]


def _form_regex(form: RawForm) -> str:
    words = form.text.split()
    body = r"\s+".join(re.escape(word) for word in words)
    if form.kind == "short":
        # A short form keeps its case. "LLMs" is the plural of "LLM".
        return rf"(?<!\w)(?-i:{body})s?(?!\w)"
    return rf"(?<!\w){body}{_PLURAL}(?!\w)"


def form_index(forms: Iterable[RawForm]) -> FormIndex:
    """Return a form index. The pattern ignores the case, except for short forms."""
    unique = sorted(
        {(form.kind, form.text): form for form in forms if len(form.text) >= 2}.values(),
        key=lambda form: len(form.text),
        reverse=True,
    )
    body = "|".join(f"({_form_regex(form)})" for form in unique) or "(?!)"
    return FormIndex(re.compile(body, re.IGNORECASE), tuple(unique))


def acronym_forms(acronyms: Iterable[Acronym]) -> Iterator[RawForm]:
    """Yield the short and long forms of the acronyms."""
    for acronym in acronyms:
        yield RawForm(acronym.key, "short", acronym.short)
        yield from (
            RawForm(acronym.key, "long", variant.strip())
            for variant in dict.fromkeys(_long_variants(acronym.long))
            if len(variant.strip()) >= 4
        )


def term_forms(terms: Iterable[Term]) -> Iterator[RawForm]:
    """Yield the name, the plural and the genitive of the terms."""
    return (
        RawForm(term.key, "term", text)
        for term in terms
        for text in dict.fromkeys((term.name, term.plural or "", term.genitive or ""))
        if text
    )


@cache
def _acronym_index(acronyms: tuple[Acronym, ...]) -> FormIndex:
    return form_index(acronym_forms(acronyms))


def acronym_index(project: Project) -> FormIndex:
    """Return the form index of the acronyms of a project."""
    return _acronym_index(tuple(project.acronyms.values()))


_TOKEN = re.compile(r"[^\W_]+")
_ROMAN = re.compile(r"[IVXLCDM]+[ab]?")


@dataclass(frozen=True, slots=True)
class GlossaryParams:
    """Parameters of core.abbrev.glossary."""

    allowed: tuple[str, ...] = (
        "ISO",
        "IEC",
        "IEEE",
        "EN",
        "DIN",
        "VDE",
        "VDI",
        "EU",
        "USA",
        "UK",
        "GmbH",
        "PDF",
        "URL",
        "DOI",
        "ISBN",
        "ISSN",
        "TODO",
        "XXX",
    )
    roman_numerals: bool = True


def is_abbreviation(token: str) -> bool:
    """Return True if a token has two or more capitals and more capitals than small letters."""
    letters = [char for char in token if char.isalpha()]
    capitals = sum(char.isupper() for char in letters)
    return capitals >= 2 and 2 * capitals > len(letters)


def _covered(index: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in spans)


@rule(
    "core.abbrev.glossary",
    summary="An abbreviation in capitals is a glossary acronym.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Abkürzungen",
            "Abkürzungen sind (...) zu benennen und im Abkürzungsverzeichnis aufzuführen.",
        )
    ],
    params=GlossaryParams(),
)
def abbrev_glossary(ctx: Context, params: GlossaryParams) -> Iterator[Finding]:
    """Report abbreviations that are not acronyms of the glossary.

    Raw forms of defined acronyms are the subject of core.abbrev.raw-form, so this
    rule skips them.
    """
    allowed = frozenset(params.allowed)
    index = acronym_index(ctx.project)
    for unit in prose_units(ctx, TEXT_KINDS):
        text = masked(unit)
        defined = [(match.start(), match.end()) for match, _ in index.find(text)]
        for token in _TOKEN.finditer(text):
            word = token.group(0)
            if (
                not is_abbreviation(word)
                or word in allowed
                or (params.roman_numerals and _ROMAN.fullmatch(word))
                or _covered(token.start(), defined)
            ):
                continue
            yield finding(
                unit,
                token.start(),
                token.end(),
                f"abbreviation {word!r} is not in the glossary. Add it and use #gls.",
            )


def _function_for(form: RawForm, matched: str) -> str:
    plural = form.kind != "short" and len(matched) > len(" ".join(form.text.split()))
    plural = plural or (form.kind == "short" and matched.endswith("s") and matched != form.text)
    return "#glspl" if plural else "#gls"


@rule(
    "core.abbrev.raw-form",
    summary="The text uses the glossary function for each acronym, not its raw short or long form.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Abkürzungen",
            "so kann dies später nur noch als MPG bezeichnet werden.",
        ),
        ref(HW, "S. 199", "Abkürzungen durchgängig verwenden"),
    ],
)
def raw_form(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report raw short and long forms of defined acronyms."""
    index = acronym_index(ctx.project)
    for unit in prose_units(ctx, TEXT_KINDS):
        for match, form in index.find(masked(unit)):
            function = _function_for(form, match.group(0))
            shown = flat(match.group(0))
            yield finding(
                unit,
                match.start(),
                match.end(),
                f'raw {form.kind} form {shown!r}. Use {function}("{form.key}").',
            )


@rule(
    "core.abbrev.unused",
    summary="Each glossary term and acronym is used in the text.",
    severity=Severity.ERROR,
    sources=[ref(USER, "Abkürzungen", "Kein ungenutzter Glossar- oder Akronym-Eintrag")],
)
def unused(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report glossary entries that no glossary function uses."""
    project = ctx.project
    source = project.glossary_source
    if source is None:
        return
    units = [*project.document.units, *([project.abstract] if project.abstract else [])]
    used = {use.key for unit in units for use in unit.glossary}
    entries = [
        *(("term", key) for key in project.terms),
        *(("acronym", key) for key in project.acronyms),
    ]
    for kind, key in entries:
        if key in used:
            continue
        found = re.search(rf"[\"']{re.escape(key)}[\"']\s*:", source.text)
        begin = 0 if found is None else len(source.text[: found.start()].encode("utf-8"))
        end = begin if found is None else begin + len(found.group(0).encode("utf-8"))
        yield Finding(
            f"{kind} {key!r} is never used. Use it with #gls or remove it from the glossary.",
            source.location(begin, end),
        )


@dataclass(frozen=True, slots=True)
class SentenceStartParams:
    """Parameters of core.abbrev.sentence-start."""

    abbreviations: tuple[str, ...] = (
        "z.B.",
        "d.h.",
        "u.a.",
        "bzw.",
        "ggf.",
        "bspw.",
        "ca.",
        "usw.",
        "etc.",
        "i.d.R.",
        "u.U.",
        "evtl.",
        "insb.",
        "sog.",
        "z.T.",
    )
    acronyms: bool = True


_LEAD = " „‚\"'("


def _first_uses(ctx: Context) -> set[tuple[int, int]]:
    """Return (unit id, span start) of the first use of each glossary key in the document."""
    seen: dict[str, tuple[int, int]] = {}
    ordered = sorted(
        (
            (unit.order, use.span.start, id(unit), use.key)
            for unit in ctx.project.document.units
            for use in unit.glossary
        ),
    )
    for _, start, unit_id, key in ordered:
        seen.setdefault(key, (unit_id, start))
    return set(seen.values())


@rule(
    "core.abbrev.sentence-start",
    summary="A sentence does not start with an abbreviation.",
    severity=Severity.WARNING,
    sources=[
        ref(USER, "Abkürzungen", "Keine Abkürzung am Satzanfang (Duden)"),
    ],
    params=SentenceStartParams(),
)
def sentence_start(ctx: Context, params: SentenceStartParams) -> Iterator[Finding]:
    """Report sentences that start with an abbreviation or a short acronym.

    The first use of an acronym shows the long form, so it does not count.
    """
    pattern = word_regex(params.abbreviations)
    first = _first_uses(ctx) if params.acronyms else set[tuple[int, int]]()
    acronyms = ctx.project.acronyms
    for unit in prose_units(ctx, STYLE_KINDS):
        for sentence, text in unit_sentences(unit):
            lead = len(text) - len(text.lstrip(_LEAD))
            position = sentence.start + lead
            match = pattern.match(text, lead)
            if match is not None:
                yield finding(
                    unit,
                    position,
                    sentence.start + match.end(),
                    f"the sentence starts with {match.group(0)!r}. Write it in full.",
                )
                continue
            yield from (
                finding(
                    unit,
                    use.span.start,
                    use.span.end,
                    f"the sentence starts with the acronym {use.key!r}. Rephrase the sentence.",
                )
                for use in unit.glossary
                if params.acronyms
                and use.span.start == position
                and use.key in acronyms
                and (id(unit), use.span.start) not in first
            )


@rule(
    "core.glossary.raw-term",
    summary="The text uses the glossary function for each glossary term, not its raw name.",
    severity=Severity.ERROR,
    sources=[
        ref(
            HW,
            "S. 104",
            "Sie dürfen nicht durch alternative Wörter ersetzt werden",
        ),
        ref(
            LANGE,
            "S. 112",
            "zentrale Fachbegriffe beizubehalten und nicht durch Wörter (...) zu ersetzen",
        ),
    ],
)
def raw_term(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report glossary term names, plurals and genitives as raw text."""
    terms = ctx.project.terms
    if not terms:
        return
    index = form_index(term_forms(terms.values()))
    for unit in prose_units(ctx, TEXT_KINDS):
        for match, form in index.find(masked(unit)):
            term = terms[form.key]
            plural = form.text == term.plural and term.plural != term.name
            function = "#glspl" if plural else "#gls"
            shown = flat(match.group(0))
            yield finding(
                unit,
                match.start(),
                match.end(),
                f'raw glossary term {shown!r}. Use {function}("{form.key}").',
            )
