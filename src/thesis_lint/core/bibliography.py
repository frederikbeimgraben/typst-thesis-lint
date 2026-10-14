"""Rules for the bibliography file."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from thesis_lint.core.sources import BRINK, HW, VORLAGE, ref
from thesis_lint.model import Severity
from thesis_lint.registry import Finding, NoParams, rule

if TYPE_CHECKING:
    from collections.abc import Iterator

    from thesis_lint.context import Context

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@rule(
    "core.bib.urldate",
    summary="An entry with a URL has an access date in the format YYYY-MM-DD.",
    severity=Severity.ERROR,
    sources=[
        ref(VORLAGE, "Literaturverzeichnis", "neben der Angabe der URL und des Zugriffsdatums"),
        ref(BRINK, "S. 233", "stets das Datum des letzten Aufrufs"),
        ref(HW, "S. 181", "Onlinequellen bei der Zitation unbedingt mit dem Datum versehen"),
    ],
)
def urldate(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report entries with `url` but without a valid `urldate`."""
    for entry in ctx.project.bibliography.entries.values():
        if not entry.has("url"):
            continue
        value = entry.get("urldate")
        if not value:
            yield Finding(f"entry {entry.key!r} has a url but no urldate", entry.location("url"))
        elif not _ISO_DATE.fullmatch(value):
            yield Finding(
                f"entry {entry.key!r}: urldate {value!r} is not in the format YYYY-MM-DD",
                entry.location("urldate"),
            )
