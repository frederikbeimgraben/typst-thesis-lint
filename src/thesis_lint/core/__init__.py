"""General rules. Each module registers its rules on import."""

from thesis_lint.core import (
    abbreviations,
    bibliography,
    citation,
    content,
    figures,
    footnotes,
    numbers,
    plagiarism,
    structure,
    style,
)

__all__ = [
    "abbreviations",
    "bibliography",
    "citation",
    "content",
    "figures",
    "footnotes",
    "numbers",
    "plagiarism",
    "structure",
    "style",
]
