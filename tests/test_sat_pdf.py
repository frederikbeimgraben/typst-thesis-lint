"""PDF helpers for the SAT tests, and tests of the line reader.

The fixture `sat-example.pdf` is the compiled example of the template variant
(hsrtreport-typst, branch sat-meti, `example-sat/main.typ`).
"""

from __future__ import annotations

import dataclasses
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from thesis_lint.packs.sat_meti import pdflines
from thesis_lint.pdf import PdfChar, PdfDocument, PdfPage, read_pdf

if TYPE_CHECKING:
    from collections.abc import Callable

    from thesis_lint.context import Context

FIXTURE = Path(__file__).parent / "fixtures" / "sat-example.pdf"


@cache
def _example() -> PdfDocument:
    return read_pdf(FIXTURE)


def example_pdf() -> PdfDocument:
    """Return a fresh copy of the example PDF."""
    return transform(_example(), lambda _page, char: char)


def transform(
    pdf: PdfDocument, change: Callable[[PdfPage, PdfChar], PdfChar | None]
) -> PdfDocument:
    """Return a copy of the PDF with each glyph changed or removed by `change`."""
    pages = [
        dataclasses.replace(
            page,
            chars=[new for char in page.chars if (new := change(page, char)) is not None],
        )
        for page in pdf.pages
    ]
    return dataclasses.replace(pdf, pages=pages)


def use_pdf(ctx: Context, pdf: PdfDocument) -> Context:
    """Let the context return this PDF."""
    ctx.pdf_provider = lambda: pdf
    return ctx


def test_lines_have_regions_and_spaces() -> None:
    lines = pdflines.page_lines(example_pdf().pages[8])
    regions = [line.region for line in lines]
    assert regions[:3] == [pdflines.Region.HEADER] * 3
    assert regions[-1] is pdflines.Region.FOOTER
    heading = next(line for line in lines if line.has_size(pdflines.H1_PT))
    assert heading.text == "1 Einleitung"
    assert heading.title == "Einleitung"


def test_join_lines_joins_hyphenated_words() -> None:
    page = example_pdf().pages[8]
    body = [line for line in pdflines.page_lines(page) if line.region is pdflines.Region.BODY]
    text = pdflines.join_lines(body)
    assert "Medizinisch-Technischen Informatik erstellten" in text
    assert "erfahrungsgemäß" in text


def test_count_words_needs_a_letter_or_digit() -> None:
    assert pdflines.count_words("Das ist – ein Test (2014).") == 5


def test_chapter_headings_find_lists_and_chapters() -> None:
    titles = [line.title for line in pdflines.chapter_headings(example_pdf())]
    assert titles[:6] == list(pdflines.LIST_TITLES)
    assert titles[6] == "Einleitung"
    assert titles[-1] == "Anhang"
