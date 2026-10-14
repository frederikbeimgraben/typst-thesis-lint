"""A small BibTeX and BibLaTeX parser. It keeps the line of each entry and field."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from thesis_lint.model import Location
from thesis_lint.typst.parse import read_text

if TYPE_CHECKING:
    from pathlib import Path

_SKIP_TYPES = frozenset({"comment", "preamble", "string"})
_FIELD_COMMENT = re.compile(r"\s*%[^\n]*(?:\n|$)")


@dataclass(frozen=True, slots=True)
class BibField:
    """One field of an entry. `value` has the outer braces or quotes removed."""

    name: str
    value: str
    line: int


@dataclass(slots=True)
class BibEntry:
    """One entry, for example `@article{key, ...}`."""

    type: str
    key: str
    path: Path
    line: int
    fields: dict[str, BibField] = field(default_factory=dict[str, BibField])

    def get(self, name: str) -> str | None:
        """Return the cleaned value of a field, or None."""
        entry = self.fields.get(name)
        return None if entry is None else clean(entry.value)

    def raw(self, name: str) -> str | None:
        """Return the value of a field as written, without the outer delimiters."""
        entry = self.fields.get(name)
        return None if entry is None else entry.value

    def has(self, *names: str) -> bool:
        """Return True if one of the fields is set and not empty."""
        return any((self.get(name) or "").strip() for name in names)

    def location(self, name: str | None = None) -> Location:
        """Return the location of the entry or of one field."""
        if name is not None and name in self.fields:
            return Location(self.path, self.fields[name].line, 1)
        return Location(self.path, self.line, 1)

    @property
    def year(self) -> str | None:
        """Return the year from `year` or from `date`."""
        year = self.get("year")
        if year:
            return year
        date = self.get("date")
        return date[:4] if date else None

    def names(self, name: str = "author") -> list[str]:
        """Return the person names of a name field. Braced names stay one name."""
        raw = self.raw(name)
        if raw is None:
            return []
        return [part.strip() for part in _split_and(raw) if part.strip()]


@dataclass(slots=True)
class Bibliography:
    """All entries of one or more `.bib` files."""

    entries: dict[str, BibEntry] = field(default_factory=dict[str, BibEntry])
    errors: list[tuple[Location, str]] = field(default_factory=list[tuple[Location, str]])
    duplicates: list[BibEntry] = field(default_factory=list[BibEntry])


def load(paths: list[Path]) -> Bibliography:
    """Parse the files and return the entries."""
    bibliography = Bibliography()
    for path in paths:
        try:
            text = read_text(path)
        except OSError as exc:
            bibliography.errors.append((Location(path), f"cannot read file: {exc}"))
            continue
        for entry in parse(text, path, bibliography):
            if entry.key in bibliography.entries:
                bibliography.duplicates.append(entry)
            else:
                bibliography.entries[entry.key] = entry
    return bibliography


def parse(text: str, path: Path, sink: Bibliography) -> list[BibEntry]:
    """Parse one file. Write syntax errors to `sink.errors`."""
    entries: list[BibEntry] = []
    index = 0
    length = len(text)
    while True:
        at = text.find("@", index)
        if at < 0:
            break
        if _in_comment(text, at):
            index = at + 1
            continue
        match = re.match(r"@(\w+)\s*([{(])", text[at:])
        if match is None:
            index = at + 1
            continue
        kind = match.group(1).lower()
        open_char = match.group(2)
        close_char = "}" if open_char == "{" else ")"
        body_start = at + match.end()
        body_end = _matching(text, body_start, open_char, close_char)
        line = text.count("\n", 0, at) + 1
        if body_end < 0:
            sink.errors.append((Location(path, line), "entry is not closed"))
            break
        index = body_end + 1
        if kind in _SKIP_TYPES:
            continue
        body = text[body_start:body_end]
        comma = body.find(",")
        key = (body if comma < 0 else body[:comma]).strip()
        entry = BibEntry(type=kind, key=key, path=path, line=line)
        if comma >= 0:
            _fields(body, comma + 1, offset=body_start, text=text, entry=entry, sink=sink)
        entries.append(entry)
        if index >= length:
            break
    return entries


def _fields(  # noqa: PLR0913 - the parser state has many parts
    body: str, position: int, *, offset: int, text: str, entry: BibEntry, sink: Bibliography
) -> None:
    while position < len(body):
        # A line comment between two fields, for example an ignore comment.
        comment = _FIELD_COMMENT.match(body, position)
        if comment is not None:
            position = comment.end()
            continue
        match = re.compile(r"\s*([\w:.+-]+)\s*=\s*").match(body, position)
        if match is None:
            if body[position:].strip(" \t\r\n,"):
                line = text.count("\n", 0, offset + position) + 1
                sink.errors.append(
                    (Location(entry.path, line), f"cannot parse field in {entry.key}")
                )
            return
        name = match.group(1).lower()
        value_start = match.end()
        value, value_end = _value(body, value_start)
        line = text.count("\n", 0, offset + match.start(1)) + 1
        entry.fields[name] = BibField(name, value, line)
        position = value_end
        while position < len(body) and body[position] in " \t\r\n":
            position += 1
        if position < len(body) and body[position] == ",":
            position += 1


def _value(body: str, start: int) -> tuple[str, int]:
    parts: list[str] = []
    position = start
    while position < len(body):
        char = body[position]
        if char == "{":
            end = _matching(body, position + 1, "{", "}")
            end = len(body) - 1 if end < 0 else end
            parts.append(body[position + 1 : end])
            position = end + 1
        elif char == '"':
            end = position + 1
            depth = 0
            while end < len(body):
                if body[end] == "{":
                    depth += 1
                elif body[end] == "}":
                    depth -= 1
                elif body[end] == '"' and depth == 0:
                    break
                end += 1
            parts.append(body[position + 1 : end])
            position = end + 1
        else:
            match = re.compile(r"[\w.:+-]+").match(body, position)
            if match is None:
                break
            parts.append(match.group(0))
            position = match.end()
        rest = re.compile(r"\s*#\s*").match(body, position)
        if rest is None:
            break
        position = rest.end()
    return "".join(parts), position


def _matching(text: str, start: int, open_char: str, close_char: str) -> int:
    depth = 1
    position = start
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return position
        position += 1
    return -1


def _in_comment(text: str, position: int) -> bool:
    line_start = text.rfind("\n", 0, position) + 1
    return "%" in text[line_start:position]


def _split_and(value: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    pieces = re.split(r"(\s+and\s+|[{}])", value)
    for piece in pieces:
        if piece == "{":
            depth += 1
            current.append(piece)
        elif piece == "}":
            depth -= 1
            current.append(piece)
        elif depth == 0 and re.fullmatch(r"\s+and\s+", piece):
            parts.append("".join(current))
            current = []
        else:
            current.append(piece)
    parts.append("".join(current))
    return parts


def clean(value: str) -> str:
    """Remove braces and simple LaTeX escapes, and collapse white space."""
    result = value.replace("{", "").replace("}", "")
    result = re.sub(r"\\([&%$#_])", r"\1", result)
    result = result.replace("~", " ")
    return re.sub(r"\s+", " ", result).strip()
