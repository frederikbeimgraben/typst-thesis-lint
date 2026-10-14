"""The context that every check gets: project, profile, milestone and the PDF."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from thesis_lint.config import Config
    from thesis_lint.pdf import PdfDocument
    from thesis_lint.project import Project
    from thesis_lint.typst.document import Heading, Unit


class Profile(StrEnum):
    """Check profile. In `draft`, submission rules report warnings instead of errors."""

    DRAFT = "draft"
    FINAL = "final"


class Milestone(StrEnum):
    """SAT milestone of the submission."""

    EW = "ew"
    FA = "fa"
    SA32 = "sa32"


class PdfUnavailableError(Exception):
    """The PDF is not available, for example because the compilation failed."""


@dataclass(slots=True)
class Context:
    """Inputs of one lint run."""

    config: Config
    project: Project
    profile: Profile = Profile.DRAFT
    milestone: Milestone | None = None
    ci: bool = False
    pdf_provider: Callable[[], PdfDocument] | None = None
    _pdf: PdfDocument | None = field(default=None, init=False)
    _pdf_error: Exception | None = field(default=None, init=False)

    @property
    def root(self) -> Path:
        """Return the project root."""
        return self.config.root

    @property
    def pdf(self) -> PdfDocument:
        """Return the compiled PDF. Compile it on first use. Raise the same error again later."""
        if self._pdf_error is not None:
            raise self._pdf_error
        if self._pdf is None:
            if self.pdf_provider is None:
                self._pdf_error = PdfUnavailableError("no PDF in this run")
                raise self._pdf_error
            try:
                self._pdf = self.pdf_provider()
            except Exception as exc:
                self._pdf_error = exc
                raise
        return self._pdf

    def heading_by_title(self, title: str, level: int = 1) -> Heading | None:
        """Return the first heading with this title and level, or None."""
        return next(
            (h for h in self.project.document.headings if h.level == level and h.text == title),
            None,
        )

    def body_units(self, excluded_titles: frozenset[str] | None = None) -> Iterator[Unit]:
        """Yield the prose units, except the units under level-1 headings in `excluded_titles`."""
        excluded = excluded_titles or frozenset()
        return (
            unit
            for unit in self.project.document.prose_units()
            if unit.heading is None or top_heading(unit.heading).text not in excluded
        )


def top_heading(heading: Heading) -> Heading:
    """Return the level-1 ancestor of a heading, or the heading itself."""
    return next((h for h in heading.ancestors() if h.parent is None), heading)
