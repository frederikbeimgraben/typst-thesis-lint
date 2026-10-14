from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from tests.helpers import make_context, messages, run_rule
from tests.test_sat_pdf import example_pdf, use_pdf
from thesis_lint.context import Milestone

if TYPE_CHECKING:
    from pathlib import Path

AUTHOR = {"metadata.typ": '#let settings = (author: "Hans Maria Muster")\n'}
EXPECTED = "SAT3_FA_Muster-Hans-Maria.pdf"


def test_filename_does_nothing_without_milestone(tmp_path: Path) -> None:
    assert run_rule(make_context(tmp_path, files=AUTHOR), "sat.filename") == []


def test_filename_accepts_the_expected_file(tmp_path: Path) -> None:
    files = AUTHOR | {f"build/{EXPECTED}": "%PDF"}
    ctx = make_context(tmp_path, files=files, milestone=Milestone.FA)
    assert run_rule(ctx, "sat.filename") == []


def test_filename_reports_the_expected_name(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, files=AUTHOR, milestone=Milestone.FA)
    found = messages(run_rule(ctx, "sat.filename"))
    assert len(found) == 1
    assert f"build/{EXPECTED} does not exist" in found[0]


def test_pdf_commentable_accepts_the_typst_pdf(tmp_path: Path) -> None:
    ctx = use_pdf(make_context(tmp_path), example_pdf())
    assert run_rule(ctx, "sat.pdf-commentable") == []


def test_pdf_commentable_reports_encryption(tmp_path: Path) -> None:
    pdf = dataclasses.replace(example_pdf(), encrypted=True, annotations_allowed=False)
    found = messages(run_rule(use_pdf(make_context(tmp_path), pdf), "sat.pdf-commentable"))
    assert len(found) == 2
    assert "is encrypted" in found[0]
    assert "does not allow comments" in found[1]


BIB = "@book{a, title = {A}}\n\n@book{b, title = {B}}\n"
CITE = "Text @a und @b.\n"


def test_sources_present_accepts_one_pdf_per_entry(tmp_path: Path) -> None:
    files = {"main.bib": BIB, "sources/a.pdf": "%PDF", "sources/b.pdf": "%PDF"}
    assert run_rule(make_context(tmp_path, CITE, files=files), "sat.sources-present") == []


def test_sources_present_reports_missing_and_extra_pdfs(tmp_path: Path) -> None:
    files = {"main.bib": BIB, "sources/a.pdf": "%PDF", "sources/c.pdf": "%PDF"}
    found = messages(run_rule(make_context(tmp_path, CITE, files=files), "sat.sources-present"))
    assert len(found) == 2
    assert "sources/b.pdf is missing" in found[0]
    assert "c.pdf is not an entry" in found[1]


def date(value: str) -> dict[str, str]:
    return {"metadata.typ": f"#let settings = (submitted-on: {value})\n"}


def test_titlepage_date_accepts_a_date(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, files=date('"15.01.2027"'))
    assert run_rule(ctx, "sat.titlepage-date") == []
    ctx = make_context(tmp_path, files=date("datetime(year: 2027, month: 1, day: 15)"))
    assert run_rule(ctx, "sat.titlepage-date") == []


def test_titlepage_date_reports_todo_and_bad_dates(tmp_path: Path) -> None:
    for value in ('"TODO"', '"2027-01-15"', '"31.02.2027"'):
        ctx = make_context(tmp_path, files=date(value))
        assert len(run_rule(ctx, "sat.titlepage-date")) == 1, value
