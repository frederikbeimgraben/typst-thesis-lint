"""Rules for plagiarism: text from the source PDFs without quotation marks."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import TYPE_CHECKING

import pypdf

from thesis_lint.core.citation import EXCLUDED_TITLES
from thesis_lint.core.sources import LANGE, VL02, ref
from thesis_lint.model import Needs, Severity
from thesis_lint.registry import Finding, rule
from thesis_lint.typst.document import UnitKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from thesis_lint.context import Context
    from thesis_lint.typst.document import Unit

_HYPHEN_BREAK = re.compile(r"(\w)[-\u00ad]\s*\n\s*(\w)")
_WORD = re.compile(r"[^\W_]+")
_NOT_ALNUM = re.compile(r"[\W_]+")


@dataclass(frozen=True, slots=True)
class NgramParams:
    """Parameters of `core.plagiarism.ngram`.

    The rule joins `n` words of the text without spaces and searches the result in
    the sources, which are also joined without spaces. So it does not depend on the
    space glyphs of a PDF. `min_chars` is the shortest joined string that counts.
    """

    n: int = 6
    min_chars: int = 25


@dataclass(frozen=True, slots=True)
class Word:
    """A normalized word of a unit with its character range."""

    text: str
    start: int
    end: int


def compact(text: str) -> str:
    """Return the text in lower case with letters and digits only, without spaces.

    NFKC turns ligatures into letters, for example U+FB01 into "fi". A word that a
    line break hyphenates is joined first.
    """
    joined = _HYPHEN_BREAK.sub(r"\1\2", unicodedata.normalize("NFKC", text).replace("\u00ad", ""))
    return _NOT_ALNUM.sub("", joined).lower()


def source_texts(directory: Path) -> dict[str, str]:
    """Return the compact text of each `<bibkey>.pdf` file, keyed by the bib key."""
    return {path.stem: _cached_compact(path) for path in sorted(directory.glob("*.pdf"))}


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "thesis-lint" / "sources"


def _cached_compact(path: Path) -> str:
    """Return the compact text of a PDF. Cache it by the hash of the file content."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    cache = _cache_dir() / f"{digest}.txt"
    try:
        return cache.read_text(encoding="utf-8")
    except OSError:
        pass
    text = compact(_pdf_text(path))
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    except OSError:
        pass
    return text


def _pdf_text(path: Path) -> str:
    """Return the text of a PDF. Use pdftotext if it is on PATH, else pypdf."""
    pdftotext = shutil.which("pdftotext")
    if pdftotext is not None:
        result = subprocess.run(  # noqa: S603 - fixed executable, no shell
            [pdftotext, "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.decode("utf-8", errors="replace")
    reader = pypdf.PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def unquoted_segments(unit: Unit) -> Iterator[list[Word]]:
    """Yield the runs of words between quotations. A run does not cross a quotation."""
    text = unit.text.replace("\u00ad", " ")
    matches = list(_WORD.finditer(text))
    keyed = groupby(matches, key=lambda m: _segment_id(unit, m.start()))
    return (
        [Word(compact(m.group(0)), m.start(), m.end()) for m in group]
        for segment, group in keyed
        if segment >= 0
    )


def _segment_id(unit: Unit, index: int) -> int:
    """Return -1 for a quoted character, else the number of quotations before it."""
    if unit.is_quoted(index):
        return -1
    return sum(span.end <= index for span in unit.quotes)


def matched_runs(
    words: list[Word], sources: dict[str, str], params: NgramParams
) -> Iterator[tuple[int, int, str]]:
    """Yield `(first word, last word, key)` for each run of overlapping matched windows."""
    n = params.n

    def source_of(i: int) -> str | None:
        window = "".join(word.text for word in words[i : i + n])
        if len(window) < params.min_chars:
            return None
        return next((key for key, text in sources.items() if window in text), None)

    hits = [(i, key) for i in range(len(words) - n + 1) if (key := source_of(i)) is not None]
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
    sources=[ref(LANGE, "S. 114"), ref(VL02, "Folien 12, 112, 124")],
    params=NgramParams(),
    needs=Needs.SOURCES_DIR,
)
def ngram(ctx: Context, params: NgramParams) -> Iterator[Finding]:
    """Report runs of words that also occur in a source PDF and are not quoted."""
    directory = ctx.root / ctx.config.paths.sources_dir
    if not directory.is_dir():
        return
    sources = source_texts(directory)
    if not sources:
        return
    for unit in _prose_units(ctx):
        for segment in unquoted_segments(unit):
            for first, last, key in matched_runs(segment, sources, params):
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
