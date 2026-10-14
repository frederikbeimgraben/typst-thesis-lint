"""Core data types: severities, locations, diagnostics and source references."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class Severity(StrEnum):
    """Severity of a finding. An error makes the run fail."""

    ERROR = "error"
    WARNING = "warning"


class Needs(StrEnum):
    """Input that a rule needs. The LSP server runs only `SOURCE` rules."""

    SOURCE = "source"
    PDF = "pdf"
    SOURCES_DIR = "sources-dir"


@dataclass(frozen=True, slots=True)
class Location:
    """A range in a file. Lines and columns start at 1. Columns count characters."""

    path: Path
    line: int = 1
    column: int = 1
    end_line: int | None = None
    end_column: int | None = None


@dataclass(frozen=True, slots=True)
class SourceRef:
    """The guideline or book passage that a rule comes from."""

    source: str
    page: str
    quote: str = ""


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One finding of one rule."""

    rule_id: str
    severity: Severity
    message: str
    location: Location
    notes: tuple[str, ...] = field(default=())

    def format(self, root: Path) -> str:
        """Return the finding as `path:line:column: severity [rule] message`."""
        try:
            shown = self.location.path.relative_to(root)
        except ValueError:
            shown = self.location.path
        loc = self.location
        return f"{shown}:{loc.line}:{loc.column}: {self.severity} [{self.rule_id}] {self.message}"
