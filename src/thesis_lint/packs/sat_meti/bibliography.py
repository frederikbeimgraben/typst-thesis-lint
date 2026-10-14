"""SAT rules for the bibliography."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from thesis_lint.core.sources import SAT, VL02, VORLAGE, ref
from thesis_lint.model import Location, Severity
from thesis_lint.packs.sat_meti.support import listed_keys, main_location
from thesis_lint.registry import Finding, rule

if TYPE_CHECKING:
    from collections.abc import Iterator

    from thesis_lint.bib import BibEntry
    from thesis_lint.context import Context


@dataclass(frozen=True, slots=True)
class BibCountParams:
    """Parameters of `sat.bib-count`."""

    min_entries: int = 8
    min_original: int = 5
    original_types: tuple[str, ...] = (
        "article",
        "inproceedings",
        "book",
        "incollection",
        "inbook",
        "phdthesis",
    )
    thesis_types: tuple[str, ...] = ("thesis",)
    doctoral_values: tuple[str, ...] = ("phd", "phdthesis", "dissertation")


@rule(
    "sat.bib-count",
    summary="The bibliography has at least 8 entries. At least 5 of them are original works.",
    severity=Severity.ERROR,
    sources=[
        ref(
            SAT,
            "S. 10",
            "mindestens 8 Quellen hiervon mindestens 5 Quellen in Form von Originalarbeiten",
        ),
        ref(
            VL02,
            "Folie 33",
            "Nach erfolgreichem Durchlauf des reviews ... → zitierfähig!",
        ),
        ref(
            VL02,
            "Folie 135",
            "Vollständige Bibliographische Daten bzw. ISBN oder DOI müssen vorhanden sein",
        ),
    ],
    params=BibCountParams(),
)
def bib_count(ctx: Context, params: BibCountParams) -> Iterator[Finding]:
    """Count the entries that the bibliography prints: the cited ones, or all with `full: true`."""
    entries = ctx.project.bibliography.entries
    keys = listed_keys(ctx)
    original = sum(_is_original(entries[key], params) for key in keys)
    location = _bibliography_location(ctx)
    if len(keys) < params.min_entries:
        yield Finding(
            f"the bibliography has {len(keys)} entries. Cite at least {params.min_entries} sources",
            location,
        )
    if original < params.min_original:
        kinds = ", ".join(params.original_types + params.thesis_types)
        yield Finding(
            " ".join(
                (
                    f"the bibliography has {original} original works. Cite at least",
                    f"{params.min_original} sources of the types {kinds}. Only a PhD thesis counts",
                )
            ),
            location,
        )


def _is_original(entry: BibEntry, params: BibCountParams) -> bool:
    if entry.type in params.original_types:
        return True
    if entry.type not in params.thesis_types:
        return False
    kind = (entry.get("type") or "").lower()
    return kind in {value.lower() for value in params.doctoral_values}


def _bibliography_location(ctx: Context) -> Location:
    calls = ctx.project.bibliography_calls
    if calls:
        return calls[0].source.node_location(calls[0].node)
    bib = ctx.config.paths.bib
    return Location(ctx.root / bib[0]) if bib else main_location(ctx)


@dataclass(frozen=True, slots=True)
class CitationStyleParams:
    """Parameters of `sat.citation-style`."""

    csl_file: str = "apa-6th-edition.csl"


@rule(
    "sat.citation-style",
    summary="The bibliography uses the APA 6th edition CSL file.",
    severity=Severity.ERROR,
    sources=[
        ref(
            VORLAGE,
            "Zitate",
            "Hinweise auf die verwendete Literatur im Stil APA 6th",
        ),
        ref(
            VL02,
            "Folie 141",
            "Wichtig: Vorgaben müssen exakt eingehalten werden!",
        ),
        ref(
            VL02,
            "Folie 150",
            "Erstellt mittels Citavi Ver. 5.6.0.2, im Stil APA 6th ed.",
        ),
    ],
    params=CitationStyleParams(),
)
def citation_style(ctx: Context, params: CitationStyleParams) -> Iterator[Finding]:
    """Check the `style` argument of every `bibliography` call."""
    calls = ctx.project.bibliography_calls
    if not calls:
        yield Finding(
            " ".join(
                (
                    "the document has no bibliography.",
                    f'Add #bibliography("main.bib", style: "{params.csl_file}")',
                    "in the chapter Literaturverzeichnis",
                )
            ),
            main_location(ctx),
        )
        return
    yield from (
        Finding(
            f"the bibliography style is {call.style!r}. Use style: {params.csl_file!r}",
            call.source.node_location(call.node),
        )
        for call in calls
        if call.style is None or call.style.replace("\\", "/").rsplit("/", 1)[-1] != params.csl_file
    )
