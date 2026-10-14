"""Split prose into sentences and words. The rules are heuristics for German text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from thesis_lint.typst.document import PLACEHOLDERS, REF_MARK, Unit

if TYPE_CHECKING:
    from collections.abc import Iterator

# Abbreviations that end with a period but do not end a sentence.
ABBREVIATIONS = frozenset(
    {
        "z.B",
        "z. B",
        "d.h",
        "d. h",
        "u.a",
        "u. a",
        "bzw",
        "ggf",
        "ca",
        "vgl",
        "Nr",
        "Abs",
        "Kap",
        "S",
        "Abb",
        "Tab",
        "al",
        "usw",
        "etc",
        "i.d.R",
        "i. d. R",
        "z.T",
        "z. T",
        "Dr",
        "Prof",
        "bspw",
        "inkl",
        "evtl",
        "insb",
        "Insb",
        "Anh",
        "Art",
        "Bd",
        "Hrsg",
        "Aufl",
        "sog",
        "o.V",
        "o.J",
        "o.O",
        "u.U",
        "u. U",
        "v.a",
        "v. a",
        "s",
        "f",
        "ff",
        "Fa",
        "Mio",
        "Mrd",
        "max",
        "min",
        "Std",
        "bzgl",
        "zzgl",
        "vs",
        "Ver",
        "Vol",
        "No",
        "ed",
        "Ed",
        "pp",
        "p",
        "Jh",
        "Jhd",
        "o.a",
        "o. a",
        "u.v.m",
        "allg",
        "ebd",
    }
)
_END = re.compile(r"[.!?…]+[“”’)\]]*")
_WORD = re.compile(r"[^\W\d_](?:[\w­-]*\w)?|\d+(?:[.,]\d+)*", re.UNICODE)
_LETTER_WORD = re.compile(r"[^\W\d_][\w­-]*", re.UNICODE)


@dataclass(frozen=True, slots=True)
class Sentence:
    """A sentence in a unit. `start` and `end` are character indexes in the unit text."""

    unit: Unit
    start: int
    end: int

    @property
    def text(self) -> str:
        """Return the sentence text."""
        return self.unit.text[self.start : self.end]

    def words(self) -> list[re.Match[str]]:
        """Return the word matches. Positions are relative to the sentence start."""
        return list(_WORD.finditer(self.text))

    def letter_words(self) -> list[str]:
        """Return the words that start with a letter."""
        return [m.group(0) for m in _LETTER_WORD.finditer(self.text)]

    def has_citation(self) -> bool:
        """Return True if the sentence contains a reference mark."""
        return REF_MARK in self.text


def sentences(unit: Unit) -> list[Sentence]:
    """Split the text of a unit into sentences."""
    text = unit.text
    result: list[Sentence] = []
    start = 0
    for match in _END.finditer(text):
        end = match.end()
        if not _is_boundary(text, match.start(), end):
            continue
        # A reference or footnote mark right after the period belongs to the sentence.
        while end < len(text) and text[end] in PLACEHOLDERS:
            end += 1
        chunk = text[start:end]
        if chunk.strip():
            lead = len(chunk) - len(chunk.lstrip())
            result.append(Sentence(unit, start + lead, end))
        start = end
    rest = text[start:]
    if rest.strip():
        lead = len(rest) - len(rest.lstrip())
        result.append(Sentence(unit, start + lead, len(text.rstrip())))
    return result


def _is_boundary(text: str, dot: int, end: int) -> bool:
    if end < len(text) and not text[end].isspace() and text[end] not in PLACEHOLDERS:
        return False
    if text[dot] != ".":
        return _next_starts_sentence(text, end)
    before = text[:dot]
    token = re.search(r"([\w.]+(?: [\w]\.?)*)$", before)
    if token is not None:
        word = token.group(1)
        last = word.rsplit(" ", 1)[-1]
        if word in ABBREVIATIONS or last in ABBREVIATIONS:
            return False
        if len(last) == 1 and last.isalpha():
            # An initial, for example "A. Brink".
            return False
        if last.isdigit() and not _next_starts_sentence(text, end, strict=True):
            # An ordinal number, for example "3. Auflage".
            return False
    return _next_starts_sentence(text, end)


def _next_starts_sentence(text: str, end: int, *, strict: bool = False) -> bool:
    rest = text[end:].lstrip("  " + "".join(PLACEHOLDERS))
    if not rest:
        return True
    first = rest[0]
    if first.isupper() or first in "„‚\"'(":
        return True
    return not strict and first.isdigit()


def words(text: str) -> list[str]:
    """Return the words of a text. Placeholders are not words."""
    return [m.group(0) for m in _WORD.finditer(text)]


def word_count(text: str) -> int:
    """Return the number of words."""
    return len(words(text))


def iter_words(text: str) -> Iterator[re.Match[str]]:
    """Yield the word matches of a text."""
    yield from _WORD.finditer(text)
