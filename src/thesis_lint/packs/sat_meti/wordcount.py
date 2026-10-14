"""SAT rules for the word count, the abstract and the keywords."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING

from thesis_lint.core.sources import SAT, VORLAGE, ref
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
        )
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
