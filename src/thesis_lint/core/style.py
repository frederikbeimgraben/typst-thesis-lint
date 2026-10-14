"""Rules for style and language.

The rules read only the prose that `thesis_lint.core.prose` selects. They do not
read quotations, code, math or the declaration of authorship. Most rules are
heuristics for German text, so most of them report warnings.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from itertools import chain, groupby
from typing import TYPE_CHECKING

from thesis_lint.bib import clean
from thesis_lint.context import top_heading
from thesis_lint.core import spelling as spellcheck
from thesis_lint.core.abbreviations import is_abbreviation
from thesis_lint.core.prose import (
    TEXT_KINDS,
    any_regex,
    finding,
    flat,
    hits,
    masked,
    match_findings,
    prose_units,
    unit_sentences,
    word_regex,
    words,
)
from thesis_lint.core.sources import BRINK, FACTSHEET, HW, LANGE, USER, VL02, VORLAGE, ref
from thesis_lint.core.spelling import SpellCheckUnavailableError
from thesis_lint.model import Location, Severity
from thesis_lint.registry import Finding, NoParams, rule
from thesis_lint.text import sentences
from thesis_lint.typst.document import PLACEHOLDERS, UnitKind
from thesis_lint.typst.parse import read_text

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from thesis_lint.context import Context
    from thesis_lint.text import Sentence
    from thesis_lint.typst.document import Unit


@dataclass(frozen=True, slots=True)
class WordList:
    """A list of words or phrases. See `thesis_lint.core.prose` for the entry syntax."""

    words: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PatternList:
    """A list of regular expressions. The match ignores the case."""

    patterns: tuple[str, ...]


def _word_rule(ctx: Context, entries: tuple[str, ...], message: str) -> Iterator[Finding]:
    """Report each word of `entries` in the prose. `{match}` in `message` is the word."""
    return match_findings(hits(ctx, word_regex(entries)), message)


# Personal style

_NO_PERSPECTIVE = "Sachverhalte werden nicht aus der Ich- oder Wir-Perspektive beschrieben!"


@rule(
    "core.style.first-person",
    summary="The text does not use the first person singular.",
    severity=Severity.ERROR,
    sources=[
        ref(VL02, "Folie 89", _NO_PERSPECTIVE),
        ref(
            HW,
            "S. 103",
            "Subjektive Ansichten, wie sie das Personalpronomen ich (...) signalisieren",
        ),
        ref(BRINK, "S. 197 f.", "sei allen Prüflingen geraten, die Ich-Form zu vermeiden"),
    ],
    params=WordList(
        words=(
            "ich",
            "mich",
            "mir",
            "mein",
            "meine",
            "meiner",
            "meinem",
            "meinen",
            "meines",
            "m. E.",
        )
    ),
)
def first_person(ctx: Context, params: WordList) -> Iterator[Finding]:
    """Report the first person singular."""
    return _word_rule(ctx, params.words, "first person {match!r}. Use an impersonal sentence.")


@rule(
    "core.style.we",
    summary="The text does not use the first person plural.",
    severity=Severity.ERROR,
    sources=[
        ref(VL02, "Folie 89", _NO_PERSPECTIVE),
        ref(
            HW,
            "S. 103",
            "den Leser durch die erste Person Plural (wir) in den Text einzubeziehen",
        ),
    ],
    params=WordList(
        words=("wir", "uns", "unser", "unsere", "unserer", "unserem", "unseren", "unseres")
    ),
)
def we(ctx: Context, params: WordList) -> Iterator[Finding]:
    """Report the first person plural."""
    return _word_rule(
        ctx, params.words, "first person plural {match!r}. Use an impersonal sentence."
    )


@rule(
    "core.style.man",
    summary="The text does not use the pronoun 'man'.",
    severity=Severity.WARNING,
    sources=[ref(HW, "S. 103", "Auch das unpersönliche Pronomen man stellt keine Alternative dar")],
    params=WordList(words=("man",)),
)
def man(ctx: Context, params: WordList) -> Iterator[Finding]:
    """Report the pronoun 'man'."""
    return _word_rule(
        ctx, params.words, "pronoun {match!r}. Name the actor or use a sentence without it."
    )


@rule(
    "core.style.reader-address",
    summary="The text does not address the reader and does not ask rhetorical questions.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 103",
            "oder durch rhetorische Fragen indirekt anzusprechen",
        )
    ],
    params=WordList(words=("Sie", "Ihnen", "Ihr", "Ihre", "Ihrem", "Ihren", "Ihrer", "Ihres")),
)
def reader_address(ctx: Context, params: WordList) -> Iterator[Finding]:
    """Report questions and the polite address inside a sentence."""
    pattern = word_regex(params.words, ignore_case=False)
    trailing = "".join(PLACEHOLDERS) + " "
    for unit in prose_units(ctx):
        for sentence, text in unit_sentences(unit):
            if text.rstrip(trailing).endswith("?"):
                yield finding(
                    unit,
                    sentence.start,
                    sentence.end,
                    "the sentence is a question. Write a statement.",
                )
            # At the start of a sentence, "Sie" and "Ihr" can mean "they" and "their".
            yield from (
                finding(
                    unit,
                    sentence.start + match.start(),
                    sentence.start + match.end(),
                    f"{match.group(0)!r} addresses the reader. Write an impersonal sentence.",
                )
                for match in pattern.finditer(text)
                if text[: match.start()].strip()
            )


# Word choice


@rule(
    "core.style.filler",
    summary="The text does not use filler words.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VL02, "Folie 89", "Beispiele für Füllwörter: also, einigermaßen, sozusagen, schlichtweg"
        ),
        ref(
            BRINK,
            "S. 181",
            "Füllwörter wie also, dann, auch, nun etc. (...) wieder eliminiert werden.",
        ),
        ref(
            HW,
            "S. 106",
            "Füllwörter wie gewissermaßen, sozusagen oder eigentlich schränken (...) ein.",
        ),
    ],
    params=WordList(
        words=(
            "also",
            "dann",
            "auch",
            "nun",
            "gewissermaßen",
            "sozusagen",
            "eigentlich",
            "einigermaßen",
            "schlichtweg",
            "offenbar",
        )
    ),
)
def filler(ctx: Context, params: WordList) -> Iterator[Finding]:
    """Report filler words."""
    return _word_rule(ctx, params.words, "filler word {match!r}. Remove it.")


@rule(
    "core.style.vague",
    summary="The text does not use vague words.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 181",
            "Vage Ausdrücke wie größtenteils, meistens, enorm (...) sind unpräzise",
        )
    ],
    params=WordList(
        words=(
            "größtenteils",
            "meistens",
            "enorm*",
            "ziemlich",
            "in etwa",
            "möglicherweise",
            "gewiss",
            "fast",
        )
    ),
)
def vague(ctx: Context, params: WordList) -> Iterator[Finding]:
    """Report vague words."""
    return _word_rule(ctx, params.words, "vague word {match!r}. Give a precise statement.")


@rule(
    "core.style.emotional",
    summary="The text does not use emotional or judging words.",
    severity=Severity.WARNING,
    sources=[
        ref(
            BRINK,
            "S. 179",
            "Ausdrücke wie unglaublich, erfreulicherweise, leicht ersichtlich, leider (...)",
        ),
        ref(
            LANGE,
            "S. 108",
            "werden die Aussagen von Keseling in einen kämpferischen Kontext gestellt",
        ),
        ref(HW, "S. 105", "Vermeiden Sie daher übertreibende und wertende Äußerungen"),
    ],
    params=WordList(
        words=(
            "unglaublich*",
            "erfreulicherweise",
            "leicht ersichtlich",
            "leider",
            "natürlich",
            "selbstverständlich",
            "automatisch",
            "sehr",
            "wichtig*",
            "endlich",
            "offensichtlich*",
            "angeblich*",
        )
    ),
)
def emotional(ctx: Context, params: WordList) -> Iterator[Finding]:
    """Report emotional or judging words."""
    return _word_rule(ctx, params.words, "emotional or judging word {match!r}. Write neutral text.")


@rule(
    "core.style.false-superlative",
    summary="The text does not use superlatives of words that have no degree.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 181",
            "am optimalsten, die einzigste Ausnahme, die bestmöglichste Alternative",
        )
    ],
    params=WordList(
        words=(
            "optimalst*",
            "einzigst*",
            "bestmöglichst*",
            "adäquatest*",
            "maximalst*",
            "minimalst*",
            "idealst*",
            "perfektest*",
        )
    ),
)
def false_superlative(ctx: Context, params: WordList) -> Iterator[Finding]:
    """Report false superlatives."""
    return _word_rule(
        ctx, params.words, "false superlative {match!r}. Use the base form of the word."
    )


@rule(
    "core.style.platitude",
    summary="The text does not use platitudes or colloquial phrases.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 179",
            "Ausdrücke wie nebenbei bemerkt, am Rande sei erwähnt oder noch erwähnt sei",
        ),
        ref(
            BRINK,
            "S. 181",
            "Umgangssprachliche Ausdrücke (Mit Sicherheit lässt sich sagen, dass …)",
        ),
        ref(
            BRINK, "S. 181", "Auch ein Bezug auf die Überschrift des Kapitels ist nicht statthaft."
        ),
    ],
    params=WordList(
        words=(
            "nebenbei bemerkt",
            "am Rande sei erwähnt",
            "noch erwähnt sei",
            "Mit Sicherheit lässt sich sagen",
            "in der Überschrift",
        )
    ),
)
def platitude(ctx: Context, params: WordList) -> Iterator[Finding]:
    """Report platitudes."""
    return _word_rule(ctx, params.words, "platitude {match!r}. Remove it.")


@rule(
    "core.style.generalization",
    summary="The text does not use sweeping generalizations.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 106",
            "generell, grundsätzlich, traditionell, klassisch, weltweit oder die Menschheit",
        )
    ],
    params=WordList(
        words=(
            "generell",
            "grundsätzlich",
            "traditionell*",
            "klassisch*",
            "weltweit*",
            "die Menschheit",
            "schon immer",
        )
    ),
)
def generalization(ctx: Context, params: WordList) -> Iterator[Finding]:
    """Report generalizing words."""
    return _word_rule(ctx, params.words, "generalization {match!r}. Make the statement specific.")


@dataclass(frozen=True, slots=True)
class RestrictionParams:
    """Words that restrict a statement, and words that name the exception."""

    triggers: tuple[str, ...] = (
        "grundsätzlich",
        "generell",
        "i.d.R.",
        "in der Regel",
        "im Allgemeinen",
    )
    exceptions: tuple[str, ...] = (
        "außer",
        "es sei denn",
        "Ausnahme*",
        "ausgenommen",
        "abgesehen",
    )


@rule(
    "core.style.restriction-exception",
    summary="A sentence with 'in der Regel' or a similar word names the exception.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 194",
            "bedarf eines Neben- oder Folgesatzes, in welchem auf mögliche Ausnahmen (...)",
        )
    ],
    params=RestrictionParams(),
)
def restriction_exception(ctx: Context, params: RestrictionParams) -> Iterator[Finding]:
    """Report a restricting word without an exception in the same or the next sentence."""
    trigger = word_regex(params.triggers)
    exception = word_regex(params.exceptions)
    for unit in prose_units(ctx):
        parts = unit_sentences(unit)
        texts = [text for _, text in parts] + [""]
        for index, (sentence, text) in enumerate(parts):
            if exception.search(texts[index] + " " + texts[index + 1]):
                continue
            yield from (
                finding(
                    unit,
                    sentence.start + match.start(),
                    sentence.start + match.end(),
                    f"{flat(match.group(0))!r} without an exception. Name the exception.",
                )
                for match in trigger.finditer(text)
            )


@rule(
    "core.style.so-called",
    summary="The text does not use 'sogenannt'.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 202",
            "ist es nicht nötig, diesen mit „sogenannt“ einzuleiten.",
        )
    ],
    params=WordList(words=("sog.", "sogenannt*", "so genannt*")),
)
def so_called(ctx: Context, params: WordList) -> Iterator[Finding]:
    """Report 'sogenannt'."""
    return _word_rule(ctx, params.words, "{match!r}. Introduce the term without it.")


@rule(
    "core.style.paired-reference",
    summary="A second part of a pair, for example 'anschließend', has its first part.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 193",
            "Es wird ein anschließend benutzt, ohne vorher ein zunächst (...)",
        )
    ],
    params=WordList(words=("auf der anderen Seite|auf der einen Seite", "anschließend|zunächst")),
)
def paired_reference(ctx: Context, params: WordList) -> Iterator[Finding]:
    """Report the second part of a pair without the first part before it in the paragraph.

    Each entry has the form `second|first`.
    """
    pairs = [
        (word_regex((second.strip(),)), word_regex((first.strip(),)), first.strip())
        for second, _, first in (entry.partition("|") for entry in params.words)
    ]
    for unit in prose_units(ctx):
        text = masked(unit)
        for second, first, first_text in pairs:
            yield from (
                finding(
                    unit,
                    match.start(),
                    match.end(),
                    f"{flat(match.group(0))!r} without {first_text!r} before it. Add it.",
                )
                for match in second.finditer(text)
                if not first.search(text, 0, match.start())
            )


# Sentence structure

_SUBORDINATORS = (
    "dass|weil|da|wenn|ob|obwohl|obgleich|damit|sodass|so dass|während|nachdem|bevor|indem|"
    "falls|sofern|soweit|solange|sobald|seit|seitdem|bis|als|wobei|wodurch|womit|wozu|"
    "worin|worauf|weshalb|warum|wo|wie"
)
_RELATIVES = "dessen|deren|denen|welche|welcher|welches|welchem|welchen"
_ARTICLES = "der|die|das|dem|den"
_PREPOSITIONS = (
    "an|auf|aus|bei|durch|für|gegen|hinter|in|mit|nach|neben|ohne|über|um|unter|von|vor|zu|zwischen"
)
_CLAUSE_START = rf"(?:(?P<sub>{_SUBORDINATORS}|{_RELATIVES})|(?P<art>{_ARTICLES}))"
_SUBCLAUSE = re.compile(
    rf",\s*(?:(?:{_PREPOSITIONS})\s+)?{_CLAUSE_START}(?!\w)(?P<rest>[^,;:]*)", re.IGNORECASE
)


def subclause_count(text: str) -> int:
    """Return the estimated number of subordinate clauses in a sentence.

    A clause starts after a comma with a conjunction or a relative pronoun. An
    article like "die" counts only if the clause ends with a lowercase word.
    This word is usually the verb of a relative clause.
    """
    return sum(
        1
        for match in _SUBCLAUSE.finditer(text)
        if match.group("sub") is not None or _ends_with_verb(match.group("rest"))
    )


def _ends_with_verb(rest: str) -> bool:
    found = words(rest)
    return bool(found) and found[-1].group(0)[0].islower()


@dataclass(frozen=True, slots=True)
class SubclauseParams:
    """Parameters of core.style.subclauses."""

    max_subclauses: int = 2


@rule(
    "core.style.subclauses",
    summary="A sentence has at most two subordinate clauses.",
    severity=Severity.WARNING,
    sources=[
        ref(VL02, "Folie 99", "Verschachtelte Nebensätze vermeiden"),
        ref(
            HW,
            "S. 98",
            "Mehr als zwei Nebensätze machen es dem Leser schwer, sich im Satz zu orientieren",
        ),
    ],
    params=SubclauseParams(),
)
def subclauses(ctx: Context, params: SubclauseParams) -> Iterator[Finding]:
    """Report sentences with too many subordinate clauses."""
    for unit in prose_units(ctx):
        for sentence, text in unit_sentences(unit):
            count = subclause_count(text)
            if count > params.max_subclauses:
                yield finding(
                    unit,
                    sentence.start,
                    sentence.end,
                    f"{count} subordinate clauses (max. {params.max_subclauses}). Split it.",
                )


@dataclass(frozen=True, slots=True)
class SentenceLengthParams:
    """Parameters of core.style.sentence-length."""

    max_words: int = 20


@rule(
    "core.style.sentence-length",
    summary="A sentence has at most 20 words.",
    severity=Severity.WARNING,
    sources=[
        ref(VL02, "Folie 99", "Sätze in der Länge begrenzen (15 – 20 Wörter ideal)"),
        ref(
            BRINK,
            "S. 178",
            "Lange Sätze erschweren das Verständnis und bereiten dem Leser unnötig Mühe.",
        ),
        ref(
            HW,
            "S. 199",
            "Lange Sätze, die mehrere Zeilen umfassen (...), sind (...) schwer zu lesen.",
        ),
    ],
    params=SentenceLengthParams(),
)
def sentence_length(ctx: Context, params: SentenceLengthParams) -> Iterator[Finding]:
    """Report long sentences. Quoted words do not count. A glossary use counts as text."""
    for unit in prose_units(ctx):
        text = masked(unit, glossary=False)
        for sentence in sentences(unit):
            count = len(words(text[sentence.start : sentence.end]))
            if count > params.max_words:
                yield finding(
                    unit,
                    sentence.start,
                    sentence.end,
                    f"the sentence has {count} words (max. {params.max_words}). Split it.",
                )


@rule(
    "core.style.single-sentence-paragraph",
    summary="A paragraph has more than one sentence.",
    severity=Severity.WARNING,
    sources=[
        ref(
            BRINK,
            "S. 193",
            "falls Absätze (...) lediglich aus einen einzelnen Satz bestehen",
        ),
        ref(HW, "S. 67", "Viele Studierende fügen häufig schon nach jedem Satz einen Absatz ein."),
    ],
)
def single_sentence_paragraph(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report paragraphs with one sentence. A paragraph that ends with a colon leads a list."""
    return (
        finding(
            unit,
            0,
            len(unit.text),
            "the paragraph has only one sentence. Extend it or join it with the next paragraph.",
        )
        for unit in prose_units(ctx, frozenset({UnitKind.PARAGRAPH}))
        if len(sentences(unit)) == 1 and not unit.text.rstrip().endswith(":")
    )


type SentenceRow = tuple[Unit, Sentence, str]


def paragraph_runs(ctx: Context) -> Iterator[list[SentenceRow]]:
    """Yield the sentences of the paragraphs under each heading, in order.

    The text of each sentence is masked, but glossary uses stay visible.
    """
    groups = groupby(prose_units(ctx, frozenset({UnitKind.PARAGRAPH})), key=_heading_key)
    for _, units in groups:
        yield [
            (unit, sentence, text[sentence.start : sentence.end])
            for unit in units
            for text in (masked(unit, glossary=False),)
            for sentence in sentences(unit)
        ]


def _heading_key(unit: Unit) -> int:
    return -1 if unit.heading is None else unit.heading.order


def _windows(count: int, size: int) -> range:
    """Return the end indexes of all windows of `size` items in `count` items."""
    return range(size - 1, count) if size > 0 else range(0)


@dataclass(frozen=True, slots=True)
class RunParams:
    """The number of sentences in a row that the rule reports."""

    run: int = 3


@rule(
    "core.style.same-start",
    summary="Three sentences in a row do not start with the same word.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 104",
            "Variationen in den Satzanfängen (...) das Lesen des Textes erleichtern",
        )
    ],
    params=RunParams(),
)
def same_start(ctx: Context, params: RunParams) -> Iterator[Finding]:
    """Report the sentence that completes a run of sentences with the same first word."""
    for run in paragraph_runs(ctx):
        firsts = [_first_word(text) for _, _, text in run]
        for index in _windows(len(run), params.run):
            window = firsts[index - params.run + 1 : index + 1]
            if window[0] and all(word == window[0] for word in window):
                unit, sentence, _ = run[index]
                yield finding(
                    unit,
                    sentence.start,
                    sentence.end,
                    f"{params.run} sentences in a row start with {window[0]!r}. Vary them.",
                )


def _first_word(text: str) -> str:
    found = words(text)
    if not found or text[: found[0].start()].strip(" „‚\"'("):
        return ""
    return found[0].group(0).casefold()


_WERDEN = re.compile(r"(?<!\w)(?:wird|werden|wurde|wurden|worden|würde|würden)(?!\w)")
# A past participle: "gemacht", "angegeben", "verwendet" or "analysiert".
_PARTICIPLE_FORMS = (
    r"[a-zäöüß]*ge[a-zäöüß]{2,}(?:t|en)",
    r"(?:be|ver|er|zer|ent|emp|miss)[a-zäöüß]{2,}t",
    r"[a-zäöüß]{2,}iert",
)
_PARTICIPLE = re.compile(rf"(?<!\w)(?:{'|'.join(_PARTICIPLE_FORMS)})(?!\w)")


@dataclass(frozen=True, slots=True)
class PassiveParams:
    """Parameters of core.style.passive-run."""

    run: int = 3
    not_participles: tuple[str, ...] = (
        "gegen*",
        "genug",
        "gestern",
        "gerade*",
        "allgemein*",
        "gemeinsam*",
        "genau*",
        "gering*",
        "gesamt*",
        "folgend*",
        "eigen*",
        "morgen*",
        "übrigen*",
        "wegen",
        "bereit*",
    )


def is_passive(text: str, not_participles: re.Pattern[str]) -> bool:
    """Return True if a sentence has a form of 'werden' and a past participle."""
    return bool(_WERDEN.search(text)) and any(
        not not_participles.fullmatch(match.group(0)) for match in _PARTICIPLE.finditer(text)
    )


@rule(
    "core.style.passive-run",
    summary="Three sentences in a row are not all in the passive voice.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 203",
            "Die häufige Verwendung von Passiv ist dem Lesefluss weniger förderlich",
        ),
        ref(
            HW,
            "S. 100",
            "Die Aneinanderreihung von Passivkonstruktionen (...) erzeugt so Monotonie.",
        ),
    ],
    params=PassiveParams(),
)
def passive_run(ctx: Context, params: PassiveParams) -> Iterator[Finding]:
    """Report the sentence that completes a run of passive sentences."""
    exclusions = word_regex(params.not_participles)
    for run in paragraph_runs(ctx):
        flags = [is_passive(text, exclusions) for _, _, text in run]
        for index in _windows(len(run), params.run):
            if all(flags[index - params.run + 1 : index + 1]):
                unit, sentence, _ = run[index]
                yield finding(
                    unit,
                    sentence.start,
                    sentence.end,
                    f"{params.run} passive sentences in a row. Use the active voice.",
                )


@dataclass(frozen=True, slots=True)
class FutureParams:
    """Words that point to a part of the text, and verbs of text references."""

    cues: tuple[str, ...] = (
        "Kapitel",
        "Abschnitt",
        "Arbeit",
        "im Folgenden",
        "nachfolgend",
        "im weiteren Verlauf",
        "später",
        "unten",
        "anschließend",
    )
    verbs: tuple[str, ...] = (
        "zeigen",
        "untersuchen",
        "betrachten",
        "erläutern",
        "darstellen",
        "beschreiben",
        "eingehen",
        "vorstellen",
        "behandeln",
        "diskutieren",
        "analysieren",
        "erklären",
        "beleuchten",
        "aufzeigen",
        "vertiefen",
    )


_FUTURE_PASSIVE = re.compile(r"(?<!\w)[a-zäöüß]{3,}(?:t|en)\s+werden(?!\w)")
_FUTURE_AUX = re.compile(r"(?<!\w)(?:wird|werden)(?!\w)")
_MODAL_WORDS = (
    "kann",
    "können",
    "könnte",
    "könnten",
    "muss",
    "müssen",
    "soll",
    "sollen",
    "sollte",
    "sollten",
    "darf",
    "dürfen",
)
_MODALS_ANY = re.compile(rf"(?<!\w)(?:{'|'.join(_MODAL_WORDS)})(?!\w)", re.IGNORECASE)


@rule(
    "core.style.future-reference",
    summary="A reference to another part of the text is in the present tense, not the future.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 101",
            "Nutzen Sie daher aber kein Futur (die Zukunftsform)",
        )
    ],
    params=FutureParams(),
)
def future_reference(ctx: Context, params: FutureParams) -> Iterator[Finding]:
    """Report sentences that refer to the text and use the future tense."""
    cue = word_regex(params.cues)
    verb = word_regex(params.verbs)
    for unit in prose_units(ctx):
        for sentence, text in unit_sentences(unit):
            aux = _FUTURE_AUX.search(text)
            if aux is None or not cue.search(text) or _MODALS_ANY.search(text):
                continue
            if _FUTURE_PASSIVE.search(text) or verb.search(text, aux.end()):
                yield finding(
                    unit,
                    sentence.start,
                    sentence.end,
                    "the text reference uses the future tense. Use the present tense.",
                )


@dataclass(frozen=True, slots=True)
class ModalParams:
    """Parameters of core.style.modal-density."""

    max_per_100_words: float = 3.0
    min_words: int = 100
    modals: tuple[str, ...] = (
        "kann",
        "können",
        "könnte",
        "könnten",
        "konnte",
        "konnten",
        "muss",
        "müssen",
        "müsste",
        "müssten",
        "musste",
        "mussten",
        "soll",
        "sollen",
        "sollte",
        "sollten",
        "darf",
        "dürfen",
        "dürfte",
        "dürften",
        "durfte",
        "durften",
        "will",
        "wollen",
        "wollte",
        "wollten",
        "mag",
        "mögen",
        "möchte",
        "möchten",
    )


@rule(
    "core.style.modal-density",
    summary="A section has at most 3 modal verbs per 100 words.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 102",
            "durch die häufige Nutzung von Modalverben an Eindeutigkeit verliert",
        ),
        ref(
            BRINK,
            "S. 194",
            "Viele Kandidaten verwenden ständig das Modalverb können",
        ),
    ],
    params=ModalParams(),
)
def modal_density(ctx: Context, params: ModalParams) -> Iterator[Finding]:
    """Report sections with too many modal verbs. The rule skips sections below `min_words`."""
    pattern = word_regex(params.modals)
    selected = {id(unit) for unit in prose_units(ctx)}
    for heading in ctx.project.document.headings:
        texts = [masked(unit, glossary=False) for unit in heading.units if id(unit) in selected]
        count = sum(len(words(text)) for text in texts)
        if count < max(params.min_words, 1):
            continue
        density = 100 * sum(len(pattern.findall(text)) for text in texts) / count
        limit = params.max_per_100_words
        if density > limit:
            yield Finding(
                f"{density:.1f} modal verbs per 100 words (max. {limit:g}). Be direct.",
                heading.location,
            )


@dataclass(frozen=True, slots=True)
class FunctionVerbParams:
    """Parameters of core.style.function-verb."""

    phrases: tuple[str, ...] = (
        "unter Beweis",
        "ist abhängig",
        "sind abhängig",
        "war abhängig",
        "waren abhängig",
    )
    double_negation: bool = True
    not_negations: tuple[str, ...] = (
        "unbedingt",
        "unter",
        "unten",
        "uns",
        "unser*",
        "ungefähr",
        "und",
        "um",
    )


_DOUBLE_NEGATION = re.compile(r"(?<!\w)nicht\s+(un[a-zäöüß]{2,})(?!\w)", re.IGNORECASE)


@rule(
    "core.style.function-verb",
    summary="The text uses plain verbs, not function verb phrases or double negations.",
    severity=Severity.WARNING,
    sources=[
        ref(
            BRINK,
            "S. 179 f.",
            "Funktionsverbgefüge unter Beweis stellen etwa liest und spricht sich (...)",
        )
    ],
    params=FunctionVerbParams(),
)
def function_verb(ctx: Context, params: FunctionVerbParams) -> Iterator[Finding]:
    """Report function verb phrases and double negations like 'nicht unwichtig'."""
    yield from _word_rule(ctx, params.phrases, "phrase {match!r}. Use the plain verb.")
    if not params.double_negation:
        return
    allowed = word_regex(params.not_negations)
    yield from match_findings(
        (
            (unit, match)
            for unit, match in hits(ctx, _DOUBLE_NEGATION)
            if not allowed.fullmatch(match.group(1))
        ),
        "double negation {match!r}. Use the positive word.",
    )


# Tense


@dataclass(frozen=True, slots=True)
class TenseParams:
    """Parameters of core.style.tense.

    `allowed_chapters` are level-1 titles where the preterite is correct.
    `forms` are preterite verb forms. The match is case-sensitive, so that the
    noun "Waren" does not match. If `passive` is set, the message names the
    passive preterite ("wurde ... untersucht").
    """

    allowed_chapters: tuple[str, ...] = ("Methoden",)
    forms: tuple[str, ...] = (
        "war",
        "waren",
        "wurde",
        "wurden",
        "hatte",
        "hatten",
        "zeigte",
        "zeigten",
        "ergab",
        "ergaben",
        "untersuchte",
        "untersuchten",
        "fand",
        "fanden",
        "gab",
        "gaben",
        "kam",
        "kamen",
        "lag",
        "lagen",
        "blieb",
        "blieben",
        "ging",
        "gingen",
        "stellte",
        "stellten",
        "führte",
        "führten",
        "nutzte",
        "nutzten",
        "verwendete",
        "verwendeten",
        "analysierte",
        "analysierten",
        "bestätigte",
        "bestätigten",
        "erfolgte",
        "erfolgten",
        "lieferte",
        "lieferten",
        "betrug",
        "betrugen",
        "konnte",
        "konnten",
        "musste",
        "mussten",
    )
    passive: bool = True


_PASSIVE_AUX = frozenset({"wurde", "wurden"})


@rule(
    "core.style.tense",
    summary="The text is in the present tense. Only the chapter 'Methoden' uses the preterite.",
    severity=Severity.WARNING,
    sources=[
        ref(
            FACTSHEET,
            "Wichtige stilistische Merkmale",
            "Der gesamte Text muss hauptsächlich im Präsens verfasst werden.",
        ),
        ref(
            HW,
            "S. 101",
            "Lediglich die Darstellung konkreter einmaliger Tätigkeiten (...) im Präteritum",
        ),
    ],
    params=TenseParams(),
)
def tense(ctx: Context, params: TenseParams) -> Iterator[Finding]:
    """Report preterite verb forms outside the allowed chapters."""
    pattern = word_regex(params.forms, ignore_case=False)
    allowed = frozenset(params.allowed_chapters)
    exclusions = word_regex(PassiveParams().not_participles)
    for unit in prose_units(ctx):
        if unit.heading is not None and top_heading(unit.heading).text in allowed:
            continue
        for sentence, text in unit_sentences(unit):
            for match in pattern.finditer(text):
                form = match.group(0)
                passive = (
                    params.passive
                    and form in _PASSIVE_AUX
                    and is_passive(form + " " + text[match.end() :], exclusions)
                )
                kind = "passive preterite" if passive else "preterite"
                yield finding(
                    unit,
                    sentence.start + match.start(),
                    sentence.start + match.end(),
                    f"{kind} {form!r} outside the method chapter. Use the present tense.",
                )


# Punctuation and word choice

_SONDERN = re.compile(r"(?<!\w)sondern(?!\w)")
# Characters before "sondern" that make a comma unnecessary.
_SONDERN_OK = frozenset(",;:(–—-/")


@rule(
    "core.style.sondern-comma",
    summary="A comma comes before the conjunction 'sondern'.",
    severity=Severity.ERROR,
    sources=[
        ref(VL02, "Folie 96", "dass vor die Konjunktion sondern immer ein Komma zu setzen ist"),
    ],
)
def sondern_comma(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report 'sondern' without a comma before it."""
    for unit in prose_units(ctx):
        text = masked(unit)
        for match in _SONDERN.finditer(text):
            before = text[: match.start()].rstrip()
            if before and before[-1] not in _SONDERN_OK:
                yield finding(
                    unit,
                    len(before),
                    match.end(),
                    "no comma before 'sondern'. Add a comma.",
                )


@dataclass(frozen=True, slots=True)
class IndemParams:
    """Articles that start the noun phrase before ', indem'."""

    articles: tuple[str, ...] = ("das", "ein", "einem", "einer", "dem")


@rule(
    "core.style.indem",
    summary="'indem' does not follow a noun. A relative clause uses 'in dem'.",
    severity=Severity.WARNING,
    sources=[
        ref(VL02, "Folie 101", "„indem“ – dadurch dass … : macht hier keinen Sinn"),
    ],
    params=IndemParams(),
)
def indem(ctx: Context, params: IndemParams) -> Iterator[Finding]:
    """Report 'indem' directly after a noun phrase like 'ein System,'.

    The pattern is an article, up to two small words and a capitalized noun.
    """
    articles = "|".join(re.escape(article) for article in params.articles if article)
    if not articles:
        return
    pattern = re.compile(
        rf"(?<!\w)(?i:{articles})\s+(?:[a-zäöüß]+\s+){{0,2}}[A-ZÄÖÜ][\w-]*\s*,\s*(indem)(?!\w)"
    )
    yield from (
        finding(
            unit,
            match.start(1),
            match.end(1),
            "'indem' after a noun. If it means 'in which', write 'in dem' or 'bei dem'.",
        )
        for unit, match in hits(ctx, pattern)
    )


# Spelling

_SPELL_KINDS = TEXT_KINDS | {UnitKind.HEADING}
_SPELL_TOKEN = re.compile(r"[^\W_](?:[\w­-]*[^\W_])?")
_NAME_WORD = re.compile(r"[^\W\d_]+")
_COMPOUND = re.compile(r"(?<![\w­-])([A-ZÄÖÜ][a-zäöüß]+)-([A-ZÄÖÜ][a-zäöüß]+)(?![\w-])")
# A part of a hyphenated word must be longer than this to lose a joint 's'.
_MIN_JOINT_PART = 3


@dataclass(frozen=True, slots=True)
class SpellingParams:
    """Parameters of core.style.spelling and core.style.compound-hyphen.

    `dictionary` is a file in the project root in the hunspell format for a
    personal dictionary. Each line is a word (`Hirsch`) or a word and a model
    word (`Validierung/Hoffnung`). With a model word, hunspell also accepts the
    inflected forms of the word (`Validierungen`). The model word must be a
    root word of the hunspell dictionary. Lines that start with '#' are
    comments. The file is optional.
    """

    language: str = "de_DE"
    dictionary: str = "dictionary.txt"


def spell_units(ctx: Context) -> Iterator[Unit]:
    """Yield the units that the spelling rules check, and the abstract."""
    abstract = ctx.project.abstract
    return chain(prose_units(ctx, _SPELL_KINDS), () if abstract is None else (abstract,))


def dictionary_words(path: Path) -> Iterator[str]:
    """Yield the words of a project dictionary file. A missing file has no words."""
    try:
        lines = read_text(path).splitlines()
    except OSError, UnicodeDecodeError:
        return iter(())
    return (line.strip() for line in lines if line.strip() and not line.strip().startswith("#"))


def personal_dictionary(ctx: Context, dictionary: str) -> tuple[str, ...]:
    """Return the lines of the project dictionary for hunspell `-p`."""
    return tuple(dictionary_words(ctx.root / dictionary)) if dictionary else ()


def project_words(ctx: Context, dictionary: str) -> frozenset[str]:
    """Return the case-folded words that the spelling rules accept without a check.

    These are the glossary keys and forms, the acronyms, the bibliography keys
    and person names, and the plain words of the project dictionary. A line
    with a model word ('/') goes only to hunspell.
    """
    project = ctx.project
    entries = list(project.bibliography.entries.values())
    texts = chain(
        chain.from_iterable(
            (term.key, term.name, term.plural or "", term.genitive or "")
            for term in project.terms.values()
        ),
        chain.from_iterable(
            (item.key, item.short, item.long) for item in project.acronyms.values()
        ),
        (entry.key for entry in entries),
        (clean(name) for entry in entries for name in (*entry.names(), *entry.names("editor"))),
        (line for line in personal_dictionary(ctx, dictionary) if "/" not in line),
    )
    return frozenset(
        word.casefold() for text in texts for word in (text, *_NAME_WORD.findall(text))
    )


def _skip_word(word: str, ignored: frozenset[str]) -> bool:
    """Return True if the spelling rule does not check `word`."""
    return (
        # Single letters are abbreviations or list labels.
        len(word) < 2
        or any(char.isdigit() for char in word)
        or word.isupper()
        or is_abbreviation(word)
        or word.casefold() in ignored
    )


@dataclass(frozen=True, slots=True)
class SpellToken:
    """A word of the text and the spellings that make it correct.

    The word is correct if hunspell knows one spelling of `whole`, or one
    spelling of each item of `parts`. A hyphenated word has one item per part.
    """

    unit: Unit
    start: int
    end: int
    word: str
    whole: tuple[str, ...]
    parts: tuple[tuple[str, ...], ...]


def spell_tokens(unit: Unit, ignored: frozenset[str]) -> Iterator[SpellToken]:
    """Yield the words of a unit that the spelling rule checks."""
    text = masked(unit)
    for match in _SPELL_TOKEN.finditer(text):
        word = match.group(0).replace("­", "")
        if _skip_word(word, ignored):
            continue
        dot = text.startswith(".", match.end())
        pieces = word.split("-")
        parts = tuple(
            _part_spellings(piece, last=index == len(pieces) - 1, dot=dot)
            for index, piece in enumerate(pieces)
            if not _skip_word(piece, ignored)
        )
        whole = (word, f"{word}.") if dot else (word,)
        yield SpellToken(unit, match.start(), match.end(), word, whole, parts)


def _part_spellings(piece: str, *, last: bool, dot: bool) -> tuple[str, ...]:
    """Return the accepted spellings of one part of a hyphenated word.

    A part before a hyphen can end with the joint 's', as in 'Nutzungs-'.
    """
    if last:
        return (piece, f"{piece}.") if dot else (piece,)
    joint = (piece[:-1],) if piece.endswith("s") and len(piece) > _MIN_JOINT_PART else ()
    return (piece, *joint)


def is_misspelled(token: SpellToken, unknown: frozenset[str]) -> bool:
    """Return True if hunspell knows no spelling of the token."""

    def known(spellings: tuple[str, ...]) -> bool:
        return any(spelling not in unknown for spelling in spellings)

    return not known(token.whole) and any(not known(part) for part in token.parts)


def _unavailable(ctx: Context, error: SpellCheckUnavailableError) -> Finding:
    message = f"the spelling check did not run: {error}. Install hunspell and the dictionary."
    return Finding(
        message + " Set DICPATH to the dictionary directory.",
        Location(ctx.root / ctx.config.paths.main),
        severity=Severity.WARNING,
    )


@rule(
    "core.style.spelling",
    summary=(
        "The text has no spelling errors (hunspell de_DE and the project dictionary"
        " with one `word` or `word/model` on each line)."
    ),
    severity=Severity.ERROR,
    sources=[
        ref(VL02, "Folie 92", "Rechtschreibfehler sind (...) nicht akzeptabel!"),
        ref(VL02, "Folie 93", "Einfach nur peinlich!"),
    ],
    params=SpellingParams(),
)
def spelling(ctx: Context, params: SpellingParams) -> Iterator[Finding]:
    """Report words that hunspell does not know.

    The rule does not check quotations, code, math, glossary uses, words with
    digits and abbreviations. If hunspell does not run, the rule reports one
    warning.
    """
    ignored = project_words(ctx, params.dictionary)
    tokens = [token for unit in spell_units(ctx) for token in spell_tokens(unit, ignored)]
    if not tokens:
        return
    spellings = {item for token in tokens for item in chain(token.whole, *token.parts)}
    try:
        unknown = spellcheck.unknown_words(
            spellings, params.language, personal_dictionary(ctx, params.dictionary)
        )
    except SpellCheckUnavailableError as error:
        yield _unavailable(ctx, error)
        return
    where = params.dictionary or "the project dictionary"
    yield from (
        finding(
            token.unit,
            token.start,
            token.end,
            f"unknown word {token.word!r}. Correct it or add it to {where}.",
        )
        for token in tokens
        if is_misspelled(token, unknown)
    )


@rule(
    "core.style.compound-hyphen",
    summary="A compound noun is one word, not two nouns with a hyphen.",
    severity=Severity.WARNING,
    sources=[
        ref(VL02, "Folie 94", "Deutsche, schreibt mehr zusammen!"),
    ],
    params=SpellingParams(),
)
def compound_hyphen(ctx: Context, params: SpellingParams) -> Iterator[Finding]:
    """Report 'Nomen-Nomen' if the dictionary knows the joined word.

    The rule skips glossary uses, abbreviations, words with digits and words
    of the glossary, the bibliography and the project dictionary. It also
    skips a compound with a part that hunspell does not know alone. Such a
    part is usually a proper name, as in 'Hirsch-Weber'.
    """
    ignored = project_words(ctx, params.dictionary)
    found = [
        (unit, match, match.group(1) + match.group(2).lower())
        for unit in spell_units(ctx)
        for match in _COMPOUND.finditer(masked(unit))
        if not {part.casefold() for part in match.group(0, 1, 2)} & ignored
    ]
    if not found:
        return
    part_spellings = {
        match.group(0): (
            _part_spellings(match.group(1), last=False, dot=False),
            (match.group(2),),
        )
        for _, match, _ in found
    }
    words = chain(
        (joined for _, _, joined in found),
        chain.from_iterable(chain.from_iterable(part_spellings.values())),
    )
    try:
        unknown = spellcheck.unknown_words(
            words, params.language, personal_dictionary(ctx, params.dictionary)
        )
    except SpellCheckUnavailableError as error:
        yield _unavailable(ctx, error)
        return

    def names_part(compound: str) -> bool:
        return any(
            all(spelling in unknown for spelling in spellings)
            for spellings in part_spellings[compound]
        )

    yield from (
        finding(
            unit,
            match.start(),
            match.end(),
            f"{match.group(0)!r} has a hyphen. Write it as one word: {joined!r}.",
        )
        for unit, match, joined in found
        if joined not in unknown and not names_part(match.group(0))
    )


# Gender forms

_AND = r"(?:und|oder|bzw\.)"
_ART = r"(?:(?:der|die|den|dem)\s+)"
_GENDER_FORMS: tuple[tuple[str, str], ...] = (
    ("colon", r"[^\W\d_]+:(?:innen|in)(?!\w)"),
    ("star", r"[^\W\d_]+\*(?:innen|in)(?!\w)"),
    ("slash", r"[^\W\d_]+/-?(?:innen|in)(?!\w)"),
    ("binnen-I", r"[a-zäöüß]{2,}Innen(?!\w)"),
    ("pair", r"(?<!\w)(\w+?)innen\s+(?:und|oder|bzw\.)\s+\1(?:e|en|n)?(?!\w)"),
    ("pair", r"(?<!\w)(\w+?)(?:e|en|n)?\s+(?:und|oder|bzw\.)\s+\1innen(?!\w)"),
    ("pair", rf"(?<!\w)(\w+)in\s+{_AND}\s+{_ART}?\1(?:e|en|n)?(?!\w)"),
    ("pair", rf"(?<!\w)(\w+?)(?:e|en|n)?\s+{_AND}\s+{_ART}?\1in(?!\w)"),
)
_GENDER = [(name, re.compile(pattern)) for name, pattern in _GENDER_FORMS]


def gender_uses(text: str) -> list[tuple[str, re.Match[str]]]:
    """Return the gender forms in a text with their matches, in text order."""
    found = [(name, match) for name, pattern in _GENDER for match in pattern.finditer(text)]
    return sorted(found, key=lambda item: item[1].start())


@rule(
    "core.style.gender-consistent",
    summary="The text uses only one form of gender-fair language.",
    severity=Severity.WARNING,
    sources=[ref(USER, "Stil", "Nur eine Genderform im ganzen Text")],
)
def gender_consistent(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report gender forms that differ from the most frequent form."""
    uses = [
        (unit, name, match)
        for unit in prose_units(ctx)
        for name, match in gender_uses(masked(unit))
    ]
    counts = Counter(name for _, name, _ in uses)
    if len(counts) < 2:
        return
    main = counts.most_common(1)[0][0]
    yield from (
        finding(
            unit,
            match.start(),
            match.end(),
            f"gender form {name!r} differs from the main form {main!r}. Use one form.",
        )
        for unit, name, match in uses
        if name != main
    )


# Typography of the prose


@dataclass(frozen=True, slots=True)
class EmphasisParams:
    """Inline styles that the running text must not use."""

    styles: tuple[str, ...] = ("strong", "underline")


@rule(
    "core.style.bold-underline",
    summary="The running text does not use bold or underlined text.",
    severity=Severity.WARNING,
    sources=[
        ref(
            VORLAGE,
            "Zeichenformate",
            "Auf Hervorhebungen von Text mittels Fettdruck, Unterstreichungen, etc. soll (...)",
        ),
        ref(
            HW,
            "S. 202",
            "Grundsätzlich werden Wörter im Fließtext weder unterstrichen noch fett gesetzt.",
        ),
    ],
    params=EmphasisParams(),
)
def bold_underline(ctx: Context, params: EmphasisParams) -> Iterator[Finding]:
    """Report strong and underlined text in prose."""
    return (
        finding(
            unit,
            styled.span.start,
            styled.span.end,
            f"{styled.style} text in the running text. Remove the emphasis.",
        )
        for unit in prose_units(ctx)
        for styled in unit.styles
        if styled.style in params.styles and styled.span.end > styled.span.start
    )


@dataclass(frozen=True, slots=True)
class ParensParams:
    """Parameters of core.style.long-parens."""

    max_words: int = 12


def paren_spans(text: str) -> Iterator[tuple[int, int]]:
    """Yield the outermost balanced parentheses as (start, end). `end` is after ')'."""
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char == "(":
            if depth == 0:
                start = index
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
            if depth == 0:
                yield start, index + 1


@rule(
    "core.style.long-parens",
    summary="Text in parentheses has at most 12 words.",
    severity=Severity.WARNING,
    sources=[
        ref(HW, "S. 202", "Zudem ist von langen Ausführungen innerhalb von Klammern abzusehen.")
    ],
    params=ParensParams(),
)
def long_parens(ctx: Context, params: ParensParams) -> Iterator[Finding]:
    """Report long text in parentheses."""
    for unit in prose_units(ctx):
        text = masked(unit, glossary=False)
        for start, end in paren_spans(text):
            count = len(words(text[start:end]))
            if count > params.max_words:
                yield finding(
                    unit,
                    start,
                    end,
                    f"{count} words in parentheses (max. {params.max_words}). Shorten them.",
                )


# Phrases


@rule(
    "core.phrase.intro-cliche",
    summary="The text does not start a part with a cliche like 'Dieses Kapitel befasst sich'.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 185",
            "„Das Thema meiner Arbeit lautet ...“. Diese Einführung wirkt äußerst hilflos",
        ),
        ref(BRINK, "S. 187", "(aber bitte nicht der Art: Dieser Abschnitt beschäftigt sich mit …)"),
    ],
    params=PatternList(
        patterns=(
            r"Das\s+Thema\s+meiner\s+Arbeit\s+lautet",
            r"Diese[rs]?\s+(?:Abschnitt|Kapitel)\s+(?:beschäftigt|befasst)\s+sich",
        )
    ),
)
def intro_cliche(ctx: Context, params: PatternList) -> Iterator[Finding]:
    """Report introduction cliches."""
    return match_findings(
        hits(ctx, any_regex(params.patterns)), "cliche {match!r}. Start with the content."
    )


@rule(
    "core.phrase.scope-excuse",
    summary="The text does not use 'im Rahmen dieser Arbeit' as a reason.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 51",
            '"... um den Rahmen dieser Arbeit nicht zu sprengen ..." sind unzulässig.',
        )
    ],
    params=PatternList(patterns=(r"Rahmen\s+(?:dieser|der)\s+Arbeit",)),
)
def scope_excuse(ctx: Context, params: PatternList) -> Iterator[Finding]:
    """Report 'Rahmen dieser Arbeit'."""
    return match_findings(
        hits(ctx, any_regex(params.patterns), TEXT_KINDS),
        "{match!r}. Give the real reason or remove the phrase.",
    )


# Placeholders


@dataclass(frozen=True, slots=True)
class PlaceholderParams:
    """Markers of unfinished text."""

    markers: tuple[str, ...] = ("TODO", "XXX")
    bracket_verbs: tuple[str, ...] = ("eintragen", "einfügen")
    template_phrases: tuple[str, ...] = (
        "ist dieser Abschnitt zu löschen",
        "Diese Textvorlage wird als",
        "Lorem ipsum",
    )


def placeholder_regex(params: PlaceholderParams) -> re.Pattern[str]:
    """Return one pattern for all placeholder forms."""
    markers = "|".join(re.escape(marker) for marker in params.markers if marker)
    verbs = "|".join(re.escape(verb) for verb in params.bracket_verbs if verb)
    phrases = "|".join(
        r"\s+".join(re.escape(word) for word in phrase.split())
        for phrase in params.template_phrases
        if phrase.strip()
    )
    parts = [
        f"(?<![A-Za-z0-9])(?:{markers})(?![A-Za-z0-9])" if markers else "",
        rf"\[\s*Hier\b[^\]]*?\b(?:{verbs})\b[^\]]*\]" if verbs else "",
        f"(?i:{phrases})" if phrases else "",
    ]
    return re.compile("|".join(part for part in parts if part) or "(?!)")


@rule(
    "core.placeholder",
    summary="The sources have no TODO, XXX, '[Hier ... eintragen]' or template hint texts.",
    severity=Severity.ERROR,
    submission=True,
    sources=[
        ref(LANGE, "S. 138", "lassen Sie eine Lücke und setzen einen Platzhalter"),
        ref(VORLAGE, "Anhang", "[Hier die Arbeitshypothese eintragen]"),
    ],
    params=PlaceholderParams(),
)
def placeholder(ctx: Context, params: PlaceholderParams) -> Iterator[Finding]:
    """Report placeholders in the source of every .typ file of the project.

    The scan reads the raw source. It finds placeholders in prose, comments and
    settings, for example `submitted-on: "TODO"` in the metadata file.
    """
    project = ctx.project
    extra = (s for s in (project.settings_source, project.glossary_source) if s is not None)
    sources = {source.path.resolve(): source for source in chain(project.document.files, extra)}
    pattern = placeholder_regex(params)
    for source in sources.values():
        for match in pattern.finditer(source.text):
            begin = len(source.text[: match.start()].encode("utf-8"))
            end = begin + len(match.group(0).encode("utf-8"))
            shown = " ".join(match.group(0).split())[:60]
            yield Finding(
                f"placeholder {shown!r}. Replace it with the final text.",
                source.location(begin, end),
            )
