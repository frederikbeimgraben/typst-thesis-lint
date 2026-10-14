"""Inline suppression comments.

Syntax in Typst files: `// ignore: rule.a,rule.b; reason`.
Syntax in BibTeX files: `% ignore: rule.a,rule.b; reason`.

A comment suppresses the findings of the given rules that start on the line
of the comment or on the next line. The rule IDs and the reason are required.
The engine reports a comment with a syntax error, an unknown rule ID, or a
rule ID that suppresses nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

from thesis_lint.model import Diagnostic, Location, Severity
from thesis_lint.typst.parse import SourceFile, read_text, walk

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

SYNTAX_RULE = "ignore.syntax"
UNKNOWN_RULE = "ignore.unknown-rule"
UNUSED_RULE = "ignore.unused"

_MARKER = re.compile(r"^\s*ignore\s*:")
_BODY = re.compile(r"^\s*ignore\s*:\s*(?P<ids>[^;]*?)\s*(?:;\s*(?P<reason>.*?))?\s*$", re.DOTALL)
_RULE_ID = re.compile(r"[a-z0-9]+(?:\.[a-z0-9-]+)+")


@dataclass(frozen=True, slots=True)
class Comment:
    """A comment with its text and the location of its start."""

    location: Location
    text: str


@dataclass(frozen=True, slots=True)
class Suppression:
    """A valid suppression comment."""

    location: Location
    rule_ids: tuple[str, ...]
    reason: str

    def covers(self, diagnostic: Diagnostic) -> bool:
        """Return True if this comment suppresses the diagnostic."""
        loc = diagnostic.location
        return (
            diagnostic.rule_id in self.rule_ids
            and loc.path.resolve() == self.location.path.resolve()
            and loc.line in {self.location.line, self.location.line + 1}
        )


@dataclass(frozen=True, slots=True)
class Outcome:
    """The kept diagnostics, the number of suppressed ones, and findings about the comments."""

    kept: tuple[Diagnostic, ...]
    suppressed: int
    comment_findings: tuple[Diagnostic, ...]


def typst_comments(source: SourceFile) -> Iterator[Comment]:
    """Yield the comments of a Typst file without the comment markers."""
    return (
        Comment(source.node_location(node), _strip_typst(source.node_text(node)))
        for node in walk(source.root)
        if node.type == "comment"
    )


def bib_comments(path: Path) -> Iterator[Comment]:
    """Yield the `%` comments of a BibTeX file. An escaped percent sign is not a comment."""
    try:
        lines = read_text(path).split("\n")
    except OSError:
        return iter(())
    return (
        Comment(Location(path, number, match.start() + 1), line[match.end() :])
        for number, line in enumerate(lines, start=1)
        if (match := re.search(r"(?<!\\)%", line)) is not None
    )


def _strip_typst(text: str) -> str:
    if text.startswith("//"):
        return text[2:]
    if text.startswith("/*"):
        return text[2:].removesuffix("*/")
    return text


def parse(
    comments: Iterable[Comment], known: frozenset[str]
) -> tuple[list[Suppression], list[Diagnostic]]:
    """Return the valid suppressions and the findings about invalid comments."""
    results = [_parse_one(comment, known) for comment in comments if _MARKER.match(comment.text)]
    suppressions = [item for item, _ in results if item is not None]
    findings = list(chain.from_iterable(problems for _, problems in results))
    return suppressions, findings


def _parse_one(
    comment: Comment, known: frozenset[str]
) -> tuple[Suppression | None, list[Diagnostic]]:
    match = _BODY.match(comment.text)
    ids_text = "" if match is None else match.group("ids")
    reason = "" if match is None else (match.group("reason") or "")
    ids = tuple(part.strip() for part in ids_text.split(",") if part.strip())
    syntax = [
        Diagnostic(SYNTAX_RULE, Severity.ERROR, message, comment.location)
        for condition, message in (
            (not ids, "the ignore comment has no rule IDs. Write `ignore: rule.id; reason`."),
            (not reason, "the ignore comment has no reason. Add `; reason` after the rule IDs."),
            (
                any(not _RULE_ID.fullmatch(rule_id) for rule_id in ids),
                "the rule IDs of the ignore comment must be separated by commas.",
            ),
        )
        if condition
    ]
    if syntax:
        return None, syntax
    unknown = [
        Diagnostic(
            UNKNOWN_RULE,
            Severity.ERROR,
            f"the ignore comment names the unknown rule {rule_id!r}.",
            comment.location,
        )
        for rule_id in ids
        if rule_id not in known
    ]
    return Suppression(comment.location, ids, reason), unknown


def apply(
    diagnostics: Iterable[Diagnostic],
    suppressions: list[Suppression],
    ran: frozenset[str],
) -> Outcome:
    """Remove the suppressed diagnostics and report the unused rule IDs of the comments.

    Only rules in `ran` can make a rule ID used. A comment for a rule that did not run
    (for example a PDF rule in the language server) is not reported as unused.
    """
    items = list(diagnostics)
    covered = [(d, [s for s in suppressions if s.covers(d)]) for d in items]
    kept = tuple(d for d, matches in covered if not matches)
    used = {(id(s), d.rule_id) for d, matches in covered for s in matches}
    unused = tuple(
        Diagnostic(
            UNUSED_RULE,
            Severity.WARNING,
            f"the ignore comment for {rule_id!r} suppresses nothing. Remove the rule ID.",
            suppression.location,
        )
        for suppression in suppressions
        for rule_id in suppression.rule_ids
        if rule_id in ran and (id(suppression), rule_id) not in used
    )
    return Outcome(kept=kept, suppressed=len(items) - len(kept), comment_findings=unused)
