"""Rules for the bibliography file."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

from thesis_lint.core.sources import BRINK, DFG, HW, LANGE, VORLAGE, ref
from thesis_lint.model import Severity
from thesis_lint.registry import Finding, NoParams, rule

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from thesis_lint.bib import BibEntry
    from thesis_lint.context import Context

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_PERSON_FIELDS = ("author", "editor")


def _entries(ctx: Context) -> Iterator[BibEntry]:
    return iter(ctx.project.bibliography.entries.values())


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


# --- core.bib.required-fields ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RequiredFieldsParams:
    """Parameters of `core.bib.required-fields`.

    Each item of `types` has the form `type: field, field, ...`. A field can name
    alternatives with `|`, for example `year|date`. One alternative is sufficient.
    The rule does not check entry types that are not in the list.
    """

    types: tuple[str, ...] = (
        "article: author, title, journaltitle|journal, year|date, volume, pages",
        "book: author|editor, title, year|date, location|address, publisher",
        "incollection: author, title, editor, booktitle, year|date, location|address, publisher, pages",  # noqa: E501 - one item per entry type
        "inproceedings: author, title, booktitle, year|date, pages",
        "online: author|organization, title, year|date, url, urldate",
        "thesis: author, title, year|date, type, institution|school",
        "misc: title, year|date",
    )


def parse_requirements(specs: Iterable[str]) -> dict[str, tuple[tuple[str, ...], ...]]:
    """Return the required field groups for each entry type."""
    return {
        kind.strip().lower(): tuple(
            tuple(name.strip().lower() for name in group.split("|"))
            for group in fields.split(",")
            if group.strip()
        )
        for kind, _, fields in (spec.partition(":") for spec in specs)
    }


@rule(
    "core.bib.required-fields",
    summary="Each entry has the required fields of its type.",
    severity=Severity.ERROR,
    sources=[
        ref(HW, "Tab. 7.1"),
        ref(BRINK, "S. 208", "Name und Vorname des Verfassers, Titel und ggf. Untertitel"),
    ],
    params=RequiredFieldsParams(),
)
def required_fields(ctx: Context, params: RequiredFieldsParams) -> Iterator[Finding]:
    """Report entries that do not have all required fields of their type."""
    requirements = parse_requirements(params.types)
    for entry in _entries(ctx):
        missing = [
            "|".join(group) for group in requirements.get(entry.type, ()) if not entry.has(*group)
        ]
        if missing:
            yield Finding(
                f"@{entry.type} entry {entry.key!r} has no field {', '.join(missing)}. Add it.",
                entry.location(),
            )


# --- core.bib.cited -------------------------------------------------------------------


@rule(
    "core.bib.cited",
    summary="Each cited key exists, each entry is cited, and no bibliography uses `full: true`.",
    severity=Severity.ERROR,
    sources=[
        ref(HW, "S. 184", "enthält das Literaturverzeichnis nur Vollbelege"),
        ref(
            BRINK,
            "S. 206",
            "Titel, die zwar gelesen, nicht aber zitiert sind, dürfen nicht erfasst werden.",
        ),
    ],
    submission=True,
)
def cited(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report unknown keys, uncited entries and `full: true`.

    An unknown key is always an error. The other findings are submission findings.
    """
    project = ctx.project
    document = project.document
    units = chain(document.units, () if project.abstract is None else (project.abstract,))
    references = [reference for unit in units for reference in unit.references]
    known = set(document.labels) | set(project.terms) | set(project.acronyms)
    yield from (
        Finding(
            " ".join(
                (
                    f"the key {reference.key!r} is not in the bibliography and is not a label.",
                    "Correct the key or add the entry.",
                )
            ),
            reference.location,
            submission=False,
        )
        for reference in references
        if not project.is_citation(reference.key) and reference.key not in known
    )
    yield from (
        Finding(
            "the bibliography uses `full: true`. Remove it to list only the cited entries.",
            call.source.node_location(call.node),
        )
        for call in project.bibliography_calls
        if call.full
    )
    used = {reference.key for reference in references}
    yield from (
        Finding(f"entry {entry.key!r} is not cited. Cite it or remove it.", entry.location())
        for entry in _entries(ctx)
        if entry.key not in used
    )


# --- core.bib.author-present ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorPresentParams:
    """Parameters of `core.bib.author-present`. One of `fields` must be set."""

    fields: tuple[str, ...] = ("author", "editor", "organization", "institution")


@rule(
    "core.bib.author-present",
    summary="Each entry names an author, an editor or an organization.",
    severity=Severity.ERROR,
    sources=[ref(VORLAGE, "Literaturverzeichnis")],
    params=AuthorPresentParams(),
)
def author_present(ctx: Context, params: AuthorPresentParams) -> Iterator[Finding]:
    """Report entries without an author field."""
    yield from (
        Finding(
            " ".join(
                (
                    f"entry {entry.key!r} has no {'|'.join(params.fields)}.",
                    "Add the author or the organization.",
                )
            ),
            entry.location(),
        )
        for entry in _entries(ctx)
        if not entry.has(*params.fields)
    )


# --- core.bib.academic-title ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AcademicTitleParams:
    """Parameters of `core.bib.academic-title`. Spaces after a period are optional."""

    titles: tuple[str, ...] = ("Dr.", "Prof.", "Dipl.", "M.Sc.", "B.Sc.")


def title_pattern(titles: Iterable[str]) -> re.Pattern[str]:
    """Return a pattern that finds one of the titles at the start of a word."""
    alternatives = "|".join(
        re.escape(title.replace(" ", "")).replace(r"\.", r"\.\s*") for title in titles
    )
    return re.compile(rf"(?<!\w)(?:{alternatives})")


@rule(
    "core.bib.academic-title",
    summary="Person names in the bibliography have no academic titles.",
    severity=Severity.ERROR,
    sources=[
        ref(BRINK, "S. 207", "Beim Zitieren bleiben akademische Grade unberücksichtigt"),
        ref(HW, "S. 179"),
    ],
    params=AcademicTitleParams(),
)
def academic_title(ctx: Context, params: AcademicTitleParams) -> Iterator[Finding]:
    """Report names in `author` or `editor` that contain an academic title."""
    pattern = title_pattern(params.titles)
    yield from (
        Finding(
            f"entry {entry.key!r}: the name {name!r} has an academic title. Remove it.",
            entry.location(field),
        )
        for entry in _entries(ctx)
        for field in _PERSON_FIELDS
        for name in entry.names(field)
        if pattern.search(name)
    )


# --- core.bib.edition-one -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EditionOneParams:
    """Parameters of `core.bib.edition-one`. The pattern finds a first edition."""

    pattern: str = r"(?i)^\s*(?:1|1\.|1st|first|erste)(?:\s|$|\.)"


@rule(
    "core.bib.edition-one",
    summary="An entry does not give the first edition.",
    severity=Severity.ERROR,
    sources=[
        ref(BRINK, "S. 208"),
        ref(HW, "S. 182", "Handelt es sich um die erste Auflage, dann"),
    ],
    params=EditionOneParams(),
)
def edition_one(ctx: Context, params: EditionOneParams) -> Iterator[Finding]:
    """Report `edition` fields with the value 1."""
    pattern = re.compile(params.pattern)
    yield from (
        Finding(
            f"entry {entry.key!r} gives the first edition. Remove the edition field.",
            entry.location("edition"),
        )
        for entry in _entries(ctx)
        if pattern.search(entry.get("edition") or "")
    )


# --- core.bib.not-citable -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NotCitableParams:
    """Parameters of `core.bib.not-citable`. A field that contains a domain is not citable."""

    domains: tuple[str, ...] = (
        "wikipedia.org",
        "wikibooks.org",
        "wiktionary.org",
        "britannica.com",
        "brockhaus.de",
        "duden.de",
        "enzyklo.de",
    )
    fields: tuple[str, ...] = ("url", "howpublished")


def _first_domain(value: str, domains: Iterable[str]) -> str:
    return next((domain for domain in domains if domain.lower() in value.lower()), "")


@rule(
    "core.bib.not-citable",
    summary="The bibliography does not cite Wikipedia or general encyclopedias.",
    severity=Severity.ERROR,
    sources=[
        ref(HW, "S. 144", "Wikipedia liefern keine zitierfähigen Informationen"),
        ref(BRINK, "S. 220", "für wissenschaftliche Zwecke ansonsten verpönten"),
        ref(LANGE, "S. 72", "Allgemeine Lexika (auch wikipedia, google, …)"),
    ],
    params=NotCitableParams(),
)
def not_citable(ctx: Context, params: NotCitableParams) -> Iterator[Finding]:
    """Report entries whose URL points to an encyclopedia."""
    yield from (
        Finding(
            " ".join(
                (
                    f"entry {entry.key!r} cites {domain}. This source is not citable.",
                    "Use a scientific source.",
                )
            ),
            entry.location(field),
        )
        for entry in _entries(ctx)
        for field in params.fields
        if (domain := _first_domain(entry.get(field) or "", params.domains))
    )


# --- core.bib.duplicate ---------------------------------------------------------------

_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


def normalize_doi(value: str) -> str:
    """Return the DOI without a resolver prefix, in lower case."""
    return _DOI_PREFIX.sub("", value.strip()).lower()


def normalize_title(value: str) -> str:
    """Return the title in lower case with only letters and digits."""
    return "".join(char for char in value.lower() if char.isalnum())


@rule(
    "core.bib.duplicate",
    summary="The bibliography has no duplicate entries (same key, DOI or title).",
    severity=Severity.ERROR,
    sources=[ref(DFG, "Leitlinie 12")],
)
def duplicate(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report entries with the same key, the same DOI or the same normalized title."""
    bibliography = ctx.project.bibliography
    yield from (
        Finding(f"the key {entry.key!r} occurs more than once. Remove one.", entry.location())
        for entry in bibliography.duplicates
    )
    groups: defaultdict[tuple[str, str], list[BibEntry]] = defaultdict(list)
    keyed = (
        (kind, normalize(entry.get(field) or ""), entry)
        for entry in bibliography.entries.values()
        for kind, field, normalize in (
            ("DOI", "doi", normalize_doi),
            ("title", "title", normalize_title),
        )
    )
    for kind, value, entry in keyed:
        if value:
            groups[kind, value].append(entry)
    yield from (
        Finding(
            f"entry {later.key!r} has the same {kind} as {group[0].key!r}. Merge the entries.",
            later.location(),
        )
        for (kind, _), group in groups.items()
        for later in group[1:]
    )


# --- core.bib.doi-and-url -------------------------------------------------------------


@rule(
    "core.bib.doi-and-url",
    summary="An entry does not have both a DOI and a URL.",
    severity=Severity.WARNING,
    sources=[ref(HW, "S. 181", "Digital Object Identifier (DOI), so ist diese permanente")],
)
def doi_and_url(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report entries with both `doi` and `url`."""
    yield from (
        Finding(
            f"entry {entry.key!r} has a doi and a url. Keep only the doi.", entry.location("url")
        )
        for entry in _entries(ctx)
        if entry.has("doi") and entry.has("url")
    )


# --- core.bib.questionable ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QuestionableParams:
    """Parameters of `core.bib.questionable`.

    `types` are entry types that are not published. A thesis entry is a student
    thesis if its `type` field contains one of `thesis_types`. The entry types in
    `student_entry_types` are always student theses. An entry is lecture notes if
    one of `keyword_fields` contains one of `keywords`.
    """

    types: tuple[str, ...] = ("unpublished",)
    thesis_types: tuple[str, ...] = ("Seminar", "Bachelor", "Master", "Diplom")
    student_entry_types: tuple[str, ...] = ("mastersthesis",)
    keywords: tuple[str, ...] = ("Skript",)
    keyword_fields: tuple[str, ...] = ("title", "type", "howpublished", "note")


def _questionable_reason(entry: BibEntry, params: QuestionableParams) -> str | None:
    if entry.type in params.types:
        return f"is @{entry.type}"
    kind = (entry.get("type") or "").lower()
    if entry.type in params.student_entry_types or (
        entry.type == "thesis" and any(word.lower() in kind for word in params.thesis_types)
    ):
        return "is a student thesis"
    text = " ".join(entry.get(field) or "" for field in params.keyword_fields).lower()
    word = next((word for word in params.keywords if word.lower() in text), None)
    return None if word is None else f"contains {word!r}"


@rule(
    "core.bib.questionable",
    summary="The bibliography has no unpublished sources, student theses or lecture notes.",
    severity=Severity.WARNING,
    sources=[
        ref(BRINK, "S. 220", "Zitierfähig sind grundsätzlich nur Quellen, die beschaffbar"),
        ref(HW, "S. 53", "studentische Arbeiten nicht zitierfähig"),
    ],
    params=QuestionableParams(),
)
def questionable(ctx: Context, params: QuestionableParams) -> Iterator[Finding]:
    """Report entries that are probably not citable."""
    yield from (
        Finding(
            " ".join(
                (
                    f"entry {entry.key!r} {reason}. Make sure that it is citable,",
                    "or use a published source.",
                )
            ),
            entry.location(),
        )
        for entry in _entries(ctx)
        if (reason := _questionable_reason(entry, params)) is not None
    )


# --- core.bib.firstname-consistent ----------------------------------------------------

_INITIAL = re.compile(r"^[^\W\d_]\.?(?:-[^\W\d_]\.?)*$")
_PARTS_WITH_COMMA = 2


def given_names(name: str) -> list[str]:
    """Return the given names of a BibTeX person name. A braced name has none."""
    text = name.strip()
    if text.startswith("{") and text.endswith("}"):
        return []
    parts = [part.strip() for part in text.replace("{", "").replace("}", "").split(",")]
    if len(parts) >= _PARTS_WITH_COMMA:
        return parts[-1].split()
    return parts[0].split()[:-1]


def name_style(name: str) -> str | None:
    """Return `abbreviated`, `full`, or None if the name has no given names."""
    given = given_names(name)
    if not given:
        return None
    return "abbreviated" if all(_INITIAL.match(token) for token in given) else "full"


@rule(
    "core.bib.firstname-consistent",
    summary="Given names are either all written in full or all abbreviated.",
    severity=Severity.ERROR,
    sources=[
        ref(HW, "S. 179", "dem Sie sich für eine Variante (Vorname ausschreiben oder abkürzen)")
    ],
)
def firstname_consistent(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Report the names that use the less frequent style."""
    styled = [
        (style, entry, field, name)
        for entry in _entries(ctx)
        for field in _PERSON_FIELDS
        for name in entry.names(field)
        if (style := name_style(name)) is not None
    ]
    counts = {style: sum(item[0] == style for item in styled) for style in ("full", "abbreviated")}
    if not all(counts.values()):
        return
    # On a tie, the abbreviated names are the minority.
    minority = "full" if counts["full"] < counts["abbreviated"] else "abbreviated"
    majority = "abbreviated" if minority == "full" else "full"
    yield from (
        Finding(
            " ".join(
                (
                    f"entry {entry.key!r}: the given name of {name!r} is {style},",
                    f"but most names are {majority}. Use one style for all names.",
                )
            ),
            entry.location(field),
        )
        for style, entry, field, name in styled
        if style == minority
    )
