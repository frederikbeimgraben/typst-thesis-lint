from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from tests.helpers import make_context, messages, run_rule
from tests.test_sat_pdf import (
    example_pdf,
    heading_line,
    heading_page,
    text_line,
    transform,
    use_pdf,
)
from thesis_lint.packs.sat_meti import pdflines
from thesis_lint.pdf import POINTS_PER_CM

if TYPE_CHECKING:
    from pathlib import Path

    from thesis_lint.context import Context
    from thesis_lint.pdf import PdfChar, PdfDocument, PdfPage

SETTINGS_LINES = (
    "#let settings = (",
    "  title: [Vorgaben zur Formatierung der Seminararbeit],",
    '  footer-id: "MTIB6.4:SAT-W2099",',
    ")",
    "",
)
SETTINGS = {"metadata.typ": "\n".join(SETTINGS_LINES)}


def context(tmp_path: Path, pdf: PdfDocument, files: dict[str, str] | None = None) -> Context:
    return use_pdf(make_context(tmp_path, files=files or SETTINGS), pdf)


def on_line(page: PdfPage, char: PdfChar, line: pdflines.Line) -> bool:
    return page.index == line.page and abs(char.top - line.top) < 1.0


def first_text_line() -> pdflines.Line:
    """Return the first text line of the chapter "Einleitung"."""
    return text_line(heading_page("Einleitung"), "Das hier")


def page_name(index: int) -> str:
    return f"PDF page {index + 1}"


LAYOUT_RULES = (
    "sat.layout.margins",
    "sat.layout.fonts",
    "sat.layout.font-sizes",
    "sat.layout.header-footer",
    "sat.layout.page-numbers",
    "sat.layout.chapter-pagebreak",
    "sat.layout.justified",
    "sat.footnote-lines",
)


def test_layout_rules_accept_the_template(tmp_path: Path) -> None:
    ctx = context(tmp_path, example_pdf())
    for rule_id in LAYOUT_RULES:
        assert messages(run_rule(ctx, rule_id)) == [], rule_id


def test_margins_report_text_in_the_left_margin(tmp_path: Path) -> None:
    target = first_text_line()

    def shift(page: PdfPage, char: PdfChar) -> PdfChar:
        if on_line(page, char, target):
            return dataclasses.replace(char, x0=char.x0 - 20, x1=char.x1 - 20)
        return char

    found = messages(
        run_rule(context(tmp_path, transform(example_pdf(), shift)), "sat.layout.margins")
    )
    assert len(found) == 1
    assert found[0].startswith(f"{page_name(target.page)}: the text 'Das hier")
    assert "left margin" in found[0]


def test_margins_allow_the_abstract_in_the_wider_box(tmp_path: Path) -> None:
    abstract = text_line(1, "Abstract:")

    def shift(page: PdfPage, char: PdfChar) -> PdfChar:
        if on_line(page, char, abstract):
            return dataclasses.replace(char, x0=char.x0 - 20, x1=char.x1 - 20)
        return char

    # The abstract starts left of the normal text block. The margins rule accepts this.
    assert abstract.x0 < pdflines.LEFT_CM * POINTS_PER_CM - 20
    found = messages(
        run_rule(context(tmp_path, transform(example_pdf(), shift)), "sat.layout.margins")
    )
    assert len(found) == 1
    assert found[0].startswith("PDF page 2: the text 'Abstract:")
    assert "left margin" in found[0]


def test_fonts_report_unknown_fonts_and_sans_captions(tmp_path: Path) -> None:
    caption = text_line(heading_page("Methoden"), "Abbildung 2.1")
    target = first_text_line()

    def change(page: PdfPage, char: PdfChar) -> PdfChar:
        if on_line(page, char, caption):
            return dataclasses.replace(char, font="LibreFranklin-Italic")
        if on_line(page, char, target):
            return dataclasses.replace(char, font="Arial-Regular")
        return char

    found = messages(
        run_rule(context(tmp_path, transform(example_pdf(), change)), "sat.layout.fonts")
    )
    assert len(found) == 2
    assert "uses the fonts Arial-Regular" in found[0]
    assert "the caption 'Abbildung 2.1" in found[1]


def test_font_sizes_report_wrong_text_size(tmp_path: Path) -> None:
    target = first_text_line()

    def shrink(page: PdfPage, char: PdfChar) -> PdfChar:
        return dataclasses.replace(char, size=11.0) if on_line(page, char, target) else char

    pdf = transform(example_pdf(), shrink)
    found = messages(run_rule(context(tmp_path, pdf), "sat.layout.font-sizes"))
    assert len(found) == 1
    assert "has 11 pt. Use 10 pt or 12 pt or 14 pt or 16 pt" in found[0]


def test_header_footer_report_wrong_header_and_footer(tmp_path: Path) -> None:
    contents = heading_line("Inhalt")
    first_header = pdflines.page_lines(example_pdf().pages[contents.page])[0]
    assert first_header.region is pdflines.Region.HEADER

    def drop(page: PdfPage, char: PdfChar) -> PdfChar | None:
        return None if on_line(page, char, first_header) else char

    files = {"metadata.typ": '#let settings = (footer-id: "OTHER")\n'}
    pdf = transform(example_pdf(), drop)
    found = messages(run_rule(context(tmp_path, pdf, files), "sat.layout.header-footer"))
    assert any(m.startswith(f"{page_name(contents.page)}: the first header line") for m in found)
    footers = len(pdf.pages) - 1
    assert sum("footer must start with the footer-id 'OTHER'" in m for m in found) == footers


def test_header_footer_report_a_footer_id_that_is_not_centered(tmp_path: Path) -> None:
    index = heading_page("Einleitung")

    def shift(page: PdfPage, char: PdfChar) -> PdfChar:
        footer = pdflines.region_of(page, char) is pdflines.Region.FOOTER
        if page.index == index and footer and char.x1 < 400:
            return dataclasses.replace(char, x0=char.x0 - 40, x1=char.x1 - 40)
        return char

    pdf = transform(example_pdf(), shift)
    found = messages(run_rule(context(tmp_path, pdf), "sat.layout.header-footer"))
    assert found == [f"{page_name(index)}: the footer-id is not centered on the text block"]


def test_page_numbers_report_a_missing_page(tmp_path: Path) -> None:
    pdf = example_pdf()
    shorter = dataclasses.replace(pdf, pages=pdf.pages[:-1])
    found = messages(run_rule(context(tmp_path, shorter), "sat.layout.page-numbers"))
    assert len(found) == len(shorter.pages) - 1
    assert f"Expected 'Seite 1 von {len(shorter.pages)}'" in found[0]


def move_headings(index: int) -> PdfDocument:
    """Move the level-1 headings of a page 300 pt down, below other body text."""

    def move(page: PdfPage, char: PdfChar) -> PdfChar:
        if page.index == index and char.size > 15:
            return dataclasses.replace(char, top=char.top + 300, bottom=char.bottom + 300)
        return char

    return transform(example_pdf(), move)


def test_chapter_pagebreak_reports_a_heading_below_text(tmp_path: Path) -> None:
    index = heading_page("Ergebnisse")
    pdf = move_headings(index)
    found = messages(run_rule(context(tmp_path, pdf), "sat.layout.chapter-pagebreak"))
    assert len(found) == 1
    assert found[0].startswith(
        f"{page_name(index)}: the heading '3 Ergebnisse' does not start a new page"
    )


def test_chapter_pagebreak_reports_contents_below_text(tmp_path: Path) -> None:
    index = heading_page("Inhalt")
    assert heading_page("Glossar") == index
    pdf = move_headings(index)
    found = messages(run_rule(context(tmp_path, pdf), "sat.layout.chapter-pagebreak"))
    assert found == [
        " ".join(
            (
                f"{page_name(index)}: the heading 'Inhalt' does not start a new page.",
                "Start each level-1 heading on a new page",
            )
        )
    ]


def test_justified_reports_a_ragged_line(tmp_path: Path) -> None:
    target = first_text_line()

    def squeeze(page: PdfPage, char: PdfChar) -> PdfChar:
        if on_line(page, char, target):
            left = 113.385826
            return dataclasses.replace(
                char, x0=left + (char.x0 - left) * 0.8, x1=left + (char.x1 - left) * 0.8
            )
        return char

    pdf = transform(example_pdf(), squeeze)
    found = messages(run_rule(context(tmp_path, pdf), "sat.layout.justified"))
    assert len(found) == 1
    assert found[0].startswith(f"{page_name(target.page)}: the line 'Das hier")


def test_footnote_lines_report_a_long_footnote(tmp_path: Path) -> None:
    found = messages(run_rule(context(tmp_path, example_pdf()), "sat.footnote-lines", max_lines=1))
    assert found == ["footnote 1 has 2 lines. Use at most 1 lines"]
