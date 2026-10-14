from typing import TYPE_CHECKING

from tests.helpers import make_context, messages, run_rule
from thesis_lint.context import Profile
from thesis_lint.engine import run
from thesis_lint.model import Needs, Severity

if TYPE_CHECKING:
    from pathlib import Path

    from thesis_lint.context import Context

GOOD_ARTICLE = """@article{good,
  author = {Brink, Alfred},
  title = {Titel},
  journal = {Journal},
  year = {2013},
  volume = {5},
  pages = {1--10},
}
"""


def bib_context(tmp_path: Path, bib: str, body: str = "@good\n", lint_toml: str = "") -> Context:
    return make_context(tmp_path, body, files={"main.bib": bib}, lint_toml=lint_toml)


def test_urldate_reports_missing_date(tmp_path: Path) -> None:
    bib = "@misc{web, title = {T}, year = {2020}, url = {https://x.org}}\n"
    ctx = bib_context(tmp_path, bib, "@web\n")
    assert len(run_rule(ctx, "core.bib.urldate")) == 1


def test_required_fields_reports_missing_volume(tmp_path: Path) -> None:
    bib = GOOD_ARTICLE.replace("  volume = {5},\n", "")
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.required-fields")
    assert messages(findings) == ["@article entry 'good' has no field volume. Add it."]


def test_required_fields_accepts_alternatives(tmp_path: Path) -> None:
    bib = GOOD_ARTICLE.replace("journal =", "journaltitle =").replace("year =", "date =")
    assert run_rule(bib_context(tmp_path, bib), "core.bib.required-fields") == []


def test_required_fields_ignores_unknown_types(tmp_path: Path) -> None:
    bib = "@manual{good, title = {T}}\n"
    assert run_rule(bib_context(tmp_path, bib), "core.bib.required-fields") == []


def test_cited_reports_unknown_uncited_and_full(tmp_path: Path) -> None:
    bib = GOOD_ARTICLE + "@misc{unused, title = {U}, year = {2020}}\n"
    main = '#include "body.typ"\n#bibliography("main.bib", full: true)\n'
    ctx = make_context(tmp_path, "@good @missing\n", files={"main.bib": bib, "main.typ": main})
    found = messages(run_rule(ctx, "core.bib.cited"))
    assert len(found) == 3
    assert any("'missing'" in message for message in found)
    assert any("full: true" in message for message in found)
    assert any("'unused'" in message for message in found)


def test_cited_unknown_key_stays_error_in_draft(tmp_path: Path) -> None:
    bib = GOOD_ARTICLE + "@misc{unused, title = {U}, year = {2020}}\n"
    lint = '[rules."core.bib.cited"]\n'
    ctx = bib_context(tmp_path, bib, "@good @missing\n", lint_toml=lint)
    assert ctx.profile is Profile.DRAFT
    result = run(ctx, [Needs.SOURCE])
    cited = sorted(
        (d.severity, "'missing'" in d.message)
        for d in result.diagnostics
        if d.rule_id == "core.bib.cited"
    )
    assert cited == [(Severity.ERROR, True), (Severity.WARNING, False)]


def test_cited_accepts_labels(tmp_path: Path) -> None:
    ctx = bib_context(tmp_path, GOOD_ARTICLE, "= Kapitel <sec-a>\n\nSiehe @sec-a und @good.\n")
    assert run_rule(ctx, "core.bib.cited") == []


def test_author_present(tmp_path: Path) -> None:
    bib = GOOD_ARTICLE + "@misc{anon, title = {T}, year = {2020}}\n"
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.author-present")
    assert len(findings) == 1
    assert "'anon'" in findings[0].message


def test_academic_title(tmp_path: Path) -> None:
    bib = GOOD_ARTICLE.replace("Brink, Alfred", "Prof. Dr. Brink, Alfred and Lange, M.Sc. Ulrike")
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.academic-title")
    assert len(findings) == 2


def test_academic_title_accepts_plain_names(tmp_path: Path) -> None:
    bib = GOOD_ARTICLE.replace("Brink, Alfred", "Drews, Andreas")
    assert run_rule(bib_context(tmp_path, bib), "core.bib.academic-title") == []


def test_edition_one(tmp_path: Path) -> None:
    bib = GOOD_ARTICLE.replace("year =", "edition = {1},\n  year =")
    assert len(run_rule(bib_context(tmp_path, bib), "core.bib.edition-one")) == 1


def test_edition_one_accepts_later_editions(tmp_path: Path) -> None:
    bib = GOOD_ARTICLE.replace("year =", "edition = {10},\n  year =")
    assert run_rule(bib_context(tmp_path, bib), "core.bib.edition-one") == []


def test_not_citable(tmp_path: Path) -> None:
    bib = GOOD_ARTICLE + "@misc{wiki, url = {https://de.wikipedia.org/wiki/X}}\n"
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.not-citable")
    assert len(findings) == 1
    assert "wikipedia.org" in findings[0].message


def test_not_citable_accepts_other_urls(tmp_path: Path) -> None:
    bib = GOOD_ARTICLE + "@misc{web, url = {https://example.org}}\n"
    assert run_rule(bib_context(tmp_path, bib), "core.bib.not-citable") == []


def test_duplicate_title_and_doi(tmp_path: Path) -> None:
    bib = (
        "@misc{a, title = {Ein Titel}, doi = {10.1/x}}\n"
        "@misc{b, title = {ein {T}itel!}}\n"
        "@misc{c, title = {Anders}, doi = {https://doi.org/10.1/X}}\n"
    )
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.duplicate")
    assert sorted(messages(findings)) == [
        "entry 'b' has the same title as 'a'. Merge the entries.",
        "entry 'c' has the same DOI as 'a'. Merge the entries.",
    ]


def test_duplicate_accepts_distinct_entries(tmp_path: Path) -> None:
    bib = "@misc{a, title = {Eins}}\n@misc{b, title = {Zwei}}\n"
    assert run_rule(bib_context(tmp_path, bib), "core.bib.duplicate") == []


def test_doi_and_url(tmp_path: Path) -> None:
    bib = "@misc{a, doi = {10.1/x}, url = {https://x.org}}\n@misc{b, doi = {10.1/y}}\n"
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.doi-and-url")
    assert len(findings) == 1
    assert "'a'" in findings[0].message


def test_questionable(tmp_path: Path) -> None:
    bib = (
        "@unpublished{u, title = {Entwurf}}\n"
        "@thesis{t, title = {T}, type = {Bachelorarbeit}}\n"
        "@misc{s, title = {Vorlesungsskript Mathematik}}\n"
        "@thesis{d, title = {T}, type = {Dissertation}}\n"
    )
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.questionable")
    assert sorted(f.message.split("'")[1] for f in findings) == ["s", "t", "u"]
    severities = {f.message.split("'")[1]: f.severity for f in findings}
    assert severities == {"u": Severity.WARNING, "t": None, "s": None}


def test_firstname_consistent(tmp_path: Path) -> None:
    bib = (
        "@misc{a, author = {Brink, Alfred and Lange, Ulrike}}\n"
        "@misc{b, author = {A. Weber and {Deutsche Forschungsgemeinschaft}}}\n"
    )
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.firstname-consistent")
    assert len(findings) == 1
    assert "A. Weber" in findings[0].message


def test_firstname_consistent_accepts_one_style(tmp_path: Path) -> None:
    bib = "@misc{a, author = {Brink, A. and U. Lange and Hans-Peter Weber}}\n"
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.firstname-consistent")
    assert len(findings) == 1
    bib = "@misc{a, author = {Brink, A. and U. Lange and Weber, H.-P.}}\n"
    assert run_rule(bib_context(tmp_path, bib), "core.bib.firstname-consistent") == []


def test_not_citable_reports_newspapers(tmp_path: Path) -> None:
    bib = (
        "@online{a, title = {A}, url = {https://www.spiegel.de/x}}\n"
        "@online{b, title = {B}, url = {https://www.umwelt.de/x}}\n"
        "@online{c, title = {C}, url = {https://de.wikipedia.org/wiki/X}}\n"
    )
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.not-citable")
    assert sorted(f.message.split("'")[1] for f in findings) == ["a", "c"]


# core.bib.ai-source


def test_ai_source(tmp_path: Path) -> None:
    bib = (
        "@online{a, author = {{OpenAI}}, title = {ChatGPT}}\n"
        "@online{b, author = {Shannon, Claude}, title = {A Theory}}\n"
        "@misc{c, title = {Antwort von Claude auf eine Frage}}\n"
        "@misc{d, title = {Mistralwinde}}\n"
    )
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.ai-source")
    assert [f.message.split("'")[1] for f in findings] == ["a", "c"]


# core.bib.preprint


def test_preprint(tmp_path: Path) -> None:
    bib = (
        "@misc{a, title = {A}, eprinttype = {arXiv}, eprint = {2312.10997}}\n"
        "@misc{b, title = {B}, url = {https://www.medrxiv.org/content/1}}\n"
        "@article{c, title = {C}, doi = {10.1000/x}, journal = {Nature}}\n"
    )
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.preprint")
    assert [f.message.split("'")[1] for f in findings] == ["a", "b"]


# core.bib.english


def test_english_reports_only_german_entries(tmp_path: Path) -> None:
    bib = (
        "@book{a, title = {Anfertigung wissenschaftlicher Arbeiten}}\n"
        "@book{b, title = {Die Kunst der Zitation}}\n"
        "@book{c, title = {Something for Everyone}, langid = {ngerman}}\n"
    )
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.english")
    assert messages(findings) == [
        "the bibliography has no English source. Include the English literature."
    ]


def test_english_accepts_english_entry(tmp_path: Path) -> None:
    for extra in (
        "@book{e, title = {Benchmarking Retrieval for Medicine}}\n",
        "@book{e, title = {Zitieren}, langid = {english}}\n",
    ):
        bib = "@book{a, title = {Die Kunst der Zitation}}\n" + extra
        assert run_rule(bib_context(tmp_path, bib), "core.bib.english") == []


# core.bib.online-durable


def test_online_durable(tmp_path: Path) -> None:
    bib = (
        "@online{a, title = {A}, url = {https://x.org}}\n"
        "@misc{b, title = {B}, url = {https://x.org}}\n"
        "@misc{c, title = {C}, url = {https://x.org}, doi = {10.1/x}}\n"
        "@online{d, title = {D}, url = {https://x.org},"
        " note = {Archiv: https://web.archive.org/web/2026/https://x.org}}\n"
        "@article{e, title = {E}}\n"
        "@online{f, title = {F}, url = {https://eur-lex.europa.eu/eli/reg/2024/1689}}\n"
        "@online{g, title = {G}, url = {https://www.iso.org/standard/1.html}}\n"
        "@online{h, title = {H}, url = {https://notiso.org/x}}\n"
    )
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.online-durable")
    assert [f.message.split("'")[1] for f in findings] == ["a", "b", "h"]


# core.bib.identifier


def test_identifier(tmp_path: Path) -> None:
    bib = (
        GOOD_ARTICLE
        + "@book{b, title = {B}}\n@book{c, title = {C}, isbn = {978-3-658-02511-3}}\n"
        + "@inproceedings{d, title = {D}, doi = {10.1/d}}\n@misc{e, title = {E}}\n"
    )
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.identifier")
    assert messages(findings) == [
        "@article entry 'good' has no doi. Add it.",
        "@book entry 'b' has no isbn. Add it.",
    ]


# core.bib.grey-type


def test_grey_type(tmp_path: Path) -> None:
    bib = (
        "@misc{a, title = {A}}\n@report{b, title = {B}, type = {Whitepaper}}\n"
        "@online{c, title = {C}, howpublished = {Website}}\n@book{d, title = {D}}\n"
    )
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.grey-type")
    assert messages(findings) == [
        "@misc entry 'a' does not tell the kind of the source. Add type or howpublished."
    ]


# core.bib.book-pages


def test_book_pages(tmp_path: Path) -> None:
    bib = (
        "@book{a, title = {A}, pages = {1--300}}\n@book{b, title = {B}, pagetotal = {300}}\n"
        + GOOD_ARTICLE
    )
    findings = run_rule(bib_context(tmp_path, bib), "core.bib.book-pages")
    assert [f.message.split("'")[1] for f in findings] == ["a"]
