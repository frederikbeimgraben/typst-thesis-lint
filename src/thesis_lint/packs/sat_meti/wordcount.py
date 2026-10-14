"""SAT rules for the word count, the abstract and the keywords."""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from thesis_lint.core.sources import SAT, VL02, VORLAGE, ref
from thesis_lint.model import Needs, Severity
from thesis_lint.packs.sat_meti import pdflines
from thesis_lint.packs.sat_meti.support import main_location, setting_location
from thesis_lint.registry import Finding, NoParams, rule
from thesis_lint.typst.document import content_unit
from thesis_lint.typst.values import Content, Unknown

if TYPE_CHECKING:
    from collections.abc import Iterator

    from thesis_lint.context import Context
    from thesis_lint.pdf import PdfDocument
    from thesis_lint.typst.values import Value


@dataclass(frozen=True, slots=True)
class WordcountParams:
    """Parameters of `sat.wordcount`. `sat.wordcount-titlepage` uses them too."""

    max: int = 1700
    min_warn: int = 1530
    start_heading: str = "Einleitung"
    stop_heading: str = "Literaturverzeichnis"
    top_margin_cm: float = pdflines.TOP_CM
    bottom_margin_cm: float = pdflines.BOTTOM_CM
    h1_pt: float = pdflines.H1_PT


@dataclass(frozen=True, slots=True)
class Measured:
    """The result of a word count in the PDF."""

    words: int | None
    problem: str | None = None


def measure(pdf: PdfDocument, params: WordcountParams) -> Measured:
    """Count the words from the start heading up to the stop heading.

    The count uses the body lines only. Header, footer and page numbers do not
    count. A heading number in front of the heading text does not count.
    """
    start = pdflines.find_heading(pdf, params.start_heading, params.h1_pt)
    if start is None:
        return Measured(None, f"cannot find the heading {params.start_heading!r} in the PDF")
    stop = pdflines.find_heading(pdf, params.stop_heading, params.h1_pt)
    lines = pdflines.lines_between(
        pdf, start, stop, top_cm=params.top_margin_cm, bottom_cm=params.bottom_margin_cm
    )
    text = pdflines.join_lines(
        dataclasses.replace(line, text=pdflines.heading_number_free(line)) for line in lines
    )
    problem = None if stop is not None else f"cannot find the heading {params.stop_heading!r}"
    return Measured(pdflines.count_words(text), problem)


@rule(
    "sat.wordcount",
    summary="The text from the introduction up to the bibliography has 1530 to 1700 words.",
    severity=Severity.ERROR,
    sources=[
        ref(SAT, "S. 11", "1700 Wörter; der Umfang muss eingehalten werden!"),
        ref(
            SAT,
            "S. 11 f.",
            "Gezählt werden die Wörter vom Anfang Ihres Textes (ab Einleitung) bis zum Beginn",
        ),
    ],
    params=WordcountParams(),
    needs=Needs.PDF,
    submission=True,
)
def wordcount(ctx: Context, params: WordcountParams) -> Iterator[Finding]:
    """Count the words in the PDF. Too many is an error, too few is a warning."""
    measured = measure(ctx.pdf, params)
    heading = ctx.heading_by_title(params.start_heading)
    location = heading.location if heading is not None else main_location(ctx)
    if measured.words is None:
        yield Finding(f"{measured.problem}. The word count is not possible", location)
        return
    if measured.problem is not None:
        yield Finding(f"{measured.problem}. The count goes to the end of the PDF", location)
    words = measured.words
    if words > params.max:
        yield Finding(
            " ".join(
                (
                    f"the text has {words} words. The maximum is {params.max}.",
                    f"Remove {words - params.max} words",
                )
            ),
            location,
        )
    elif words < params.min_warn:
        yield Finding(
            " ".join(
                (
                    f"the text has {words} words. This is less than {params.min_warn}.",
                    f"The SAT target is {params.max} words",
                )
            ),
            location,
            severity=Severity.WARNING,
        )


@rule(
    "sat.wordcount-titlepage",
    summary="The word count on the title page is the word count of the PDF.",
    severity=Severity.ERROR,
    sources=[ref(SAT, "S. 11", "Die Anzahl der Worte muss auf der Titelseite angegeben werden.")],
    needs=Needs.PDF,
    submission=True,
)
def wordcount_titlepage(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Compare the setting `word-count` with the count in the PDF.

    The rule uses the parameters of `sat.wordcount`, so that both rules count
    the same range.
    """
    configured = ctx.config.rules.get("sat.wordcount")
    params = (
        configured.params
        if configured is not None and isinstance(configured.params, WordcountParams)
        else WordcountParams()
    )
    measured = measure(ctx.pdf, params)
    if measured.words is None:
        return
    location = setting_location(ctx, "word-count")
    valued = ctx.project.settings.get("word-count")
    value = None if valued is None else valued.value
    if not isinstance(value, int) or isinstance(value, bool):
        yield Finding(
            f"the title page needs the word count of the PDF. Set word-count: {measured.words}",
            location,
        )
    elif value != measured.words:
        yield Finding(
            " ".join(
                (
                    f"word-count is {value}, but the PDF has {measured.words} words.",
                    f"Set word-count: {measured.words}",
                )
            ),
            location,
        )


@dataclass(frozen=True, slots=True)
class AbstractParams:
    """Parameters of `sat.abstract-length`."""

    min_words: int = 120
    max_words: int = 160
    page_index: int = 1
    label: str = "Abstract:"
    end_labels: tuple[str, ...] = ("Keywords:", "Schlüsselwörter:")
    next_page_title: str = "Inhalt"


@rule(
    "sat.abstract-length",
    summary="The abstract has 120 to 160 words and is complete on the second PDF page.",
    severity=Severity.ERROR,
    sources=[
        ref(SAT, "S. 9", "Abstract 120 – 160 Wörter"),
        ref(VORLAGE, "Abstract", "Das Abstract befindet sich vollständig auf Seite 2."),
    ],
    params=AbstractParams(),
    needs=Needs.PDF,
    submission=True,
)
def abstract_length(ctx: Context, params: AbstractParams) -> Iterator[Finding]:
    """Count the abstract words in the PDF and check that the abstract fits on its page."""
    location = setting_location(ctx, "abstract")
    pdf = ctx.pdf
    shown = params.page_index + 1
    if params.page_index >= len(pdf.pages):
        yield Finding(f"the PDF has no page {shown} with the abstract", location)
        return
    lines = pdflines.body_lines(pdflines.page_lines(pdf.pages[params.page_index]))
    text = pdflines.join_lines(lines)
    start = text.find(params.label)
    if start < 0:
        yield Finding(f"PDF page {shown} has no {params.label!r}. Set the abstract", location)
        return
    ends = [index for label in params.end_labels if (index := text.find(label, start)) >= 0]
    words = pdflines.count_words(text[start + len(params.label) : min(ends, default=len(text))])
    if not ends:
        yield Finding(
            " ".join(
                (
                    f"the keywords are not on PDF page {shown}. Make the abstract shorter,",
                    "so that the abstract and the keywords fit on this page",
                )
            ),
            location,
        )
    following = pdflines.first_body_line(pdf, params.page_index + 1)
    if following is not None and following.title != params.next_page_title:
        yield Finding(
            " ".join(
                (
                    f"the abstract page continues on PDF page {shown + 1}.",
                    "Make the abstract shorter, so that it fits on one page",
                )
            ),
            location,
        )
    if not params.min_words <= words <= params.max_words:
        yield Finding(
            f"the abstract has {words} words. Use {params.min_words} to {params.max_words} words",
            location,
        )


@dataclass(frozen=True, slots=True)
class KeywordsParams:
    """Parameters of `sat.keywords`."""

    count: int = 5
    german_setting: str = "keywords"
    english_setting: str = "keywords-en"


@rule(
    "sat.keywords",
    summary="The document has exactly 5 German and 5 English keywords.",
    severity=Severity.ERROR,
    sources=[
        ref(
            SAT,
            "S. 9",
            "Es müssen 5 sogenannte Keywords in deutscher und in englischer Sprache benannt werden",
        ),
        ref(VL02, "Folie 56", "Deckblatt: ... Abstract, Keywords"),
        ref(VL02, "Folie 68", "Möglichst englische Keywords verwenden oder Übersetzungen angeben"),
    ],
    params=KeywordsParams(),
)
def keywords(ctx: Context, params: KeywordsParams) -> Iterator[Finding]:
    """Count the items of the keyword settings."""
    for name, language in (
        (params.german_setting, "German"),
        (params.english_setting, "English"),
    ):
        valued = ctx.project.settings.get(name)
        found = _keywords(None if valued is None else valued.value)
        if found is None:
            yield Finding(
                " ".join(
                    (
                        f"the setting {name} is missing or not a string or an array.",
                        f"Add {params.count} {language} keywords",
                    )
                ),
                setting_location(ctx, name),
            )
        elif len(found) != params.count:
            yield Finding(
                f"{name} has {len(found)} keywords. Use exactly {params.count} {language} keywords",
                setting_location(ctx, name),
            )


@dataclass(frozen=True, slots=True)
class KeywordsTitleParams:
    """Parameters of `sat.keywords-title`.

    A keyword word matches a title word if one word is the other word plus one
    of `endings`. The check ignores case. All words of a keyword with more than
    one word must match consecutive title words in the same order.
    """

    german_setting: str = "keywords"
    english_setting: str = "keywords-en"
    title_setting: str = "title"
    endings: tuple[str, ...] = ("e", "en", "n", "s", "es", "er", "ern")


@rule(
    "sat.keywords-title",
    summary="No keyword repeats a word of the title.",
    severity=Severity.WARNING,
    sources=[
        ref(
            VL02,
            "Folie 68",
            "Keywords sollen nicht die Begriffe aus dem Titel wiederholen",
        )
    ],
    params=KeywordsTitleParams(),
)
def keywords_title(ctx: Context, params: KeywordsTitleParams) -> Iterator[Finding]:
    """Report German and English keywords that occur in the title, also in an inflected form."""
    title = ctx.project.setting_text(params.title_setting)
    if not title:
        return
    title_words = _WORD.findall(title)
    for name in (params.german_setting, params.english_setting):
        valued = ctx.project.settings.get(name)
        found = _keywords(None if valued is None else valued.value) or []
        yield from (
            Finding(
                " ".join(
                    (
                        f"the keyword {keyword!r} in {name} repeats a word of the title.",
                        "Use a keyword that adds new search information",
                    )
                ),
                setting_location(ctx, name),
            )
            for keyword in found
            if _repeats(_WORD.findall(keyword), title_words, params.endings)
        )


_WORD = re.compile(r"[^\W_]+")


def _same_word(first: str, second: str, endings: tuple[str, ...]) -> bool:
    """Return True if one word is the other word plus nothing or one of `endings`."""
    short, long = sorted((first.casefold(), second.casefold()), key=len)
    return long.startswith(short) and long[len(short) :] in {"", *endings}


def _repeats(words: list[str], title_words: list[str], endings: tuple[str, ...]) -> bool:
    """Return True if `words` match consecutive words of the title."""
    return bool(words) and any(
        all(
            _same_word(word, title_word, endings)
            for word, title_word in zip(words, title_words[start:], strict=False)
        )
        for start in range(len(title_words) - len(words) + 1)
    )


def _keywords(value: Value) -> list[str] | None:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [text for item in value if (text := _item_text(item))]
    return None


def _item_text(item: Value) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, Content):
        return content_unit(item.source, item.node).text.strip()
    if isinstance(item, Unknown):
        return item.source.node_text(item.node)
    return ""
