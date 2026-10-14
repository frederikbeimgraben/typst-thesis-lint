"""Rules for plagiarism: text from the source PDFs without quotation marks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import groupby
from typing import TYPE_CHECKING

from thesis_lint.core.citation import EXCLUDED_TITLES
from thesis_lint.core.sources import LANGE, ref
from thesis_lint.model import Needs, Severity
from thesis_lint.pdf import read_pdf
from thesis_lint.registry import Finding, rule
from thesis_lint.typst.document import UnitKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from thesis_lint.context import Context
    from thesis_lint.typst.document import Unit

_HYPHEN_BREAK = re.compile(r"(\w)[-­]\s*\n\s*(\w)")
_LETTERS = re.compile(r"[^\W\d_]+")

type NGram = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NgramParams:
    """Parameters of `core.plagiarism.ngram`."""

    n: int = 6


@dataclass(frozen=True, slots=True)
class Word:
    """A normalized word of a unit with its character range."""

    text: str
    start: int
    end: int


def normalize(text: str) -> list[str]:
    """Return the lower-case words of a text. Join words that a line break hyphenates."""
    joined = _HYPHEN_BREAK.sub(r"\1\2", text.replace("­", ""))
    return [match.group(0).lower() for match in _LETTERS.finditer(joined)]


def ngrams(tokens: list[str], n: int) -> Iterator[NGram]:
    """Yield the n-grams of a token list."""
    return (tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1))


def source_ngrams(directory: Path, n: int) -> dict[NGram, str]:
    """Return the n-grams of all `<bibkey>.pdf` files. Map each n-gram to its first key."""
    index: dict[NGram, str] = {}
    for path in sorted(directory.glob("*.pdf")):
        text = "\n".join(page.text for page in read_pdf(path).pages)
        for gram in ngrams(normalize(text), n):
            index.setdefault(gram, path.stem)
    return index


def unquoted_segments(unit: Unit) -> Iterator[list[Word]]:
    """Yield the runs of words between quotations. A run does not cross a quotation."""
    text = unit.text.replace("­", " ")
    matches = list(_LETTERS.finditer(text))
    keyed = groupby(matches, key=lambda m: _segment_id(unit, m.start()))
    return (
        [Word(m.group(0).lower(), m.start(), m.end()) for m in group]
        for segment, group in keyed
        if segment >= 0
    )


def _segment_id(unit: Unit, index: int) -> int:
    """Return -1 for a quoted character, else the number of quotations before it."""
    if unit.is_quoted(index):
        return -1
    return sum(span.end <= index for span in unit.quotes)


def matched_runs(
    words: list[Word], index: dict[NGram, str], n: int
) -> Iterator[tuple[int, int, str]]:
    """Yield `(first word, last word, key)` for each run of overlapping matched n-grams."""
    hits = [
        (i, key)
        for i, gram in enumerate(ngrams([w.text for w in words], n))
        if (key := index.get(gram)) is not None
    ]
    runs: list[tuple[int, int, str]] = []
    for i, key in hits:
        if runs and i <= runs[-1][1] + 1:
            first, _, run_key = runs[-1]
            runs[-1] = (first, i + n - 1, run_key)
        else:
            runs.append((i, i + n - 1, key))
    return iter(runs)


def _prose_units(ctx: Context) -> Iterable[Unit]:
    return (
        unit for unit in ctx.body_units(EXCLUDED_TITLES) if unit.kind is not UnitKind.QUOTE_BLOCK
    )


@rule(
    "core.plagiarism.ngram",
    summary="The text has no unmarked word sequences from the source PDFs.",
    severity=Severity.ERROR,
    sources=[ref(LANGE, "S. 114")],
    params=NgramParams(),
    needs=Needs.SOURCES_DIR,
)
def ngram(ctx: Context, params: NgramParams) -> Iterator[Finding]:
    """Report runs of words that also occur in a source PDF and are not quoted."""
    directory = ctx.root / ctx.config.paths.sources_dir
    if not directory.is_dir():
        return
    index = source_ngrams(directory, params.n)
    if not index:
        return
    for unit in _prose_units(ctx):
        for segment in unquoted_segments(unit):
            for first, last, key in matched_runs(segment, index, params.n):
                count = last - first + 1
                yield Finding(
                    " ".join(
                        (
                            f"{count} words match the source {key!r} literally.",
                            "Mark them as a quotation or paraphrase them.",
                        )
                    ),
                    unit.location(segment[first].start, segment[last].end),
                )
