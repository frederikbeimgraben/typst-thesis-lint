"""Compile the document with Typst and read the PDF with pdfplumber and pypdf."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, cast

import pdfplumber
import pypdf

if TYPE_CHECKING:
    from pathlib import Path

POINTS_PER_CM = 72 / 2.54


@dataclass(frozen=True, slots=True)
class PdfChar:
    """One glyph. Coordinates are in points, `top` from the top of the page."""

    text: str
    font: str
    size: float
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass(slots=True)
class PdfPage:
    """One page. `index` starts at 0."""

    index: int
    width: float
    height: float
    text: str
    chars: list[PdfChar] = field(default_factory=list[PdfChar])

    def body_chars(self, header_cm: float, footer_cm: float) -> list[PdfChar]:
        """Return the glyphs between the header area and the footer area."""
        top = header_cm * POINTS_PER_CM
        bottom = self.height - footer_cm * POINTS_PER_CM
        return [char for char in self.chars if char.top >= top and char.bottom <= bottom]


@dataclass(slots=True)
class PdfDocument:
    """The compiled document."""

    path: Path
    pages: list[PdfPage]
    encrypted: bool
    annotations_allowed: bool

    @property
    def text(self) -> str:
        """Return the text of all pages, separated by form feeds."""
        return "\f".join(page.text for page in self.pages)


class CompileError(Exception):
    """Typst could not compile the document."""


def compile_document(root: Path, main: Path, font_paths: list[Path], output: Path) -> Path:
    """Run `typst compile` and return the path of the PDF."""
    typst = shutil.which("typst")
    if typst is None:
        msg = "the typst executable is not on PATH"
        raise CompileError(msg)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [typst, "compile", "--root", str(root)]
    for path in font_paths:
        command.extend(["--font-path", str(path)])
    command.extend([str(main), str(output)])
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603 - fixed executable, no shell
    if result.returncode != 0:
        msg = result.stderr.strip() or "typst compile failed"
        raise CompileError(msg)
    return output


class _PlumberPage(Protocol):
    width: float
    height: float
    chars: list[dict[str, object]]

    def extract_text(self, *, x_tolerance: float) -> str | None: ...


class _PlumberPdf(Protocol):
    pages: list[_PlumberPage]

    def close(self) -> None: ...


def read_pdf(path: Path, *, x_tolerance: float = 3.0) -> PdfDocument:
    """Read the glyphs and the text of all pages, and the security settings.

    `x_tolerance` is the largest gap in points between two glyphs of one word.
    LaTeX PDFs often have no space glyphs, so a smaller value finds the word gaps.
    """
    reader = pypdf.PdfReader(str(path))
    encrypted = reader.is_encrypted
    annotations_allowed = True
    if encrypted:
        permissions = reader.user_access_permissions
        annotations_allowed = permissions is not None and bool(
            permissions & pypdf.constants.UserAccessPermissions.ADD_OR_MODIFY
        )
    pages: list[PdfPage] = []
    document = cast("_PlumberPdf", cast("object", pdfplumber.open(path)))
    try:
        for index, page in enumerate(document.pages):
            chars = [_char(raw) for raw in page.chars]
            pages.append(
                PdfPage(
                    index=index,
                    width=float(page.width),
                    height=float(page.height),
                    text=page.extract_text(x_tolerance=x_tolerance) or "",
                    chars=chars,
                )
            )
    finally:
        document.close()
    return PdfDocument(
        path=path, pages=pages, encrypted=encrypted, annotations_allowed=annotations_allowed
    )


def _char(raw: dict[str, object]) -> PdfChar:
    return PdfChar(
        text=str(raw.get("text", "")),
        font=_base_font(str(raw.get("fontname", ""))),
        size=_number(raw.get("size")),
        x0=_number(raw.get("x0")),
        x1=_number(raw.get("x1")),
        top=_number(raw.get("top")),
        bottom=_number(raw.get("bottom")),
    )


def _number(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _base_font(name: str) -> str:
    """Remove the subset prefix, for example `ABCDEF+LibreFranklin-Regular`."""
    if len(name) > 7 and name[6] == "+":
        return name[7:]
    return name
