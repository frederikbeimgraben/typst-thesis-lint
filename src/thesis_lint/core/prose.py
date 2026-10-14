"""Shared helpers for rules that read running text.

Style, number and abbreviation rules look only at prose that the author wrote
in their own words. This module selects that prose and hides the parts that
the rules must not check:

- `prose_units` yields the units of the selected kinds. It skips the units under
  a level-1 heading in `EXCLUDED_TITLES`: the declaration of authorship has
  fixed wording, and the acknowledgements are personal text. It skips
  headings, because the heading rules check them.
- `masked` returns the text of a unit with the same length. It replaces quoted
  text and glossary uses with `MASK`. Math, raw text, references and other
  inline objects are already single placeholder characters in the unit text.
- `word_regex` compiles a word list into one pattern that matches whole words.
  A space in an entry matches any white space. An entry that ends with `*`
  also matches longer words with the same start. A period in an entry can
  have one space after it, so that `i.d.R.` also matches `i. d. R.`.
- `hits` and `finding` connect a pattern to the units and to locations.

Other rule modules can use these helpers. Keep the functions pure.
"""

from __future__ import annotations

import re
from functools import cache
from typing import TYPE_CHECKING

from thesis_lint.context import top_heading
from thesis_lint.registry import Finding
from thesis_lint.text import Sentence, sentences
from thesis_lint.typst.document import OBJECT_MARK, PLACEHOLDERS, UnitKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from thesis_lint.context import Context
    from thesis_lint.typst.document import Span, Unit

# Level-1 titles of chapters that the prose rules do not check. The
# declaration of authorship has fixed wording. The acknowledgements are
# personal text, so the first person is correct there.
EXCLUDED_TITLES: tuple[str, ...] = (
    "Eidesstattliche Erklärung",
    "Ehrenwörtliche Erklärung",
    "Selbstständigkeitserklärung",
    "Selbständigkeitserklärung",
    "Danksagungen",
    "Danksagung",
)

# Unit kinds that hold running text.
STYLE_KINDS = frozenset(
    {UnitKind.PARAGRAPH, UnitKind.ITEM, UnitKind.ENUM_ITEM, UnitKind.TERM, UnitKind.FOOTNOTE}
)
# Running text together with captions and table cells.
TEXT_KINDS = STYLE_KINDS | {UnitKind.CAPTION, UnitKind.CELL}

# The character that replaces hidden text. It is not a word character.
MASK = OBJECT_MARK

_GLOB = "*"


def prose_units(
    ctx: Context,
    kinds: frozenset[UnitKind] = STYLE_KINDS,
    excluded_titles: tuple[str, ...] = EXCLUDED_TITLES,
) -> Iterator[Unit]:
    """Yield the units of `kinds` in document order. Skip the chapters in `excluded_titles`."""
    return (
        unit
        for unit in ctx.project.document.units
        if unit.kind in kinds
        and (unit.heading is None or top_heading(unit.heading).text not in excluded_titles)
    )


def masked(unit: Unit, *, glossary: bool = True) -> str:
    """Return the unit text. Replace quotations and (if `glossary`) glossary uses with MASK."""
    spans: list[Span] = list(unit.quotes)
    if glossary:
        spans.extend(use.span for use in unit.glossary)
    if not spans:
        return unit.text
    hidden = frozenset(index for span in spans for index in range(span.start, span.end))
    return "".join(MASK if index in hidden else char for index, char in enumerate(unit.text))


def is_hidden(char: str) -> bool:
    """Return True if `char` is a placeholder or the mask character."""
    return char in PLACEHOLDERS or char == MASK


def entry_regex(entry: str) -> str:
    """Return the regex source for one word-list entry. See the module docstring."""
    glob = entry.endswith(_GLOB)
    words = entry.removesuffix(_GLOB).split()
    # After a period, the space to the next word is optional: "m. E." and "m.E.".
    body = "".join(
        (r"\s*" if words[index - 1].endswith(".") else r"\s+") * (index > 0) + _word_regex(word)
        for index, word in enumerate(words)
    )
    return body + (r"\w*" if glob else "")


def _word_regex(word: str) -> str:
    escaped = [re.escape(part) for part in word.split(".")]
    if word.endswith("."):
        return r"\.\s?".join(escaped[:-1]) + r"\."
    return r"\.\s?".join(escaped)


@cache
def word_regex(entries: tuple[str, ...], *, ignore_case: bool = True) -> re.Pattern[str]:
    """Return a pattern that matches each entry as a whole word. Longer entries win."""
    alternatives = sorted((entry_regex(entry) for entry in entries if entry.strip()), key=len)
    if not alternatives:
        return re.compile(r"(?!)")
    body = "|".join(reversed(alternatives))
    flags = re.IGNORECASE if ignore_case else re.NOFLAG
    return re.compile(rf"(?<!\w)(?:{body})(?!\w)", flags)


@cache
def any_regex(patterns: tuple[str, ...], *, ignore_case: bool = True) -> re.Pattern[str]:
    """Return one pattern that matches any of the regex sources in `patterns`."""
    body = "|".join(f"(?:{pattern})" for pattern in patterns if pattern) or "(?!)"
    return re.compile(body, re.IGNORECASE if ignore_case else re.NOFLAG)


def hits(
    ctx: Context, pattern: re.Pattern[str], kinds: frozenset[UnitKind] = STYLE_KINDS
) -> Iterator[tuple[Unit, re.Match[str]]]:
    """Yield each match of `pattern` in the masked text of the prose units."""
    return (
        (unit, match)
        for unit in prose_units(ctx, kinds)
        for match in pattern.finditer(masked(unit))
    )


def finding(unit: Unit, start: int, end: int, message: str) -> Finding:
    """Return a finding for the character range `start` to `end` of `unit`."""
    return Finding(message, unit.location(start, end))


def match_findings(found: Iterable[tuple[Unit, re.Match[str]]], message: str) -> Iterator[Finding]:
    """Return one finding per match. `{match}` in `message` becomes the matched text."""
    return (
        finding(unit, match.start(), match.end(), message.format(match=flat(match.group(0))))
        for unit, match in found
    )


def flat(text: str) -> str:
    """Return `text` with each run of white space as one space."""
    return " ".join(text.split())


def unit_sentences(unit: Unit) -> list[tuple[Sentence, str]]:
    """Return the sentences of a unit, each with its masked text."""
    text = masked(unit)
    return [(sentence, text[sentence.start : sentence.end]) for sentence in sentences(unit)]


_WORD = re.compile(r"[^\W\d_](?:[\w­-]*\w)?|\d+(?:[.,]\d+)*")


def words(text: str) -> list[re.Match[str]]:
    """Return the word matches of a (masked) text. Hidden characters are not words."""
    return list(_WORD.finditer(text))
