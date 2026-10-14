"""Rules for headings and the outline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from thesis_lint.core.sources import BRINK, HW, ref
from thesis_lint.model import Severity
from thesis_lint.registry import Finding, NoParams, rule

if TYPE_CHECKING:
    from collections.abc import Iterator

    from thesis_lint.context import Context


@rule(
    "core.heading.min-children",
    summary="A heading with subsections has at least two subsections.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 146 f.",
            "Keinesfalls darf zu einem Oberpunkt nur ein einziger Unterpunkt eingerichtet werden.",
        ),
        ref(
            HW, "S. 67", "Eine Gliederungsebene darf nicht nur ein einziges Unterkapitel beinhalten"
        ),
    ],
)
def min_children(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report headings with exactly one child heading."""
    for heading in ctx.project.document.headings:
        outlined = [child for child in heading.children if child.outlined]
        if len(outlined) == 1:
            yield Finding(
                f"heading {heading.text!r} has only one subsection. Add a second one or remove it.",
                heading.location,
            )
