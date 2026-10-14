"""SAT rules for the appendix: hypothesis, project plan and improvements."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from thesis_lint.context import Milestone, top_heading
from thesis_lint.core.sources import SAT, VL02, VORLAGE, ref
from thesis_lint.model import Severity
from thesis_lint.packs.sat_meti.support import (
    child_heading,
    descendants,
    main_location,
    section_nodes,
)
from thesis_lint.registry import Finding, rule
from thesis_lint.typst.document import UnitKind
from thesis_lint.typst.parse import call_name, positional_args

if TYPE_CHECKING:
    from collections.abc import Iterator

    from thesis_lint.context import Context
    from thesis_lint.typst.document import Heading


def _section(
    ctx: Context, appendix_title: str, title: str
) -> tuple[Heading | None, Heading | None]:
    appendix = ctx.heading_by_title(appendix_title)
    return appendix, None if appendix is None else child_heading(appendix, title)


def _missing(ctx: Context, appendix: Heading | None, appendix_title: str, title: str) -> Finding:
    location = appendix.location if appendix is not None else main_location(ctx)
    return Finding(
        f"the appendix has no section {title!r}. Add `== {title}` under `= {appendix_title}`",
        location,
    )


@dataclass(frozen=True, slots=True)
class HypothesisParams:
    """Parameters of `sat.appendix-hypothesis`."""

    appendix_title: str = "Anhang"
    title: str = "Arbeitshypothese"
    placeholder_pattern: str = r"^\[.*\]$"


@rule(
    "sat.appendix-hypothesis",
    summary="The appendix has a section with the working hypothesis, and the section has text.",
    severity=Severity.ERROR,
    sources=[
        ref(VORLAGE, "Anhang", "Arbeitshypothese: [Hier die Arbeitshypothese eintragen]"),
        ref(
            SAT,
            "S. 10",
            "Die Arbeitshypothese ist die zentrale Aussage",
        ),
        ref(
            VL02,
            "Folie 26",
            "Eine Hypothese ist eine überprüfbare Aussage",
        ),
        ref(
            VL02,
            "Folie 28",
            "Die wissenschaftliche Fragestellung wird als Arbeitshypothese formuliert",
        ),
        ref(
            VL02,
            "Folie 30",
            "Arbeitshypothese: C ist schneller als Java",
        ),
        ref(
            VL02,
            "Folie 78",
            "Folgendes muss festgelegt sein: ... Hypothese und Leitfragen",
        ),
    ],
    params=HypothesisParams(),
)
def appendix_hypothesis(ctx: Context, params: HypothesisParams) -> Iterator[Finding]:
    """Report a missing or empty hypothesis section. A bracket placeholder is empty."""
    appendix, section = _section(ctx, params.appendix_title, params.title)
    if section is None:
        yield _missing(ctx, appendix, params.appendix_title, params.title)
        return
    placeholder = re.compile(params.placeholder_pattern)
    texts = [
        unit.text
        for unit in section.all_units()
        if unit.kind is not UnitKind.HEADING
        and any(char.isalnum() for char in unit.text)
        and placeholder.search(unit.text.strip()) is None
    ]
    if not texts:
        yield Finding(
            f"the section {params.title!r} is empty. Write the working hypothesis",
            section.location,
        )


@dataclass(frozen=True, slots=True)
class ProjectPlanParams:
    """Parameters of `sat.appendix-projectplan`."""

    appendix_title: str = "Anhang"
    title: str = "Projektplan"
    figure_kind: str = "image"


@rule(
    "sat.appendix-projectplan",
    summary="The appendix has a section with the project plan as a figure with an image.",
    severity=Severity.ERROR,
    sources=[
        ref(VORLAGE, "Anhang", "Projektplan: [Hier das Gantt-Diagramm einfügen"),
        ref(
            SAT, "S. 11", "Im Anhang des Entwurfsdokumentes muss ein Gantt-Diagramm enthalten sein"
        ),
        ref(
            VL02,
            "Folie 20",
            "Planung der Umsetzung (Arbeitspakete, Termine)",
        ),
        ref(
            VL02,
            "Folie 79",
            "Damit inhaltliche und zeitliche Ziele erreicht werden, ist Planung des Prozesses",
        ),
    ],
    params=ProjectPlanParams(),
)
def appendix_projectplan(ctx: Context, params: ProjectPlanParams) -> Iterator[Finding]:
    """Report a missing project plan section or a section without an image figure."""
    appendix, section = _section(ctx, params.appendix_title, params.title)
    if section is None:
        yield _missing(ctx, appendix, params.appendix_title, params.title)
        return
    inside = {id(section), *(id(h) for h in descendants(section))}
    figures = [
        figure
        for figure in ctx.project.document.figures
        if figure.heading is not None
        and id(figure.heading) in inside
        and figure.kind == params.figure_kind
    ]
    if not figures:
        yield Finding(
            " ".join(
                (
                    f"the section {params.title!r} has no figure with an image.",
                    'Add the Gantt chart as #figure(image("..."), caption: [...])',
                )
            ),
            section.location,
        )


@dataclass(frozen=True, slots=True)
class ImprovementsParams:
    """Parameters of `sat.improvements`."""

    appendix_title: str = "Anhang"
    title: str = "Verbesserungsvorschläge"
    level: int = 4
    id_pattern: str = r"^VS\d{3}"


@rule(
    "sat.improvements",
    summary="Milestone sa32: each VS heading in the appendix has level 4 and a link to the text.",
    severity=Severity.ERROR,
    sources=[
        ref(
            SAT,
            "S. 12",
            "sind alle Verbesserungsvorschläge in den Anhang der Ausarbeitung zu übernehmen",
        ),
        ref(
            SAT,
            "S. 13",
            "Erstellen Sie zu jedem Verbesserungsvorschlag einen Link zu dem Absatz des Textes",
        ),
        ref(
            SAT,
            "S. 13",
            "keine Verbesserungsvorschläge vorgegeben bekommen, so entfällt dieser Arbeitsschritt",
        ),
        ref(
            VORLAGE,
            "Anhang",
            "Format Überschrift 4 – diese darf im Inhaltsverzeichnis nicht erscheinen",
        ),
    ],
    params=ImprovementsParams(),
    submission=True,
)
def improvements(ctx: Context, params: ImprovementsParams) -> Iterator[Finding]:
    """Check the VS headings and their links. The rule runs only for the milestone sa32.

    A missing or empty section is correct: without feedback, the step is not necessary.
    """
    if ctx.milestone is not Milestone.SA32:
        return
    _, section = _section(ctx, params.appendix_title, params.title)
    if section is None:
        return
    pattern = re.compile(params.id_pattern)
    for heading in descendants(section):
        yield from _check_improvement(ctx, heading, params, pattern)


def _check_improvement(
    ctx: Context, heading: Heading, params: ImprovementsParams, pattern: re.Pattern[str]
) -> Iterator[Finding]:
    if heading.level != params.level:
        yield Finding(
            " ".join(
                (
                    f"the improvement {heading.text!r} has level {heading.level}.",
                    f"Use level {params.level} (`{'=' * params.level}`)",
                )
            ),
            heading.location,
        )
    if pattern.search(heading.text) is None:
        yield Finding(
            " ".join(
                (
                    f"the improvement {heading.text!r} has no number. Start the title with VS001,",
                    "VS002 and so on",
                )
            ),
            heading.location,
        )
    if not _links_to_text(ctx, heading, params.appendix_title):
        yield Finding(
            " ".join(
                (
                    f"the improvement {heading.text!r} has no link to a heading in the text.",
                    "Add a link, for example #link(<sec:x>)[...] or @sec:x",
                )
            ),
            heading.location,
        )


def _links_to_text(ctx: Context, heading: Heading, appendix_title: str) -> bool:
    targets = {
        h.label: h
        for h in ctx.project.document.headings
        if h.label is not None and top_heading(h).text != appendix_title
    }
    return any(label in targets for label in _link_labels(ctx, heading))


def _link_labels(ctx: Context, heading: Heading) -> Iterator[str]:
    source = heading.source
    for node in section_nodes(ctx, heading):
        if node.type == "ref":
            match = re.match(r"@([^\[\s]+)", source.node_text(node))
            if match is not None:
                yield match.group(1).rstrip(".:,;")
        elif node.type == "call" and call_name(node, source) == "link":
            yield from (
                source.node_text(arg).strip("<>")
                for arg in positional_args(node)
                if arg.type == "label"
            )
