"""SAT rules for the submission: file name, PDF rights, source PDFs and date."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import pypdf

from thesis_lint.context import Milestone
from thesis_lint.core.sources import SAT, VORLAGE, ref
from thesis_lint.model import Location, Needs, Severity
from thesis_lint.packs.sat_meti.support import listed_keys, main_location, setting_location
from thesis_lint.registry import Finding, NoParams, rule
from thesis_lint.typst.values import Unknown

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from thesis_lint.context import Context


@dataclass(frozen=True, slots=True)
class FilenameParams:
    """Parameters of `sat.filename`."""

    ew_prefix: str = "SAT2_EW_"
    fa_prefix: str = "SAT3_FA_"
    sa32_prefix: str = "SAT3_SA32_"
    output_dir: str = "build"
    author_setting: str = "author"


def expected_filename(ctx: Context, params: FilenameParams) -> str | None:
    """Return the file name for the milestone, or None without milestone or author.

    The name is `<prefix><Nachname>-<Vorname>.pdf`. The last word of the author
    is the family name. More given names are joined with hyphens.
    """
    if ctx.milestone is None:
        return None
    author = ctx.project.setting_text(params.author_setting) or ""
    names = author.split()
    if len(names) < 2:
        return None
    prefix = {
        Milestone.EW: params.ew_prefix,
        Milestone.FA: params.fa_prefix,
        Milestone.SA32: params.sa32_prefix,
    }[ctx.milestone]
    return f"{prefix}{names[-1]}-{'-'.join(names[:-1])}.pdf"


@rule(
    "sat.filename",
    summary="The PDF has the file name of the milestone, e.g. SAT3_FA_Nachname-Vorname.pdf.",
    severity=Severity.ERROR,
    sources=[
        ref(SAT, "S. 9", "Dateiname: SAT2_EW_[Nachname-Vorname].pdf"),
        ref(SAT, "S. 11", "Dateiname: SAT3_FA_[Nachname-Vorname].pdf"),
        ref(SAT, "S. 13", "Dateiname: SAT3_SA32_[Nachname-Vorname].pdf"),
    ],
    params=FilenameParams(),
    submission=True,
)
def filename(ctx: Context, params: FilenameParams) -> Iterator[Finding]:
    """Check that the output directory holds the PDF with the expected name.

    The rule runs only with a milestone.
    """
    if ctx.milestone is None:
        return
    name = expected_filename(ctx, params)
    location = setting_location(ctx, params.author_setting)
    if name is None:
        yield Finding(
            " ".join(
                (
                    f'the setting {params.author_setting} must be "Vorname Nachname".',
                    "The rule needs it for the file name",
                )
            ),
            location,
        )
        return
    target = ctx.root / params.output_dir / name
    if not target.is_file():
        yield Finding(
            " ".join(
                (
                    f"the submission file {params.output_dir}/{name} does not exist. Compile the",
                    f"document to this file: typst compile main.typ {params.output_dir}/{name}",
                )
            ),
            location,
        )


@rule(
    "sat.pdf-commentable",
    summary="The PDF is not encrypted and allows comments.",
    severity=Severity.ERROR,
    sources=[
        ref(
            SAT,
            "S. 17",
            "in einem Format abgegeben werden, welches sich kommentieren lässt",
        )
    ],
    needs=Needs.PDF,
    submission=True,
)
def pdf_commentable(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Check the compiled PDF and, with a milestone, the submission file.

    The name of the submission file comes from the parameters of `sat.filename`.
    """
    configured = ctx.config.rules.get("sat.filename")
    params = (
        configured.params
        if configured is not None and isinstance(configured.params, FilenameParams)
        else FilenameParams()
    )
    pdf = ctx.pdf
    yield from _rights(pdf.path, encrypted=pdf.encrypted, comments=pdf.annotations_allowed, ctx=ctx)
    name = expected_filename(ctx, params)
    if name is None:
        return
    target = ctx.root / params.output_dir / name
    if target.is_file():
        encrypted, comments = _read_rights(target)
        yield from _rights(target, encrypted=encrypted, comments=comments, ctx=ctx)


def _read_rights(path: Path) -> tuple[bool, bool]:
    reader = pypdf.PdfReader(str(path))
    if not reader.is_encrypted:
        return False, True
    permissions = reader.user_access_permissions
    allowed = permissions is not None and bool(
        permissions & pypdf.constants.UserAccessPermissions.ADD_OR_MODIFY
    )
    return True, allowed


def _rights(path: Path, *, encrypted: bool, comments: bool, ctx: Context) -> Iterator[Finding]:
    if encrypted:
        yield Finding(
            f"the PDF {path.name} is encrypted. Submit a PDF without encryption",
            main_location(ctx),
        )
    if not comments:
        yield Finding(
            f"the PDF {path.name} does not allow comments. Remove the restriction",
            main_location(ctx),
        )


@rule(
    "sat.sources-present",
    summary="The folder sources has one PDF for each entry in the bibliography and no other PDFs.",
    severity=Severity.ERROR,
    sources=[
        ref(
            SAT,
            "S. 12",
            "aufgeführten Quellen müssen […] als pdf-Dokument abgegeben werden",
        )
    ],
    needs=Needs.SOURCES_DIR,
    submission=True,
)
def sources_present(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    """Compare the cited keys with the files `sources/<key>.pdf`."""
    directory = ctx.root / ctx.config.paths.sources_dir
    keys = listed_keys(ctx)
    if not directory.is_dir():
        if keys:
            yield Finding(
                " ".join(
                    (
                        f"the folder {ctx.config.paths.sources_dir}/ does not exist. Add one PDF",
                        "for each source, with the name <key>.pdf",
                    )
                ),
                main_location(ctx),
            )
        return
    present = {path.stem: path for path in directory.iterdir() if path.suffix.lower() == ".pdf"}
    entries = ctx.project.bibliography.entries
    yield from (
        Finding(
            " ".join(
                (
                    f"the source PDF {ctx.config.paths.sources_dir}/{key}.pdf is missing.",
                    "Add the PDF or a screenshot of the title page as PDF",
                )
            ),
            entries[key].location(),
        )
        for key in sorted(keys - present.keys())
    )
    yield from (
        Finding(
            " ".join(
                (
                    f"the PDF {path.name} is not an entry of the bibliography. Remove or rename it",
                    "to the key of the entry",
                )
            ),
            Location(path),
        )
        for key, path in sorted(present.items())
        if key not in keys
    )


@dataclass(frozen=True, slots=True)
class TitlepageDateParams:
    """Parameters of `sat.titlepage-date`."""

    setting: str = "submitted-on"
    pattern: str = r"\d{2}\.\d{2}\.\d{4}"
    date_format: str = "%d.%m.%Y"


@rule(
    "sat.titlepage-date",
    summary="The submission date on the title page has the format DD.MM.YYYY.",
    severity=Severity.ERROR,
    sources=[ref(VORLAGE, "Titelseite", "vorgelegt am: 12.12.20xx")],
    params=TitlepageDateParams(),
    submission=True,
)
def titlepage_date(ctx: Context, params: TitlepageDateParams) -> Iterator[Finding]:
    """Check the setting `submitted-on`. A `datetime(...)` value is correct."""
    valued = ctx.project.settings.get(params.setting)
    location = setting_location(ctx, params.setting)
    value = None if valued is None else valued.value
    if isinstance(value, Unknown) and value.source.node_text(value.node).startswith("datetime("):
        return
    text = ctx.project.setting_text(params.setting)
    if text is None:
        yield Finding(
            f"the setting {params.setting} is missing. Set the submission date as DD.MM.YYYY",
            location,
        )
        return
    text = text.strip()
    if re.fullmatch(params.pattern, text) is None or not _valid_date(text, params.date_format):
        yield Finding(
            " ".join(
                (
                    f"the submission date {text!r} is not a date in the format DD.MM.YYYY.",
                    "Set the date, for example 15.01.2027",
                )
            ),
            location,
        )


def _valid_date(text: str, date_format: str) -> bool:
    try:
        datetime.strptime(text, date_format)  # noqa: DTZ007 - a calendar date has no time zone
    except ValueError:
        return False
    return True
