"""SAT rules for the layout of the compiled PDF."""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

from thesis_lint.core.sources import USER, VL02, VORLAGE, ref
from thesis_lint.model import Needs, Severity
from thesis_lint.packs.sat_meti import pdflines
from thesis_lint.packs.sat_meti.pdflines import (
    POINTS_PER_MM,
    Line,
    Region,
    excerpt,
    font_matches,
    normalize,
)
from thesis_lint.packs.sat_meti.support import main_location
from thesis_lint.pdf import POINTS_PER_CM
from thesis_lint.registry import Finding, rule
from thesis_lint.typst.document import UnitKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from thesis_lint.context import Context
    from thesis_lint.pdf import PdfDocument


def _page_name(index: int) -> str:
    return f"PDF page {index + 1}"


def _pdf_finding(ctx: Context, index: int, message: str) -> Finding:
    return Finding(f"{_page_name(index)}: {message}", main_location(ctx))


def _all_lines(pdf: PdfDocument, top_cm: float, bottom_cm: float) -> list[list[Line]]:
    return [pdflines.page_lines(page, top_cm, bottom_cm) for page in pdf.pages]


def _chapter_of_lines(
    pages: list[list[Line]], h1_pt: float, tolerance: float
) -> Iterator[tuple[Line, Line | None]]:
    """Yield each line with the first line of its level-1 heading. Wrapped headings count once."""
    chapter: Line | None = None
    previous_heading = False
    for lines in pages:
        for line in lines:
            heading = pdflines.is_chapter_heading(line, h1_pt, tolerance)
            if heading and not (previous_heading and chapter is not None):
                chapter = line
            if line.region is Region.BODY:
                previous_heading = heading
            yield line, chapter
        previous_heading = False


# ---------------------------------------------------------------------------
# Margins
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MarginsParams:
    """Parameters of `sat.layout.margins`."""

    left_cm: float = pdflines.LEFT_CM
    right_cm: float = pdflines.RIGHT_CM
    top_cm: float = pdflines.TOP_CM
    bottom_cm: float = pdflines.BOTTOM_CM
    page_width_cm: float = 21.0
    page_height_cm: float = 29.7
    tolerance_mm: float = 1.0
    abstract_page: int = 1
    abstract_left_cm: float = 2.5
    abstract_right_cm: float = 2.0


@rule(
    "sat.layout.margins",
    summary="A4 portrait. The text is inside the margins (left 4, right 3, top 3, bottom 2 cm).",
    severity=Severity.ERROR,
    sources=[
        ref(VORLAGE, "Seitenformat", "DinA4, hochkant"),
        ref(
            VORLAGE,
            "Seitenränder",
            "Linker Rand: 4 cm Rechter Rand: 3 cm Oberer Rand: 3 cm Unterer Rand: 2 cm",
        ),
    ],
    params=MarginsParams(),
    needs=Needs.PDF,
)
def margins(ctx: Context, params: MarginsParams) -> Iterator[Finding]:
    """Check the page size and the position of the body text and of header and footer."""
    tolerance = params.tolerance_mm * POINTS_PER_MM
    for page, lines in zip(
        ctx.pdf.pages, _all_lines(ctx.pdf, params.top_cm, params.bottom_cm), strict=True
    ):
        width = params.page_width_cm * POINTS_PER_CM
        height = params.page_height_cm * POINTS_PER_CM
        if abs(page.width - width) > tolerance or abs(page.height - height) > tolerance:
            yield _pdf_finding(
                ctx,
                page.index,
                " ".join(
                    (
                        f"the page size is {page.width / POINTS_PER_CM:.1f} x",
                        f"{page.height / POINTS_PER_CM:.1f} cm. Use A4 portrait",
                    )
                ),
            )
        # The style "Abstract" of the Word template reaches into both margins.
        abstract = page.index == params.abstract_page
        left_cm = params.abstract_left_cm if abstract else params.left_cm
        right_cm = params.abstract_right_cm if abstract else params.right_cm
        box = _Box(
            left=left_cm * POINTS_PER_CM - tolerance,
            right=page.width - right_cm * POINTS_PER_CM + tolerance,
            top=params.top_cm * POINTS_PER_CM - tolerance,
            bottom=page.height - params.bottom_cm * POINTS_PER_CM + tolerance,
        )
        first = {side: line for line in reversed(lines) for side in _outside(line, box)}
        yield from (
            _pdf_finding(
                ctx,
                page.index,
                " ".join(
                    (
                        f"the text {excerpt(line.text)!r} is in the {side} margin.",
                        "Keep the text inside the page margins",
                    )
                ),
            )
            for side, line in sorted(first.items())
        )


@dataclass(frozen=True, slots=True)
class _Box:
    left: float
    right: float
    top: float
    bottom: float


def _outside(line: Line, box: _Box) -> Iterator[str]:
    """Yield the margins that a line goes into."""
    if line.x0 < box.left:
        yield "left"
    if _letters_right(line) > box.right:
        yield "right"
    if line.region is Region.BODY and line.top < box.top:
        yield "top"
    if line.region is Region.BODY and line.bottom > box.bottom:
        yield "bottom"


def _letters_right(line: Line) -> float:
    """Return the right edge of the letters and digits. Punctuation can hang in the margin."""
    return max((char.x1 for char in line.ink if char.text.isalnum()), default=line.x0)


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FontsParams:
    """Parameters of `sat.layout.fonts`."""

    text_fonts: tuple[str, ...] = ("Libre Franklin", "Franklin Gothic")
    serif_fonts: tuple[str, ...] = ("TeX Gyre Termes", "Times New Roman")
    exempt_fonts: tuple[str, ...] = pdflines.EXEMPT_FONTS
    abstract_page: int = 1
    caption_pattern: str = r"^(Abbildung|Tabelle|Formel) [\d.]+ : "
    list_titles: tuple[str, ...] = pdflines.LIST_TITLES


@rule(
    "sat.layout.fonts",
    summary="Text in Libre Franklin. Abstract and captions in TeX Gyre Termes or Times.",
    severity=Severity.ERROR,
    sources=[
        ref(VORLAGE, "Zeichenformate", "Standardtext: 12 Punkte Franklin Gothic Book"),
        ref(VORLAGE, "Zeichenformate", "Abstract: 10 Punkte Times New Roman kursiv"),
        ref(USER, "Template variant", "Libre Franklin ersetzt Franklin Gothic Book"),
    ],
    params=FontsParams(),
    needs=Needs.PDF,
)
def fonts(ctx: Context, params: FontsParams) -> Iterator[Finding]:
    """Report unknown fonts, and an abstract or a caption that is not in the serif font."""
    known = params.text_fonts + params.serif_fonts + params.exempt_fonts
    caption = re.compile(params.caption_pattern)
    pages = _all_lines(ctx.pdf, pdflines.TOP_CM, pdflines.BOTTOM_CM)
    lists = {normalize(title) for title in params.list_titles}
    in_lists = {
        (line.page, line.top)
        for line, chapter in _chapter_of_lines(pages, pdflines.H1_PT, pdflines.SIZE_TOLERANCE_PT)
        if chapter is not None and normalize(chapter.title) in lists
    }
    unknown = [
        (line.page, char)
        for lines in pages
        for line in lines
        for char in line.ink
        if not font_matches(char.font, known)
    ]
    if unknown:
        page, first = unknown[0]
        yield _pdf_finding(
            ctx,
            page,
            " ".join(
                (
                    f"the PDF uses the fonts {', '.join(sorted({c.font for _, c in unknown}))},",
                    f"for example for {first.text!r}. Use {' or '.join(params.text_fonts)}.",
                    "If the font is missing, add the template font folder to [paths] font-paths.",
                    "If the font has no such glyph, use another character",
                )
            ),
        )
    for lines in pages:
        serif_lines = [
            line
            for line in _caption_lines(lines, caption)
            if line.page > 0
            and (line.page, line.top) not in in_lists
            and not _all_serif(line, params)
            and not (line.page == params.abstract_page and line.region is Region.BODY)
        ]
        abstract = [
            line
            for line in lines
            if line.page == params.abstract_page
            and line.region is Region.BODY
            and not _all_serif(line, params)
        ]
        if abstract:
            yield _pdf_finding(
                ctx,
                lines[0].page,
                " ".join(
                    (
                        f"the abstract text {excerpt(abstract[0].text)!r} is not in",
                        f"{' or '.join(params.serif_fonts)}. Use the serif font for the abstract",
                    )
                ),
            )
        if serif_lines:
            yield _pdf_finding(
                ctx,
                lines[0].page,
                " ".join(
                    (
                        f"the caption {excerpt(serif_lines[0].text)!r} is not in",
                        f"{' or '.join(params.serif_fonts)}. Use the serif font for captions",
                    )
                ),
            )


def _all_serif(line: Line, params: FontsParams) -> bool:
    return all(font_matches(font, params.serif_fonts + params.exempt_fonts) for font in line.fonts)


def _caption_lines(lines: Iterable[Line], caption: re.Pattern[str]) -> Iterator[Line]:
    """Yield the caption lines. A wrapped caption has more lines with a small line gap."""
    previous: Line | None = None
    for line in lines:
        start = line.region is Region.BODY and caption.search(line.text) is not None
        follows = (
            previous is not None
            and line.region is Region.BODY
            and line.fonts == previous.fonts
            and line.top - previous.top <= 1.5 * line.size
        )
        if start or follows:
            yield line
            previous = line
        else:
            previous = None


# ---------------------------------------------------------------------------
# Font sizes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FontSizesParams:
    """Parameters of `sat.layout.font-sizes`."""

    title_pt: float = pdflines.TITLE_PT
    normal_pt: float = pdflines.NORMAL_PT
    h1_pt: float = pdflines.H1_PT
    h2_pt: float = pdflines.H2_PT
    lists_pt: float = pdflines.LISTS_PT
    header_pt: float = pdflines.HEADER_PT
    footer_pt: float = pdflines.FOOTER_PT
    footnote_pt: float = pdflines.FOOTNOTE_PT
    abstract_pt: float = pdflines.ABSTRACT_PT
    tolerance_pt: float = pdflines.SIZE_TOLERANCE_PT
    abstract_page: int = 1
    list_titles: tuple[str, ...] = pdflines.LIST_TITLES
    exempt_fonts: tuple[str, ...] = pdflines.EXEMPT_FONTS


@rule(
    "sat.layout.font-sizes",
    summary="The font sizes of the template: title 24, text 12, headings 16/14/12, lists 10 pt.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Zeichenformate",
            "Titel: 24 Punkte; Standardtext: 12 Punkte; Überschrift 1: 16 Punkte",
        ),
        ref(
            VORLAGE,
            "Zeichenformate",
            "Kopfzeilen: 12 Punkte; Fußzeilen: 10 Punkte; Fußnoten: 10 Punkte",
        ),
        ref(
            VORLAGE,
            "Formatvorlage Kopfzeile",
            "10 Punkte, zentriert (so rendert die Vorlage; Projektentscheidung)",
        ),
    ],
    params=FontSizesParams(),
    needs=Needs.PDF,
)
def font_sizes(ctx: Context, params: FontSizesParams) -> Iterator[Finding]:
    """Compare the size of each glyph with the sizes that its part of the document allows."""
    pages = _all_lines(ctx.pdf, pdflines.TOP_CM, pdflines.BOTTOM_CM)
    lists = {normalize(title) for title in params.list_titles}
    reported: set[tuple[int, Region]] = set()
    for line, chapter in _chapter_of_lines(pages, params.h1_pt, params.tolerance_pt):
        allowed = _allowed_sizes(line, chapter, params, lists)
        wrong = next(
            (
                char
                for char in line.ink
                if not font_matches(char.font, params.exempt_fonts)
                and all(abs(char.size - size) > params.tolerance_pt for size in allowed)
            ),
            None,
        )
        if wrong is None or (line.page, line.region) in reported:
            continue
        reported.add((line.page, line.region))
        sizes = " or ".join(f"{size:g} pt" for size in sorted(set(allowed)))
        yield _pdf_finding(
            ctx,
            line.page,
            " ".join(
                (
                    f"the {line.region} text {excerpt(line.text)!r} has {wrong.size:g} pt.",
                    f"Use {sizes}",
                )
            ),
        )
    title_page = pages[0] if pages else []
    largest = max((line.size for line in title_page), default=params.title_pt)
    if abs(largest - params.title_pt) > params.tolerance_pt:
        yield _pdf_finding(
            ctx, 0, f"the title has the size {largest:g} pt. Use {params.title_pt:g} pt"
        )


def _allowed_sizes(
    line: Line, chapter: Line | None, params: FontSizesParams, lists: set[str]
) -> tuple[float, ...]:
    if line.page == 0:
        return (params.title_pt, params.normal_pt)
    if line.region is Region.HEADER:
        return (params.header_pt,)
    if line.region is Region.FOOTER:
        return (params.footer_pt,)
    if line.page == params.abstract_page:
        return (params.abstract_pt,)
    if chapter is not None and normalize(chapter.title) in lists:
        return (params.h1_pt, params.lists_pt)
    return (params.normal_pt, params.h1_pt, params.h2_pt, params.footnote_pt)


# ---------------------------------------------------------------------------
# Header and footer
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HeaderFooterParams:
    """Parameters of `sat.layout.header-footer`."""

    header_text: str = "Hochschule Reutlingen – Fakultät Informatik – Studiengang meti"
    title_setting: str = "title"
    footer_setting: str = "footer-id"
    footer_pattern: str = r"Seite \d+ von \d+$"
    left_cm: float = pdflines.LEFT_CM
    right_cm: float = pdflines.RIGHT_CM
    top_cm: float = pdflines.TOP_CM
    bottom_cm: float = pdflines.BOTTOM_CM
    h1_pt: float = pdflines.H1_PT
    tolerance_mm: float = 1.0


@rule(
    "sat.layout.header-footer",
    summary="No header and footer on the title page. Template header and footer elsewhere.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Kopfzeile",
            "beinhaltet auch die Kapitelnummer und –überschrift der ersten Ebene",
        ),
        ref(
            VORLAGE,
            "Fußzeile",
            "Der Aufbau der Fußzeile erfolgt, mit Ausnahme der Titelseite, gemäß dem […] Beispiel.",
        ),
    ],
    params=HeaderFooterParams(),
    needs=Needs.PDF,
)
def header_footer(ctx: Context, params: HeaderFooterParams) -> Iterator[Finding]:
    """Check the header lines, the chapter line and the footer of each page."""
    pdf = ctx.pdf
    pages = _all_lines(pdf, params.top_cm, params.bottom_cm)
    chapters = {
        line.page: chapter
        for line, chapter in _chapter_of_lines(pages, params.h1_pt, pdflines.SIZE_TOLERANCE_PT)
    }
    for lines in pages:
        if not lines:
            continue
        index = lines[0].page
        header = [line for line in lines if line.region is Region.HEADER]
        footer = [line for line in lines if line.region is Region.FOOTER]
        if index == 0:
            if header or footer:
                yield _pdf_finding(ctx, 0, "the title page has a header or a footer. Remove it")
            continue
        width = pdf.pages[index].width
        yield from (
            _pdf_finding(ctx, index, message)
            for message in _header_problems(ctx, header, chapters.get(index), params, width)
        )
        yield from (
            _pdf_finding(ctx, index, message)
            for message in _footer_problems(ctx, footer, params, width)
        )


def _header_problems(
    ctx: Context,
    header: list[Line],
    chapter: Line | None,
    params: HeaderFooterParams,
    width: float,
) -> Iterator[str]:
    texts = [line.text for line in header]
    if not texts or normalize(texts[0]) != normalize(params.header_text):
        yield f"the first header line must be {params.header_text!r}"
        return
    title = ctx.project.setting_text(params.title_setting)
    rest = normalize(pdflines.join_lines(header[1:]))
    if title is not None and not rest.startswith(normalize(title)):
        yield f"the second header line must be the title {excerpt(normalize(title))!r}"
    numbered = chapter is not None and chapter.title != chapter.text
    if numbered and chapter is not None and not rest.endswith(normalize(chapter.text)):
        yield f"the last header line must be the chapter {chapter.text!r}"
    middle = (params.left_cm * POINTS_PER_CM + width - params.right_cm * POINTS_PER_CM) / 2
    tolerance = params.tolerance_mm * POINTS_PER_MM
    off = next((line for line in header if abs((line.x0 + line.x1) / 2 - middle) > tolerance), None)
    if off is not None:
        yield f"the header line {excerpt(off.text)!r} is not centered"


def _footer_problems(
    ctx: Context, footer: list[Line], params: HeaderFooterParams, width: float
) -> Iterator[str]:
    if len(footer) != 1:
        yield f"the footer has {len(footer)} lines. Use one line: <footer-id> Seite X von Y"
        return
    line = footer[0]
    tolerance = params.tolerance_mm * POINTS_PER_MM
    footer_id = ctx.project.setting_text(params.footer_setting)
    if footer_id is not None and not line.text.startswith(footer_id.strip()):
        yield f"the footer must start with the footer-id {footer_id.strip()!r}"
    middle = (params.left_cm * POINTS_PER_CM + width - params.right_cm * POINTS_PER_CM) / 2
    id_glyphs = line.ink[: len("".join((footer_id or "").split()))]
    if id_glyphs and abs((id_glyphs[0].x0 + id_glyphs[-1].x1) / 2 - middle) > tolerance:
        yield "the footer-id is not centered on the text block"
    if re.search(params.footer_pattern, line.text) is None:
        yield f"the footer {line.text!r} does not end with 'Seite X von Y'"
    elif abs(line.x1 - (width - params.right_cm * POINTS_PER_CM)) > tolerance:
        yield "the page number does not end at the right margin"


# ---------------------------------------------------------------------------
# Page numbers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PageNumbersParams:
    """Parameters of `sat.layout.page-numbers`."""

    footer_pattern: str = r"Seite (\d+) von (\d+)\s*$"
    first_list_title: str = "Inhalt"
    first_list_page: int = 2


@rule(
    "sat.layout.page-numbers",
    summary="The title page is page 0. The footer shows the page index and the PDF page count.",
    severity=Severity.ERROR,
    sources=[
        ref(VORLAGE, "Seitennummerierung", "Die Zählung beginnt bei 0 für das Titelblatt"),
        ref(USER, "Template variant", "Abstract Seite 1, erste Verzeichnisseite Seite 2"),
    ],
    params=PageNumbersParams(),
    needs=Needs.PDF,
)
def page_numbers(ctx: Context, params: PageNumbersParams) -> Iterator[Finding]:
    """Read "Seite X von Y" from each footer and compare it with the page index."""
    pdf = ctx.pdf
    pattern = re.compile(params.footer_pattern)
    total = len(pdf.pages)
    for page in pdf.pages:
        footer = pdflines.join_lines(
            line for line in pdflines.page_lines(page) if line.region is Region.FOOTER
        )
        match = pattern.search(footer)
        if page.index == 0:
            if match is not None:
                yield _pdf_finding(ctx, 0, "the title page has a page number. Remove it")
            continue
        if match is None:
            yield _pdf_finding(ctx, page.index, "the page has no page number 'Seite X von Y'")
            continue
        number, count = int(match.group(1)), int(match.group(2))
        if number != page.index or count != total:
            yield _pdf_finding(
                ctx,
                page.index,
                " ".join(
                    (
                        f"the footer shows 'Seite {number} von {count}'.",
                        f"Expected 'Seite {page.index} von {total}' (the title page is page 0)",
                    )
                ),
            )
    first = pdflines.find_heading(pdf, params.first_list_title)
    if first is not None and first.page != params.first_list_page:
        yield _pdf_finding(
            ctx,
            first.page,
            " ".join(
                (
                    f"the list {params.first_list_title!r} starts on page {first.page}.",
                    f"It must start on page {params.first_list_page}, after the abstract page",
                )
            ),
        )


# ---------------------------------------------------------------------------
# Page breaks
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChapterPagebreakParams:
    """Parameters of `sat.layout.chapter-pagebreak`."""

    h1_pt: float = pdflines.H1_PT
    tolerance_pt: float = pdflines.SIZE_TOLERANCE_PT
    new_page_titles: tuple[str, ...] = ("Inhalt",)


@rule(
    "sat.layout.chapter-pagebreak",
    summary="Each numbered level-1 heading and the contents page start on a new page.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Gliederung des Textes",
            "muss mit einer neuen Seite begonnen werden",
        )
    ],
    params=ChapterPagebreakParams(),
    needs=Needs.PDF,
)
def chapter_pagebreak(ctx: Context, params: ChapterPagebreakParams) -> Iterator[Finding]:
    """Report level-1 headings with other body text above them on the same page.

    Only numbered chapters and the headings in `new_page_titles` must start a
    new page. The other lists follow the contents page without a page break.
    """
    titles = {normalize(title) for title in params.new_page_titles}
    headings = [
        heading
        for heading in pdflines.chapter_headings(ctx.pdf, params.h1_pt, params.tolerance_pt)
        if heading.title != heading.text or normalize(heading.title) in titles
    ]
    for heading in headings:
        lines = pdflines.body_lines(pdflines.page_lines(ctx.pdf.pages[heading.page]))
        above = [line for line in lines if line.top < heading.top]
        if any(not line.has_size(params.h1_pt, params.tolerance_pt) for line in above):
            yield _pdf_finding(
                ctx,
                heading.page,
                " ".join(
                    (
                        f"the heading {heading.text!r} does not start a new page.",
                        "Start each level-1 heading on a new page",
                    )
                ),
            )


# ---------------------------------------------------------------------------
# Justified text
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JustifiedParams:
    """Parameters of `sat.layout.justified`."""

    right_cm: float = pdflines.RIGHT_CM
    tolerance_mm: float = 1.0
    normal_pt: float = pdflines.NORMAL_PT
    text_fonts: tuple[str, ...] = ("Libre Franklin", "Franklin Gothic")
    start_heading: str = "Einleitung"
    skipped_chapters: tuple[str, ...] = ("Literaturverzeichnis",)
    min_width_ratio: float = 0.6
    max_gap_em: float = 2.0


_ITEM_START = re.compile(r"^(?:[•‣◦–-]|\d+[.)])\s")


@rule(
    "sat.layout.justified",
    summary="The text is justified. Each line except the last of a paragraph ends at the margin.",
    severity=Severity.ERROR,
    sources=[
        ref(USER, "Template variant", "BLOCKSATZ (Formatvorlage Standard justify)"),
        ref(
            VORLAGE,
            "Textabsätze",
            "dass jede Zeile möglichst bis zum Zeilenrand beschrieben ist",
        ),
        ref(
            VL02,
            "Folie 103",
            "Blocksatz verwenden oder Worttrennung durchführen, wenn Flattersatz zu extrem",
        ),
    ],
    params=JustifiedParams(),
    needs=Needs.PDF,
)
def justified(ctx: Context, params: JustifiedParams) -> Iterator[Finding]:
    """Group the body lines into paragraphs and check the right edge of the inner lines."""
    pdf = ctx.pdf
    pages = _all_lines(pdf, pdflines.TOP_CM, pdflines.BOTTOM_CM)
    started = False
    skipped = {normalize(title) for title in params.skipped_chapters}
    candidates: list[list[Line]] = [[] for _ in pages]
    for line, chapter in _chapter_of_lines(pages, pdflines.H1_PT, pdflines.SIZE_TOLERANCE_PT):
        if chapter is not None and normalize(chapter.title) == normalize(params.start_heading):
            started = True
        in_skipped = chapter is not None and normalize(chapter.title) in skipped
        if started and not in_skipped and _is_prose(line, params):
            candidates[line.page].append(line)
    reported: set[int] = set()
    for lines in candidates:
        for current, following in pairwise(lines):
            if current.page in reported or not _same_paragraph(current, following):
                continue
            edge = pdf.pages[current.page].width - params.right_cm * POINTS_PER_CM
            text_width = edge - min(line.x0 for line in lines)
            gap = edge - current.x1
            wide = current.x1 - current.x0 >= params.min_width_ratio * text_width
            if wide and gap > params.tolerance_mm * POINTS_PER_MM:
                reported.add(current.page)
                yield _pdf_finding(
                    ctx,
                    current.page,
                    " ".join(
                        (
                            f"the line {excerpt(current.text)!r} does not end at the right margin.",
                            "Use justified text",
                        )
                    ),
                )


def _is_prose(line: Line, params: JustifiedParams) -> bool:
    if line.region is not Region.BODY or not line.has_size(params.normal_pt):
        return False
    if not all(font_matches(font, params.text_fonts) for font in line.fonts):
        return False
    limit = params.max_gap_em * line.size
    return all(b.x0 - a.x1 <= limit for a, b in pairwise(line.ink))


def _same_paragraph(current: Line, following: Line) -> bool:
    close = following.top - current.top <= 1.4 * current.size
    new_item = _ITEM_START.match(following.text) is not None
    dedent = following.x0 < current.x0 - 1.0
    return close and not new_item and not dedent


# ---------------------------------------------------------------------------
# Footnotes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FootnoteLinesParams:
    """Parameters of `sat.footnote-lines`."""

    max_lines: int = 4
    footnote_pt: float = pdflines.FOOTNOTE_PT
    tolerance_pt: float = pdflines.SIZE_TOLERANCE_PT
    start_heading: str = "Einleitung"


@rule(
    "sat.footnote-lines",
    summary="A footnote has at most 4 lines.",
    severity=Severity.WARNING,
    sources=[ref(VORLAGE, "Fußnoten", "Die Fußnotentexte sollten nicht länger als 4 Zeilen sein.")],
    params=FootnoteLinesParams(),
    needs=Needs.PDF,
)
def footnote_lines(ctx: Context, params: FootnoteLinesParams) -> Iterator[Finding]:
    """Count the lines of each footnote in the footnote area at the bottom of the pages."""
    pdf = ctx.pdf
    start = pdflines.find_heading(pdf, params.start_heading)
    if start is None:
        return
    counts: dict[int, int] = {}
    number = 0
    for page in pdf.pages[start.page :]:
        for line in _footnote_area(pdflines.body_lines(pdflines.page_lines(page)), params):
            if line.text.startswith(str(number + 1)):
                number += 1
            if number:
                counts[number] = counts.get(number, 0) + 1
    footnotes = [u for u in ctx.project.document.units if u.kind is UnitKind.FOOTNOTE]
    for footnote, lines in sorted(counts.items()):
        if lines <= params.max_lines:
            continue
        unit = footnotes[footnote - 1] if footnote <= len(footnotes) else None
        yield Finding(
            f"footnote {footnote} has {lines} lines. Use at most {params.max_lines} lines",
            unit.start_location if unit is not None else main_location(ctx),
        )


def _footnote_area(lines: list[Line], params: FootnoteLinesParams) -> list[Line]:
    """Return the lines at the end of the page that have the footnote size."""
    area: list[Line] = []
    for line in reversed(lines):
        if not line.has_size(params.footnote_pt, params.tolerance_pt):
            break
        area.append(line)
    return area[::-1]
