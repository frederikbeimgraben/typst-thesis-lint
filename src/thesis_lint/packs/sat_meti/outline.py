"""SAT rules for the outline, the lists and the declaration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from thesis_lint.core.sources import SAT, VL02, VORLAGE, ref
from thesis_lint.model import Needs, Severity
from thesis_lint.packs.sat_meti import pdflines
from thesis_lint.packs.sat_meti.support import (
    DECLARATION_TITLE,
    main_location,
    section_nodes,
    setting_location,
)
from thesis_lint.registry import Finding, rule
from thesis_lint.typst.document import UnitKind
from thesis_lint.typst.parse import call_name

if TYPE_CHECKING:
    from collections.abc import Iterator

    from thesis_lint.context import Context
    from thesis_lint.typst.document import Heading


@dataclass(frozen=True, slots=True)
class OutlineParams:
    """Parameters of `sat.outline`."""

    chapters: tuple[str, ...] = (
        "Einleitung",
        "Methoden",
        "Ergebnisse",
        "Diskussion",
        "Zusammenfassung",
        "Literaturverzeichnis",
        "Danksagungen",
        "Eidesstattliche Erklärung",
        "Anhang",
    )


@rule(
    "sat.outline",
    summary="The level-1 headings are exactly the chapters of the SAT template, in this order.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Gliederung des Textes",
            "muss die nachfolgend gegebene Gliederung aufweisen (Hauptüberschriften)",
        ),
        ref(SAT, "S. 10", "Die Hauptgliederung ist in SAT fix vorgegeben und einzuhalten."),
        ref(
            VL02,
            "Folie 56",
            "Einleitung /Hintergrund/ Stand der Forschung, Ziele, Angewandte Methoden, Ergebnisse",
        ),
        ref(
            VL02,
            "Folie 57",
            "IMRaD structure: Introduction, Methods, Results and Discussion",
        ),
    ],
    params=OutlineParams(),
)
def outline(ctx: Context, params: OutlineParams) -> Iterator[Finding]:
    """Report missing, extra and misplaced level-1 headings."""
    expected = params.chapters
    chapters = [h for h in ctx.project.document.headings if h.level == 1]
    order = ", ".join(expected)
    yield from (
        Finding(
            f"level-1 heading {heading.text!r} is not a SAT chapter. Use only: {order}",
            heading.location,
        )
        for heading in chapters
        if heading.text not in expected
    )
    titles = [h.text for h in chapters]
    yield from (
        Finding(f"the chapter {title!r} is missing. Add `= {title}`", main_location(ctx))
        for title in expected
        if title not in titles
    )
    known = [h for h in chapters if h.text in expected]
    wanted = [title for title in expected if title in titles]
    misplaced = next(
        (h for h, title in zip(known, wanted, strict=False) if h.text != title),
        None,
    )
    if misplaced is None and len(known) > len(wanted):
        misplaced = known[len(wanted)]
    if misplaced is not None:
        yield Finding(
            f"level-1 heading {misplaced.text!r} is at the wrong position. Use this order: {order}",
            misplaced.location,
        )


@dataclass(frozen=True, slots=True)
class MaxDepthParams:
    """Parameters of `sat.max-depth`."""

    max_level: int = 2
    appendix_title: str = "Anhang"
    appendix_level: int = 4
    appendix_pattern: str = r"^VS\d{3}"


@rule(
    "sat.max-depth",
    summary="The text uses heading levels 1 and 2 only. The appendix can have level-4 VS headings.",
    severity=Severity.ERROR,
    sources=[
        ref(
            SAT,
            "S. 10",
            "die jedoch alle auf nur einer Unterebene liegen sollen",
        ),
        ref(
            VORLAGE,
            "Titel und Überschriften",
            "Die Gliederung des Textes sollte maximal über 2 Ebenen erfolgen.",
        ),
        ref(
            VORLAGE,
            "Anhang",
            "Format Überschrift 4 – diese darf im Inhaltsverzeichnis nicht erscheinen",
        ),
    ],
    params=MaxDepthParams(),
)
def max_depth(ctx: Context, params: MaxDepthParams) -> Iterator[Finding]:
    """Report headings that are deeper than the maximum level."""
    pattern = re.compile(params.appendix_pattern)
    yield from (
        Finding(
            " ".join(
                (
                    f"heading {heading.text!r} has level {heading.level}. The SAT allows only",
                    f"{params.max_level} levels. Use a level-{params.max_level} section",
                )
            ),
            heading.location,
        )
        for heading in ctx.project.document.headings
        if heading.level > params.max_level and not _appendix_exception(heading, params, pattern)
    )


def _appendix_exception(heading: Heading, params: MaxDepthParams, pattern: re.Pattern[str]) -> bool:
    top = next((h for h in heading.ancestors() if h.parent is None), heading)
    return (
        top.text == params.appendix_title
        and heading.level == params.appendix_level
        and pattern.search(heading.text) is not None
    )


@dataclass(frozen=True, slots=True)
class DirectoriesParams:
    """Parameters of `sat.directories`."""

    layout: str = "sat-meti"
    titles: tuple[str, ...] = pdflines.LIST_TITLES
    h1_pt: float = pdflines.H1_PT
    tolerance_pt: float = pdflines.SIZE_TOLERANCE_PT


@rule(
    "sat.directories",
    summary="The PDF has all six lists: contents, figures, tables, equations, acronyms, glossary.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Gliederung des Textes",
            "mit Ausnahme des Abschnitts „Verzeichnisse“",
        ),
        ref(
            VL02,
            "Folie 56",
            "Inhaltsverzeichnis",
        ),
        ref(
            VL02,
            "Folie 97",
            "Erklären Sie die Bedeutung von Abkürzungen, bevor diese fortgesetzt verwendet werden",
        ),
        ref(
            VL02,
            "Folie 100",
            "zusätzlich soll ein Abkürzungsverzeichnis verwendet werden",
        ),
    ],
    params=DirectoriesParams(),
    needs=Needs.PDF,
)
def directories(ctx: Context, params: DirectoriesParams) -> Iterator[Finding]:
    """Check the layout setting and find the list headings in the PDF."""
    layout = ctx.project.setting_str("layout")
    if layout != params.layout:
        yield Finding(
            " ".join(
                (
                    f'the setting layout is {layout!r}. Set layout: "{params.layout}".',
                    "This layout prints all lists",
                )
            ),
            setting_location(ctx, "layout"),
        )
    found = {
        pdflines.normalize(line.title)
        for line in pdflines.chapter_headings(ctx.pdf, params.h1_pt, params.tolerance_pt)
    }
    yield from (
        Finding(
            " ".join(
                (
                    f"the PDF has no list with the heading {title!r}.",
                    f'Use layout: "{params.layout}" to print all lists',
                )
            ),
            main_location(ctx),
        )
        for title in params.titles
        if pdflines.normalize(title) not in found
    )


@dataclass(frozen=True, slots=True)
class DeclarationParams:
    """Parameters of `sat.declaration`."""

    title: str = DECLARATION_TITLE
    function: str = "declaration"
    # The parts of the text. The rule joins them with one space.
    text: tuple[str, ...] = (
        "Hiermit erkläre ich an Eides statt, dass ich die vorliegende Arbeit selbstständig",
        "erstellt, keine nicht genannte fremde Hilfe in Anspruch genommen und alle von mir",
        "verwendeten Hilfsmittel und Quellen in der Arbeit benannt und kenntlich gemacht habe.",
        "Die Arbeit oder Teile davon wurden in keinem Prüfungsmodul zur Prüfung vorgelegt und",
        "verletzt in keiner Weise Rechte Dritter.",
        "Mir ist bekannt, dass eine unwahre Erklärung als Täuschung gewertet wird.",
    )


@rule(
    "sat.declaration",
    summary="The declaration has the exact text of the template.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Gliederung des Textes",
            "Eidesstattliche Erklärung: Der hier im Dokument gegebene Text muss übernommen werden.",
        ),
        ref(
            VL02,
            "Folie 146",
            "Am Ende der schriftlichen Ausarbeitung steht zumeist eine eidesstattliche Erklärung",
        ),
        ref(
            VL02,
            "Folie 147",
            "Einhaltung der formellen Vorgaben",
        ),
    ],
    params=DeclarationParams(),
)
def declaration(ctx: Context, params: DeclarationParams) -> Iterator[Finding]:
    """Accept the template function or the exact text. White space does not matter."""
    heading = ctx.heading_by_title(params.title)
    if heading is None:
        return
    if any(
        node.type == "call" and call_name(node, heading.source) == params.function
        for node in section_nodes(ctx, heading)
    ):
        return
    units = [u for u in heading.all_units() if u.kind is not UnitKind.HEADING]
    actual = pdflines.normalize(" ".join(unit.text for unit in units))
    expected = pdflines.normalize(" ".join(params.text))
    if actual == expected:
        return
    index = next(
        (i for i, (a, b) in enumerate(zip(actual, expected, strict=False)) if a != b),
        min(len(actual), len(expected)),
    )
    shown = pdflines.excerpt(actual[index:]) or "(end of text)"
    yield Finding(
        " ".join(
            (
                "the declaration text is not the template text. The first difference is at",
                f"{shown!r}. Use #{params.function}() or copy the exact text",
            )
        ),
        units[0].start_location if units else heading.location,
    )
