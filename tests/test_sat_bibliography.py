from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import make_context, messages, run_rule

if TYPE_CHECKING:
    from pathlib import Path


def bib(*entries: tuple[str, str, str]) -> str:
    return "".join(
        f"@{kind}{{{key},\n  title = {{T}},\n{extra}}}\n\n" for kind, key, extra in entries
    )


ENTRIES = (
    *(("article", f"a{i}", "") for i in range(5)),
    ("online", "web1", ""),
    ("online", "web2", ""),
    ("thesis", "phd1", "  type = {phdthesis},\n"),
)
CITES = "= Einleitung\n\n" + " ".join(f"Satz @{key}." for _, key, _ in ENTRIES) + "\n"


def test_bib_count_accepts_eight_cited_entries(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, CITES, files={"main.bib": bib(*ENTRIES)})
    assert run_rule(ctx, "sat.bib-count") == []


def test_bib_count_counts_only_cited_entries(tmp_path: Path) -> None:
    text = "= Einleitung\n\nSatz @a0. Satz @web1.\n"
    ctx = make_context(tmp_path, text, files={"main.bib": bib(*ENTRIES)})
    found = messages(run_rule(ctx, "sat.bib-count"))
    assert len(found) == 2
    assert "has 2 entries" in found[0]
    assert "has 1 original works" in found[1]


def test_bib_count_counts_all_entries_with_full(tmp_path: Path) -> None:
    text = '#bibliography("main.bib", full: true)\n'
    ctx = make_context(tmp_path, text, files={"main.bib": bib(*ENTRIES)})
    assert run_rule(ctx, "sat.bib-count") == []


def test_bib_count_needs_a_phd_thesis(tmp_path: Path) -> None:
    entries = (*ENTRIES[1:7], ("thesis", "ma", "  type = {Masterarbeit},\n"), ("misc", "m", ""))
    text = '#bibliography("main.bib", full: true)\n'
    ctx = make_context(tmp_path, text, files={"main.bib": bib(*entries)})
    found = messages(run_rule(ctx, "sat.bib-count"))
    assert len(found) == 1
    assert "has 4 original works" in found[0]


def test_citation_style_accepts_the_apa_file(tmp_path: Path) -> None:
    text = '#bibliography("main.bib", style: "apa-6th-edition.csl")\n'
    assert run_rule(make_context(tmp_path, text), "sat.citation-style") == []


def test_citation_style_reports_another_style(tmp_path: Path) -> None:
    text = '#bibliography("main.bib", style: "ieee")\n'
    found = messages(run_rule(make_context(tmp_path, text), "sat.citation-style"))
    assert found == ["the bibliography style is 'ieee'. Use style: 'apa-6th-edition.csl'"]


def test_citation_style_reports_a_missing_bibliography(tmp_path: Path) -> None:
    found = messages(run_rule(make_context(tmp_path, "Text.\n"), "sat.citation-style"))
    assert len(found) == 1
    assert "no bibliography" in found[0]
