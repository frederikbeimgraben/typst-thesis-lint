"""Rules for footnotes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from thesis_lint.core.prose import TEXT_KINDS, finding, is_hidden, masked, prose_units
from thesis_lint.core.sources import BRINK, HW, VORLAGE, ref
from thesis_lint.model import Severity
from thesis_lint.registry import Finding, NoParams, rule
from thesis_lint.typst.document import FOOTNOTE_MARK

if TYPE_CHECKING:
    from collections.abc import Iterator

    from thesis_lint.context import Context
    from thesis_lint.typst.document import Span, Unit

_OPENERS = " „‚\"'(["
_CLOSERS = " “”‘’\"'"


def footnote_marks(ctx: Context) -> Iterator[tuple[Unit, Span, Unit]]:
    """Yield each footnote mark with its unit and the footnote unit."""
    return (
        (unit, span, footnote)
        for unit in prose_units(ctx, TEXT_KINDS)
        for span, footnote in unit.footnotes
    )


def char_before(text: str, index: int) -> str:
    """Return the character before `index`. Skip other footnote marks."""
    position = index - 1
    while position >= 0 and text[position] == FOOTNOTE_MARK:
        position -= 1
    return text[position] if position >= 0 else ""


@dataclass(frozen=True, slots=True)
class PunctuationParams:
    """Characters that a footnote mark can follow."""

    after: tuple[str, ...] = (",", ";", ".", "?", "!", "–", "—")


@rule(
    "core.footnote.after-punctuation",
    summary="A footnote mark follows a punctuation mark.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Fußnoten",
            "grundsätzlich nach einem Satzzeichen (Komma, Strichpunkt, Punkt, (...))",
        )
    ],
    params=PunctuationParams(),
)
def after_punctuation(ctx: Context, params: PunctuationParams) -> Iterator[Finding]:
    """Report footnote marks that do not follow a punctuation mark."""
    allowed = frozenset(params.after)
    return (
        finding(
            unit,
            span.start,
            span.end,
            f"the footnote mark does not follow one of {' '.join(params.after)}. Move it.",
        )
        for unit, span, _ in footnote_marks(ctx)
        if char_before(unit.text, span.start) not in allowed
    )


@rule(
    "core.footnote.format",
    summary="A footnote text starts with a capital letter and ends with a period.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 222",
            "beginnt (...) mit einem Großbuchstaben und wird mit einem Punkt abgeschlossen.",
        )
    ],
)
def footnote_format(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report footnotes that start with a lowercase letter or do not end with a period."""
    for _, _, footnote in footnote_marks(ctx):
        text = masked(footnote)
        start = text.lstrip(_OPENERS)
        # The period can be inside a quotation, so the end check reads the plain text.
        end = footnote.text.rstrip(_CLOSERS)
        if not start:
            continue
        if start[0].isalpha() and start[0].islower() and not is_hidden(start[0]):
            yield finding(
                footnote,
                0,
                1,
                "the footnote starts with a lowercase letter. Start it with a capital letter.",
            )
        if not end.endswith("."):
            yield finding(
                footnote,
                max(len(footnote.text) - 1, 0),
                len(footnote.text),
                "the footnote does not end with a period. Add a period.",
            )


@rule(
    "core.footnote.after-digit",
    summary="A footnote mark does not follow a digit.",
    severity=Severity.WARNING,
    sources=[
        ref(
            HW,
            "S. 148",
            "Vermeiden Sie auch, hochgestellte Fußnotenzeichen direkt hinter Zahlen zu setzen",
        )
    ],
)
def after_digit(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report footnote marks directly after a digit."""
    return (
        finding(
            unit,
            span.start,
            span.end,
            "the footnote mark follows a digit and looks like a power. Move the mark.",
        )
        for unit, span, _ in footnote_marks(ctx)
        if char_before(unit.text, span.start).isdigit()
    )
