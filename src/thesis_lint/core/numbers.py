"""Rules for numbers, units, operators and the typography of the running text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

from thesis_lint.core.prose import (
    STYLE_KINDS,
    TEXT_KINDS,
    finding,
    hits,
    is_hidden,
    masked,
    prose_units,
)
from thesis_lint.core.sources import BRINK, HW, ref
from thesis_lint.model import Severity
from thesis_lint.registry import Finding, NoParams, rule

if TYPE_CHECKING:
    from collections.abc import Iterator

    from thesis_lint.context import Context
    from thesis_lint.typst.document import Unit, UnitKind

# Unit symbols. Single capital letters like "A" or "B" are not in the list,
# because they are often labels ("Variante 2 B").
UNITS: tuple[str, ...] = (
    "%",
    "‰",
    "°C",
    "°F",
    "nm",
    "µm",
    "μm",
    "mm",
    "cm",
    "m",
    "km",
    "m²",
    "m³",
    "ns",
    "µs",
    "μs",
    "ms",
    "s",
    "min",
    "h",
    "mg",
    "g",
    "kg",
    "ml",
    "Hz",
    "kHz",
    "MHz",
    "GHz",
    "mW",
    "W",
    "kW",
    "MW",
    "mV",
    "V",
    "kV",
    "mA",
    "Ω",
    "kJ",
    "Pa",
    "kPa",
    "hPa",
    "bar",
    "dB",
    "kB",
    "KB",
    "MB",
    "GB",
    "TB",
    "KiB",
    "MiB",
    "GiB",
    "TiB",
    "bit",
    "kbit",
    "Mbit",
    "Gbit",
    "px",
    "dpi",
    "€",
)

# Words before a number that make the number a designator, not a quantity.
DESIGNATORS: tuple[str, ...] = (
    "S.",
    "Seite",
    "Seiten",
    "Kapitel",
    "Kap.",
    "Abschnitt",
    "Abschnitte",
    "Abb.",
    "Abbildung",
    "Tab.",
    "Tabelle",
    "Anhang",
    "Anh.",
    "Nr.",
    "Art.",
    "Artikel",
    "Abs.",
    "Absatz",
    "Rn.",
    "Ziffer",
    "Version",
    "Ver.",
    "Formel",
    "Gleichung",
    "Teil",
    "Band",
    "Bd.",
    "Heft",
    "Vol.",
    "No.",
    "Klasse",
    "Stufe",
    "Level",
    "Phase",
    "Schritt",
    "Typ",
)

# Space characters between a number and a unit that do not break.
_PROTECTED = frozenset({" ", " "})
_PREVIOUS_TOKEN = re.compile(r"(\S+)\s*$")


def previous_token(text: str, index: int) -> str:
    """Return the token before `index`, without the space between."""
    match = _PREVIOUS_TOKEN.search(text, 0, index)
    return "" if match is None else match.group(1)


def _is_code_like(token: str) -> bool:
    """Return True for tokens like 'GPT', 'ISO' or 'v2' before a number."""
    return any(char.isdigit() for char in token) or sum(char.isupper() for char in token) >= 2


@cache
def _unit_regex(units: tuple[str, ...]) -> re.Pattern[str]:
    body = "|".join(re.escape(unit) for unit in sorted(units, key=len, reverse=True))
    return re.compile(rf"(?P<space>[    ]?)(?P<unit>{body})(?!\w)")


def _masked_matches(
    ctx: Context, pattern: re.Pattern[str], kinds: frozenset[UnitKind]
) -> Iterator[tuple[Unit, str, re.Match[str]]]:
    """Yield each match of `pattern` with its unit and the masked unit text."""
    return (
        (unit, text, match)
        for unit in prose_units(ctx, kinds)
        for text in (masked(unit),)
        for match in pattern.finditer(text)
    )


@dataclass(frozen=True, slots=True)
class SpellSmallParams:
    """Parameters of core.number.spell-small."""

    max_value: int = 12
    units: tuple[str, ...] = (*UNITS, "Uhr", "Prozent")
    designators: tuple[str, ...] = DESIGNATORS


_SMALL = re.compile(r"(?<![\w.,/:\-–])\d{1,2}(?!\w)")
_NUMBER_FOLLOWERS = frozenset({".", ":", "/", "-", "–", ")", "(", "²", "³"})


def small_number_is_exempt(text: str, match: re.Match[str], params: SpellSmallParams) -> bool:
    """Return True if a small number in `text` can stay a digit."""
    end = match.end()
    following = text[end : end + 2]
    if following[:1] in _NUMBER_FOLLOWERS:
        # An ordinal, a date, a time, a fraction, a range, a compound, a list mark or a power.
        return True
    if following[:1] == "," and following[1:2].isdigit():
        return True
    if _unit_regex(params.units).match(text, end):
        return True
    token = previous_token(text, match.start())
    designators = frozenset(params.designators)
    return token in designators or token.rstrip(",:") in designators or _is_code_like(token)


@rule(
    "core.number.spell-small",
    summary="Whole numbers below 13 are words in the running text.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 194",
            "ganze Zahlen unter „13“ (...) im Text auszuschreiben sind.",
        )
    ],
    params=SpellSmallParams(),
)
def spell_small(ctx: Context, params: SpellSmallParams) -> Iterator[Finding]:
    """Report small whole numbers as digits.

    The rule does not report numbers with a unit, ordinals, dates, ranges, decimal
    numbers, numbers after a designator like "S." or "Kapitel", and numbers in
    math, raw text, references and quotations.
    """
    return (
        finding(
            unit,
            match.start(),
            match.end(),
            f"the number {match.group(0)} is a digit. Write it as a word.",
        )
        for unit, text, match in _masked_matches(ctx, _SMALL, STYLE_KINDS)
        if int(match.group(0)) <= params.max_value
        and not (len(match.group(0)) == 2 and match.group(0).startswith("0"))
        and not small_number_is_exempt(text, match, params)
    )


@dataclass(frozen=True, slots=True)
class DecimalParams:
    """Parameters of core.number.decimal."""

    designators: tuple[str, ...] = DESIGNATORS
    identifier_prefixes: tuple[str, ...] = (
        "ISO",
        "IEC",
        "EN",
        "DIN",
        "IEEE",
        "ISBN",
        "ISSN",
        "DOI",
        "PMID",
        "Nr.",
        "ID",
    )
    min_group_digits: int = 5


_DOTTED = re.compile(r"(?<![\w.,/\-–])(\d+)((?:\.\d+)+)(?![\w]|,\d)")
_LONG = re.compile(r"(?<![\w.,/\-–:])\d+(?![\w/\-:]|[.,]\d)")


def dotted_message(text: str, match: re.Match[str], designators: frozenset[str]) -> str | None:
    """Return the message for a number with periods, or None if the number is fine."""
    whole = match.group(1)
    groups = match.group(2).split(".")[1:]
    if len(whole) <= 3 and all(len(group) == 3 for group in groups):
        return (
            f"{match.group(0)!r} uses a period to group the digits. Use a narrow "
            "non-breaking space."
        )
    if len(groups) > 1:
        # A date, a version or a section number like 1.2.3.
        return None
    token = previous_token(text, match.start())
    if token in designators or _is_code_like(token):
        return None
    return f"{match.group(0)!r} uses a decimal point. Use a decimal comma."


def _long_is_exempt(
    text: str, match: re.Match[str], params: DecimalParams, exempt_tokens: frozenset[str]
) -> bool:
    token = previous_token(text, match.start())
    return (
        len(match.group(0)) < params.min_group_digits
        or token in exempt_tokens
        or _is_code_like(token)
    )


@rule(
    "core.number.decimal",
    summary="Numbers use a decimal comma, no period to group digits and group 5 or more digits.",
    severity=Severity.ERROR,
    sources=[
        ref(
            HW,
            "S. 206",
            "In der Dezimalschreibweise ist der Punkt als Gliederungszeichen nicht zulässig.",
        )
    ],
    params=DecimalParams(),
)
def decimal(ctx: Context, params: DecimalParams) -> Iterator[Finding]:
    """Report decimal points, periods as group marks and long numbers without groups."""
    designators = frozenset(params.designators)
    exempt_tokens = designators | frozenset(params.identifier_prefixes)
    for unit, text, match in _masked_matches(ctx, _DOTTED, TEXT_KINDS):
        message = dotted_message(text, match, designators)
        if message is not None:
            yield finding(unit, match.start(), match.end(), message)
    yield from (
        finding(
            unit,
            match.start(),
            match.end(),
            f"{match.group(0)!r} has no digit groups. Group the digits in threes.",
        )
        for unit, text, match in _masked_matches(ctx, _LONG, TEXT_KINDS)
        if not _long_is_exempt(text, match, params, exempt_tokens)
    )


@dataclass(frozen=True, slots=True)
class UnitSpaceParams:
    """Parameters of core.number.unit-space."""

    units: tuple[str, ...] = UNITS


_NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?")


@rule(
    "core.number.unit-space",
    summary="A number and its unit are separated by a (narrow) non-breaking space.",
    severity=Severity.ERROR,
    sources=[
        ref(
            HW,
            "S. 119",
            "Zwischen Zahlenwert und Einheit (inkl. %-Zeichen) wird ein geschütztes Leerzeichen",
        ),
        ref(
            HW,
            "S. 207",
            "Bei Größen steht ein (halbes, geschütztes) Leerzeichen",
        ),
    ],
    params=UnitSpaceParams(),
)
def unit_space(ctx: Context, params: UnitSpaceParams) -> Iterator[Finding]:
    """Report a unit after a number without a non-breaking space. Write `5~%` in Typst."""
    units = _unit_regex(params.units)
    for unit, text, match in _masked_matches(ctx, _NUMBER, TEXT_KINDS):
        found = units.match(text, match.end())
        if found is None or found.group("space") in _PROTECTED:
            continue
        yield finding(
            unit,
            match.start(),
            found.end(),
            f"no non-breaking space before unit {found.group('unit')!r}. Use '~' or U+202F.",
        )


_OPERATOR = re.compile(r"[+×÷=<>]")
_ARROW_PARTS = frozenset("-=<>+")


def is_operator(text: str, index: int) -> bool:
    """Return True if the character at `index` is a binary operator between terms."""
    before = text[index - 1] if index > 0 else " "
    after = text[index + 1] if index + 1 < len(text) else " "
    if before in _ARROW_PARTS or after in _ARROW_PARTS:
        # An arrow like "->" or "=>", or a name like "C++".
        return False
    if before.isdigit():
        return True
    return before.isspace() and after.isspace()


@rule(
    "core.number.operators",
    summary="The running text has no math operators. Use words or math mode.",
    severity=Severity.ERROR,
    sources=[
        ref(
            BRINK,
            "S. 194",
            "obwohl dieses nur in Formeln zulässig ist",
        )
    ],
)
def operators(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report arithmetic operators, for example plus, times or equals, outside math."""
    return (
        finding(
            unit,
            match.start(),
            match.end(),
            f"operator {match.group(0)!r} in the running text. Write it as a word or use math.",
        )
        for unit, text, match in _masked_matches(ctx, _OPERATOR, STYLE_KINDS)
        if is_operator(text, match.start())
    )


_HYPHEN_DASH = re.compile(r"(?<=\s)-(?=\s)")


@rule(
    "core.typo.dash",
    summary="A dash between words is an en dash, not a hyphen.",
    severity=Severity.ERROR,
    sources=[
        ref(
            HW,
            "S. 206",
            "Der lange Gedankenstrich ‚–‘ ist für Einschübe (...) vorgesehen.",
        )
    ],
)
def dash(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report ' - ' in prose."""
    return (
        finding(unit, match.start(), match.end(), "hyphen as a dash. Write '--' for an en dash.")
        for unit, match in hits(ctx, _HYPHEN_DASH, TEXT_KINDS)
    )


_SPACE_RUN = re.compile(r" +")


def double_spaces(unit: Unit) -> Iterator[tuple[int, int]]:
    """Yield the byte ranges of runs of two or more spaces in the source of a unit.

    A run that contains a line break is indentation or a line end, so it does
    not count. The unit text collapses some spaces, so the check reads the source.
    """
    data = unit.source.data
    for match in _SPACE_RUN.finditer(unit.text):
        if any(is_hidden(char) for char in match.group(0)):
            continue
        begin = unit.byte_at(match.start())
        end = unit.byte_at(match.end()) if match.end() < len(unit.text) else unit.end_byte
        gap = data[begin:end]
        if len(gap) >= 2 and not gap.strip(b" "):
            yield begin, end


@rule(
    "core.typo.double-space",
    summary="The running text has no double spaces.",
    severity=Severity.ERROR,
    sources=[
        ref(HW, "S. 207", "Zwischen den Wörtern im Beispiel steht ein überflüssiges Leerzeichen.")
    ],
)
def double_space(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report two or more spaces between words in the source of prose."""
    return (
        Finding("double space. Use one space.", unit.source.location(begin, end))
        for unit in prose_units(ctx, TEXT_KINDS)
        for begin, end in double_spaces(unit)
    )
