"""SAT rules for paragraphs, figure references and abbreviations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from thesis_lint.context import top_heading
from thesis_lint.core.sources import USER, VORLAGE, ref
from thesis_lint.model import Severity
from thesis_lint.packs.sat_meti.support import DECLARATION_TITLE
from thesis_lint.registry import Finding, rule
from thesis_lint.typst.document import UnitKind

if TYPE_CHECKING:
    from collections.abc import Iterator

    from thesis_lint.context import Context
    from thesis_lint.typst.document import Unit

_EXCLUDED = frozenset({DECLARATION_TITLE})


@dataclass(frozen=True, slots=True)
class ParagraphLengthParams:
    """Parameters of `sat.paragraph-length`."""

    max_chars: int = 400


@rule(
    "sat.paragraph-length",
    summary="A paragraph has at most 400 characters.",
    severity=Severity.WARNING,
    sources=[
        ref(
            VORLAGE,
            "Textabsätze",
            "Die Länge eines Absatzes ist auf maximal 400 Zeichen zu beschränken.",
        )
    ],
    params=ParagraphLengthParams(),
)
def paragraph_length(ctx: Context, params: ParagraphLengthParams) -> Iterator[Finding]:
    """Report paragraphs with more characters than the maximum."""
    yield from (
        Finding(
            " ".join(
                (
                    f"the paragraph has {len(unit.text)} characters. Split it into paragraphs of",
                    f"at most {params.max_chars} characters",
                )
            ),
            unit.start_location,
        )
        for unit in ctx.body_units(_EXCLUDED)
        if unit.kind is UnitKind.PARAGRAPH and len(unit.text) > params.max_chars
    )


@dataclass(frozen=True, slots=True)
class FigureRefParams:
    """Parameters of `sat.figure-ref-parens`."""

    label_prefixes: tuple[str, ...] = ("fig:", "tab:")


@rule(
    "sat.figure-ref-parens",
    summary="A reference to a figure or a table is in round brackets, for example (Abbildung 3.1).",
    severity=Severity.WARNING,
    sources=[
        ref(
            VORLAGE,
            "Abbildungen",
            "Hierzu werden im Text runde Klammern verwendet, z.B. (Abbildung 1) oder (Abb. 23).",
        )
    ],
    params=FigureRefParams(),
)
def figure_ref_parens(ctx: Context, params: FigureRefParams) -> Iterator[Finding]:
    """Report figure and table references outside of round brackets."""
    document = ctx.project.document
    labels = {figure.label for figure in document.figures if figure.label is not None}
    for unit in ctx.body_units(_EXCLUDED):
        for reference in unit.references:
            is_figure = reference.key in labels or reference.key.startswith(params.label_prefixes)
            if is_figure and not _in_parens(unit.text, reference.span.start):
                yield Finding(
                    " ".join(
                        (
                            f"the reference @{reference.key} is not in round brackets.",
                            f"Write (@{reference.key})",
                        )
                    ),
                    reference.location,
                )


def _in_parens(text: str, index: int) -> bool:
    before = text[:index]
    return before.count("(") > before.count(")")


@dataclass(frozen=True, slots=True)
class AbbrevStyleParams:
    """Parameters of `sat.abbrev-style`."""

    abbreviations: tuple[str, ...] = ("z.B.", "d.h.", "u.a.", "bzw.", "ggf.", "usw.")


_GAP = r"[\s   ]+"


def _patterns(abbreviation: str) -> list[re.Pattern[str]]:
    """Return the patterns of the wrong forms: with a space, or without the last period."""
    parts = [re.escape(part) for part in abbreviation.split(".") if part]
    spaced = (
        [re.compile(r"(?<![\w.])" + (r"\." + _GAP).join(parts) + r"\.?(?!\w)")]
        if len(parts) > 1
        else []
    )
    missing_period = re.compile(r"(?<![\w.])" + r"\.".join(parts) + r"(?![\w.])")
    return [*spaced, missing_period]


@rule(
    "sat.abbrev-style",
    summary="Common abbreviations have no space inside and end with a period, for example z.B.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Abkürzungen",
            "Die Verwendung von allgemein gebräuchlichen Abkürzungen ist ebenfalls möglich.",
        ),
        ref(
            USER, "Spec", "gebräuchliche Abk. ohne Leerzeichen: z.B., d.h., u.a., bzw., ggf., usw."
        ),
    ],
    params=AbbrevStyleParams(),
)
def abbrev_style(ctx: Context, params: AbbrevStyleParams) -> Iterator[Finding]:
    """Report spaced forms like `z. B.` and forms without the last period like `bzw`."""
    patterns = [
        (abbreviation, pattern)
        for abbreviation in params.abbreviations
        for pattern in _patterns(abbreviation)
    ]
    for unit in _style_units(ctx):
        skipped = [*unit.quotes, *unit.raws, *unit.maths]
        for abbreviation, pattern in patterns:
            for match in pattern.finditer(unit.text):
                if unit.in_span(match.start(), skipped):
                    continue
                yield Finding(
                    f"write {abbreviation!r} instead of {re.sub(_GAP, ' ', match.group(0))!r}",
                    unit.location(match.start(), match.end()),
                )


def _style_units(ctx: Context) -> Iterator[Unit]:
    if ctx.project.abstract is not None:
        yield ctx.project.abstract
    yield from (
        unit
        for unit in ctx.project.document.units
        if unit.kind is not UnitKind.CONTENT
        and (unit.heading is None or top_heading(unit.heading).text not in _EXCLUDED)
    )
