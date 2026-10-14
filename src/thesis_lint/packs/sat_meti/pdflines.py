"""Read text lines from the compiled PDF of the SAT layout.

The SAT rules that read the PDF work on lines, not on single glyphs. A line
holds the glyphs with the same vertical position. The helpers put spaces
between words, sort the lines into header, body and footer, and join
hyphenated words again.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import TYPE_CHECKING

from thesis_lint.pdf import POINTS_PER_CM

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from thesis_lint.pdf import PdfChar, PdfDocument, PdfPage

# The page geometry of the SAT template variant.
LEFT_CM = 4.0
RIGHT_CM = 3.0
TOP_CM = 3.0
BOTTOM_CM = 2.0

# The font sizes of the SAT template variant, in points.
TITLE_PT = 24.0
NORMAL_PT = 12.0
H1_PT = 16.0
H2_PT = 14.0
LISTS_PT = 10.0
HEADER_PT = 10.0
FOOTER_PT = 10.0
FOOTNOTE_PT = 10.0
ABSTRACT_PT = 10.0
SIZE_TOLERANCE_PT = 0.3

# The titles of the six lists in the order of the template.
LIST_TITLES = (
    "Inhalt",
    "Abbildungsverzeichnis",
    "Tabellenverzeichnis",
    "Formelverzeichnis",
    "Abkürzungsverzeichnis",
    "Glossar",
)

# Fonts for math and code. The layout rules do not check them.
EXEMPT_FONTS = ("NewCMMath", "NewCM", "DejaVuSansMono", "DejaVuMath")

POINTS_PER_MM = POINTS_PER_CM / 10

_SPACES = frozenset({" ", " ", " ", " ", " ", " "})
_HEADING_NUMBER = re.compile(r"^\d+(?:\.\d+)*\s+")
_HYPHENS = "-­‐"


class Region(StrEnum):
    """The part of a page that holds a line."""

    HEADER = "header"
    BODY = "body"
    FOOTER = "footer"


@dataclass(frozen=True, slots=True)
class Line:
    """A text line of one page. Coordinates are in points from the top left corner."""

    page: int
    region: Region
    chars: tuple[PdfChar, ...]
    text: str
    top: float
    bottom: float
    x0: float
    x1: float
    size: float

    @property
    def ink(self) -> tuple[PdfChar, ...]:
        """Return the glyphs that are not white space."""
        return tuple(char for char in self.chars if not is_space(char.text))

    @property
    def fonts(self) -> frozenset[str]:
        """Return the font names of the glyphs that are not white space."""
        return frozenset(char.font for char in self.ink)

    def has_size(self, points: float, tolerance: float = SIZE_TOLERANCE_PT) -> bool:
        """Return True if the main font size of the line is `points`."""
        return abs(self.size - points) <= tolerance

    @property
    def title(self) -> str:
        """Return the text without a leading heading number, for example `2.1 `."""
        return _HEADING_NUMBER.sub("", self.text).strip()


def is_space(text: str) -> bool:
    """Return True if a glyph text is white space or empty."""
    return not text.strip() or all(char in _SPACES for char in text)


def font_matches(font: str, prefixes: Iterable[str]) -> bool:
    """Return True if the PDF font name starts with one of the prefixes.

    The comparison ignores spaces and case. For example, `LibreFranklin-Bold`
    matches the prefix `Libre Franklin`.
    """
    name = font.replace(" ", "").lower()
    return any(name.startswith(prefix.replace(" ", "").lower()) for prefix in prefixes)


def region_of(
    page: PdfPage, char: PdfChar, top_cm: float = TOP_CM, bottom_cm: float = BOTTOM_CM
) -> Region:
    """Return the region of a glyph from its vertical center and the page margins."""
    middle = (char.top + char.bottom) / 2
    if middle < top_cm * POINTS_PER_CM:
        return Region.HEADER
    if middle > page.height - bottom_cm * POINTS_PER_CM:
        return Region.FOOTER
    return Region.BODY


def page_lines(page: PdfPage, top_cm: float = TOP_CM, bottom_cm: float = BOTTOM_CM) -> list[Line]:
    """Return the lines of a page, from top to bottom."""
    return list(_build_lines(page, top_cm, bottom_cm))


def document_lines(
    pdf: PdfDocument, top_cm: float = TOP_CM, bottom_cm: float = BOTTOM_CM
) -> Iterator[Line]:
    """Yield the lines of all pages in reading order."""
    for page in pdf.pages:
        yield from _build_lines(page, top_cm, bottom_cm)


def _build_lines(page: PdfPage, top_cm: float, bottom_cm: float) -> Iterator[Line]:
    ordered = sorted(page.chars, key=lambda char: (char.top, char.x0))
    groups: list[list[PdfChar]] = []
    for char in ordered:
        last = groups[-1] if groups else None
        if last is not None and abs(char.top - last[0].top) <= max(0.3 * last[0].size, 1.0):
            last.append(char)
        else:
            groups.append([char])
    for group in groups:
        line = _line(page, sorted(group, key=lambda char: char.x0), top_cm, bottom_cm)
        if line is not None:
            yield line


def _line(page: PdfPage, chars: list[PdfChar], top_cm: float, bottom_cm: float) -> Line | None:
    ink = [char for char in chars if not is_space(char.text)]
    if not ink:
        return None
    sizes = Counter(round(char.size, 1) for char in ink)
    size = sizes.most_common(1)[0][0]
    regions = Counter(region_of(page, char, top_cm, bottom_cm) for char in ink)
    return Line(
        page=page.index,
        region=regions.most_common(1)[0][0],
        chars=tuple(chars),
        text=_text(chars),
        top=min(char.top for char in ink),
        bottom=max(char.bottom for char in ink),
        x0=min(char.x0 for char in ink),
        x1=max(char.x1 for char in ink),
        size=size,
    )


def _text(chars: Sequence[PdfChar]) -> str:
    """Return the text of sorted glyphs. Put a space where the gap is wide."""
    parts: list[str] = [_glyph(chars[0].text)] if chars else []
    for previous, current in pairwise(chars):
        gap = current.x0 - previous.x1
        wide = gap > 0.15 * max(previous.size, current.size)
        if wide and not is_space(previous.text) and not is_space(current.text):
            parts.append(" ")
        parts.append(_glyph(current.text))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _glyph(text: str) -> str:
    if is_space(text):
        return " "
    # Typst maps the hyphen glyph to a soft hyphen in some fonts.
    return text.replace("­", "-")


def join_lines(lines: Iterable[Line]) -> str:
    """Join the texts of lines. Join a word again that a hyphen breaks at the line end."""
    result = ""
    for line in lines:
        text = line.text
        if not result:
            result = text
            continue
        hyphenated = len(result) > 1 and result[-1] in _HYPHENS and result[-2].isalpha()
        if hyphenated and text[:1].islower():
            result = result[:-1] + text
        elif hyphenated and text[:1].isalpha():
            result += text
        else:
            result += " " + text
    return result


def count_words(text: str) -> int:
    """Count the words. A word is a token between spaces with a letter or a digit."""
    return sum(1 for token in text.split() if any(char.isalnum() for char in token))


def heading_number_free(line: Line) -> str:
    """Return the line text without a heading number in front of a wide gap.

    The SAT layout puts the heading number into a separate grid cell. The
    number does not count as a word.
    """
    ink = line.ink
    if len(ink) < 2:
        return line.text
    number = _HEADING_NUMBER.match(line.text)
    if number is None:
        return line.text
    digits = len(number.group(0).replace(" ", ""))
    if digits >= len(ink):
        return line.text
    gap = ink[digits].x0 - ink[digits - 1].x1
    return line.text[number.end() :] if gap >= 0.5 * line.size else line.text


def body_lines(lines: Iterable[Line]) -> list[Line]:
    """Return the body lines."""
    return [line for line in lines if line.region is Region.BODY]


def first_body_line(pdf: PdfDocument, index: int) -> Line | None:
    """Return the first body line of a page, or None."""
    if index >= len(pdf.pages):
        return None
    return next(iter(body_lines(page_lines(pdf.pages[index]))), None)


def is_chapter_heading(
    line: Line, h1_pt: float = H1_PT, tolerance: float = SIZE_TOLERANCE_PT
) -> bool:
    """Return True if the line is a level-1 heading of the body (not the title page)."""
    return line.page > 0 and line.region is Region.BODY and line.has_size(h1_pt, tolerance)


def chapter_headings(
    pdf: PdfDocument, h1_pt: float = H1_PT, tolerance: float = SIZE_TOLERANCE_PT
) -> list[Line]:
    """Return the first line of each level-1 heading. A wrapped heading has more lines."""
    result: list[Line] = []
    previous: Line | None = None
    for line in document_lines(pdf):
        if not is_chapter_heading(line, h1_pt, tolerance):
            if line.region is Region.BODY:
                previous = None
            continue
        if previous is None or previous.page != line.page:
            result.append(line)
        previous = line
    return result


def find_heading(
    pdf: PdfDocument,
    title: str,
    h1_pt: float = H1_PT,
    tolerance: float = SIZE_TOLERANCE_PT,
) -> Line | None:
    """Return the first level-1 heading line with this title, or None."""
    return next(
        (
            line
            for line in chapter_headings(pdf, h1_pt, tolerance)
            if normalize(line.title) == normalize(title)
        ),
        None,
    )


def normalize(text: str) -> str:
    """Collapse white space and remove soft hyphens."""
    return re.sub(r"\s+", " ", text.replace("­", "")).strip()


def lines_between(
    pdf: PdfDocument,
    start: Line,
    stop: Line | None,
    *,
    top_cm: float = TOP_CM,
    bottom_cm: float = BOTTOM_CM,
) -> list[Line]:
    """Return the body lines from `start` up to `stop`. `stop` is not in the result."""
    result: list[Line] = []
    active = False
    for line in document_lines(pdf, top_cm, bottom_cm):
        if _same_place(line, start):
            active = True
        if stop is not None and _same_place(line, stop):
            break
        if active and line.region is Region.BODY:
            result.append(line)
    return result


def excerpt(text: str, length: int = 40) -> str:
    """Return the start of a text for a message."""
    return text if len(text) <= length else text[: length - 3] + "..."


def _same_place(line: Line, other: Line) -> bool:
    return line.page == other.page and line.top == other.top and line.x0 == other.x0
