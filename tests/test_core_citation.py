from typing import TYPE_CHECKING

from tests.helpers import make_context, messages, run_rule
from thesis_lint.core.citation import author_key, ellipsis_problems
from thesis_lint.model import Severity

if TYPE_CHECKING:
    from pathlib import Path

    from thesis_lint.context import Context
    from thesis_lint.registry import Finding

BIB = "@misc{a, title = {A}}\n@misc{b, title = {B}}\n@misc{c, title = {C}}\n"
BIB_MANY = BIB + "@misc{d, title = {D}}\n@misc{e, title = {E}}\n"


def ctx_for(tmp_path: Path, body: str, files: dict[str, str] | None = None) -> Context:
    return make_context(tmp_path, body, files={"main.bib": BIB_MANY} | (files or {}))


def check(tmp_path: Path, rule_id: str, body: str, **params: object) -> list[Finding]:
    return run_rule(ctx_for(tmp_path, body), rule_id, **params)


# core.cite.quote-needs-key


def test_quote_needs_key_reports_quote_without_citation(tmp_path: Path) -> None:
    findings = check(tmp_path, "core.cite.quote-needs-key", 'Das ist "sogenannt" gut.\n')
    assert len(findings) == 1


def test_quote_needs_key_accepts_citation_in_sentence(tmp_path: Path) -> None:
    body = (
        'Er sagt "Das ist so. Und so" @a[S. 3].\n\n'
        'Sie sagt "X"#footnote[Vgl. @b[S. 2].].\n\n'
        "Ein 'einfaches' Wort.\n\n"
        "#quote(block: true, attribution: [@c[S. 4]])[Ein langes Zitat.]\n"
    )
    assert check(tmp_path, "core.cite.quote-needs-key", body) == []


def test_quote_needs_key_reports_block_quote_without_citation(tmp_path: Path) -> None:
    body = "#quote(block: true)[Ein langes Zitat.]\n"
    assert len(check(tmp_path, "core.cite.quote-needs-key", body)) == 1


# core.cite.quote-page


def test_quote_page_reports_missing_page(tmp_path: Path) -> None:
    findings = check(tmp_path, "core.cite.quote-page", 'Er sagt "So ist es" @a.\n')
    assert messages(findings) == [
        "the citation @a of a quotation gives no page. Add it, for example @a[S. 12]."
    ]


def test_quote_page_accepts_page(tmp_path: Path) -> None:
    body = 'Er sagt "So ist es" @a[S. 12]. Sie sagt "So" @b[p. 3].\n'
    assert check(tmp_path, "core.cite.quote-page", body) == []


# core.cite.ellipsis


def test_ellipsis_problems() -> None:
    assert list(ellipsis_problems("Das ist […] gut")) == []
    assert len(list(ellipsis_problems("Das ist (…) gut"))) == 1
    assert len(list(ellipsis_problems("Das ist … gut"))) == 1
    assert len(list(ellipsis_problems("[…] Das ist gut"))) == 1
    assert len(list(ellipsis_problems("Das ist gut […]"))) == 1


def test_ellipsis_rule(tmp_path: Path) -> None:
    body = 'Er sagt "Das (...) ist" @a[S. 1]. Sie sagt "Das [...] ist" @b[S. 2].\n'
    assert len(check(tmp_path, "core.cite.ellipsis", body)) == 1


# core.cite.abstract


def test_abstract_reports_citation(tmp_path: Path) -> None:
    metadata = "#let settings = (abstract: [Wir zeigen @a etwas.])\n"
    ctx = ctx_for(tmp_path, "Text.\n", files={"metadata.typ": metadata})
    assert len(run_rule(ctx, "core.cite.abstract")) == 1


def test_abstract_accepts_no_citation(tmp_path: Path) -> None:
    metadata = "#let settings = (abstract: [Wir zeigen etwas.])\n"
    ctx = ctx_for(tmp_path, "Text.\n", files={"metadata.typ": metadata})
    assert run_rule(ctx, "core.cite.abstract") == []


# core.cite.consensus


def test_consensus_needs_two_keys(tmp_path: Path) -> None:
    body = "In der Literatur ist das bekannt @a. In der Literatur ist das klar @a @b.\n"
    findings = check(tmp_path, "core.cite.consensus", body)
    assert len(findings) == 1
    assert "1 source(s)" in findings[0].message


# core.cite.statistics


def test_statistics_reports_unsourced_percentage(tmp_path: Path) -> None:
    body = "Etwa 40 % der Nutzer lesen nichts. Etwa 30 % lesen alles @a.\n"
    findings = check(tmp_path, "core.cite.statistics", body)
    assert len(findings) == 1
    assert "40 %" in findings[0].message


# core.cite.laut-subjunctive


def test_laut_subjunctive(tmp_path: Path) -> None:
    body = "Laut Brink sei das richtig @a. Laut Brink ist das richtig @a.\n"
    findings = check(tmp_path, "core.cite.laut-subjunctive", body)
    assert len(findings) == 1
    assert "'sei'" in findings[0].message


def test_laut_subjunctive_accepts_plain_subjunctive(tmp_path: Path) -> None:
    body = "Brink meint, das sei richtig @a.\n"
    assert check(tmp_path, "core.cite.laut-subjunctive", body) == []


# core.cite.ibid, core.cite.ff, core.cite.secondary


def test_ibid(tmp_path: Path) -> None:
    body = "Das gilt auch hier#footnote[Ebd., S. 3.]. Und @a[ebd.].\n"
    assert len(check(tmp_path, "core.cite.ibid", body)) == 2


def test_ibid_accepts_normal_text(tmp_path: Path) -> None:
    assert check(tmp_path, "core.cite.ibid", "Das ist eben da @a[S. 3].\n") == []


def test_ff(tmp_path: Path) -> None:
    body = "Siehe @a[S. 12ff.] und S. 3 ff. im Text. Der Stoff. ist gut.\n"
    findings = check(tmp_path, "core.cite.ff", body)
    assert len(findings) == 2
    assert all(f.severity is None for f in findings)


def test_ff_reports_f_as_warning(tmp_path: Path) -> None:
    body = "Das gilt @a[S. 12 f.] und @b[S. 3f.]. Der Fall f. ist gut @c[S. 4-5].\n"
    findings = check(tmp_path, "core.cite.ff", body)
    assert messages(findings) == ["avoid 'f.'. Give the exact page range."] * 2
    assert all(f.severity is Severity.WARNING for f in findings)


def test_secondary(tmp_path: Path) -> None:
    body = "Das ist so @a[zit. nach Ebel 2006, S. 34]. Das auch @b[S. 3].\n"
    assert len(check(tmp_path, "core.cite.secondary", body)) == 1


# core.cite.quote-share


def test_quote_share(tmp_path: Path) -> None:
    body = 'Eins zwei drei vier "fünf sechs" @a[S. 1].\n'
    assert len(check(tmp_path, "core.cite.quote-share", body)) == 1
    assert check(tmp_path, "core.cite.quote-share", body, max_share=0.5) == []


# core.cite.cluster


def test_cluster(tmp_path: Path) -> None:
    body = "Viel @a @b @c @d @e. Wenig @a; @b. Getrennt @a und @b @c @d @e.\n"
    findings = check(tmp_path, "core.cite.cluster", body)
    assert messages(findings) == [
        "5 citations in one group (maximum 4). Cite only the most important sources."
    ]


# core.cite.block-quote


def test_block_quote(tmp_path: Path) -> None:
    long_quote = " ".join(["Wort"] * 41)
    short_quote = " ".join(["Wort"] * 40)
    body = f'Er sagt "{long_quote}" @a[S. 1]. Sie sagt "{short_quote}" @b[S. 2].\n\n'
    body += f"#quote(block: true, attribution: [@c[S. 3]])[{long_quote}]\n"
    findings = check(tmp_path, "core.cite.block-quote", body)
    assert len(findings) == 1
    assert "41 words" in findings[0].message


# core.cite.reporting-unsourced


def test_reporting_unsourced(tmp_path: Path) -> None:
    body = "Müller betont die Bedeutung.\n\nMeier betont das auch @a.\n\nEin Absatz.\n"
    findings = check(tmp_path, "core.cite.reporting-unsourced", body)
    assert len(findings) == 1
    assert "'betont'" in findings[0].message


# core.cite.foreign-quote


def test_foreign_quote(tmp_path: Path) -> None:
    body = (
        'Er sagt "the model is good for the data" @a[p. 1].\n\n'
        'Sie sagt "the data is fine and good"#footnote[Übersetzung: gut @b[p. 2].].\n\n'
        'Er sagt "das Modell ist gut für die Daten" @c[S. 3].\n'
    )
    findings = check(tmp_path, "core.cite.foreign-quote", body)
    assert messages(findings) == ["the quotation is in English. Translate it or paraphrase it."] * 2


def test_foreign_quote_accepts_german_quote(tmp_path: Path) -> None:
    body = 'Er sagt "das Modell ist gut für die Daten" @c[S. 3].\n'
    assert check(tmp_path, "core.cite.foreign-quote", body) == []


# core.cite.software


def test_software(tmp_path: Path) -> None:
    body = "Wir nutzen Python. Wir nutzen Python @a. Wir nutzen Pythonic.\n"
    assert check(tmp_path, "core.cite.software", body) == []
    findings = check(tmp_path, "core.cite.software", body, terms=["Python"])
    assert len(findings) == 1


def test_software_accepts_a_reference_to_the_tool_list(tmp_path: Path) -> None:
    body = (
        "= Werkzeuge <sec:werkzeuge>\n\nDie Suche nutzte Consensus (@sec:werkzeuge).\n\n"
        + "Consensus half.\n"
    )
    ctx = make_context(tmp_path, body, lint_toml="")
    findings = run_rule(
        ctx, "core.cite.software", terms=["Consensus"], tool_labels=["sec:werkzeuge"]
    )
    assert len(findings) == 1
    assert findings[0].location.line == 5


# core.cite.page-required


def test_page_required_reports_citation_without_page(tmp_path: Path) -> None:
    body = (
        "Das gilt @a. Das auch @b[Kap. 3].\n\n"
        "Fußnote#footnote[Quelle: @c.].\n\n"
        "#figure([X], caption: [Bild @d])\n"
    )
    findings = check(tmp_path, "core.cite.page-required", body)
    assert sorted(f.message.split()[2] for f in findings) == ["@a", "@b", "@c", "@d"]


def test_page_required_accepts_pages(tmp_path: Path) -> None:
    body = (
        "Das gilt @a[S. 223]. Das auch @b[S. 223-227] und @c[S. 223–227].\n\n"
        "English @d[p. 4] and @e[pp. 4-6]. Siehe @sec:x.\n\n= X <sec:x>\n"
    )
    assert check(tmp_path, "core.cite.page-required", body) == []


# core.cite.same-author-cluster

AUTHOR_BIB = (
    "@misc{m1, author = {Maier, Hans and Roth, Eva}, title = {A}}\n"
    "@misc{m2, author = {Hans Maier}, title = {B}}\n"
    "@misc{m3, author = {Maier, Lisa}, title = {C}}\n"
    "@misc{eu1, author = {{Europäische Kommission}}, title = {D}}\n"
    "@misc{eu2, author = {{Europäische Kommission}}, title = {E}}\n"
    "@misc{r1, author = {Roth, Eva}, title = {F}}\n"
)


def test_author_key() -> None:
    assert author_key("Maier, Hans") == author_key("Hans Maier") == "maier, h"
    assert author_key("{Europäische Kommission}") == "europäische kommission"


def test_same_author_cluster_reports_same_first_author(tmp_path: Path) -> None:
    body = "Eins @m1 @m2. Zwei @eu1; @eu2.\n"
    ctx = make_context(tmp_path, body, files={"main.bib": AUTHOR_BIB})
    findings = run_rule(ctx, "core.cite.same-author-cluster")
    assert [f.message.split()[0] for f in findings] == ["@m2", "@eu2"]


def test_same_author_cluster_accepts_other_authors(tmp_path: Path) -> None:
    body = "Eins @m1 @m3 @r1. Zwei @m1 und @m2.\n"
    ctx = make_context(tmp_path, body, files={"main.bib": AUTHOR_BIB})
    assert run_rule(ctx, "core.cite.same-author-cluster") == []


# core.cite.vgl-apa


def test_vgl_apa_reports_phrase_before_citation(tmp_path: Path) -> None:
    body = "Das gilt (vgl. @a[S. 3]). Siehe @b[S. 4].\n\nText#footnote[Vgl. @c[S. 1].].\n"
    findings = check(tmp_path, "core.cite.vgl-apa", body)
    assert len(findings) == 3
    assert findings[0].message == "remove 'vgl.' before @a. APA style has no such phrase."


def test_vgl_apa_accepts_plain_citation(tmp_path: Path) -> None:
    body = "Das gilt @a[S. 3]. Siehe Abschnitt @sec:x. Vgl. dazu die Tabelle.\n\n= X <sec:x>\n"
    assert check(tmp_path, "core.cite.vgl-apa", body) == []


# core.cite.indirect-intro


def test_indirect_intro_reports_paragraph_without_introduction(tmp_path: Path) -> None:
    body = "Das Verfahren ist schnell. Es ist auch genau @m1[S. 3].\n"
    ctx = make_context(tmp_path, body, files={"main.bib": AUTHOR_BIB})
    findings = run_rule(ctx, "core.cite.indirect-intro")
    assert len(findings) == 1
    assert findings[0].location.column == 1


def test_indirect_intro_accepts_introduction_or_single_sentence(tmp_path: Path) -> None:
    body = (
        "Maier und Roth halten das Verfahren für schnell. Es ist genau @m1[S. 3].\n\n"
        "Laut einer Untersuchung ist es schnell. Es ist genau @m2[S. 3].\n\n"
        "Das Verfahren ist schnell @m3[S. 2]. Es ist genau @m3[S. 3].\n\n"
        "Das Verfahren ist schnell und genau @r1[S. 3].\n\n"
        "Das Verfahren ist schnell. Es ist genau.\n"
    )
    ctx = make_context(tmp_path, body, files={"main.bib": AUTHOR_BIB})
    assert run_rule(ctx, "core.cite.indirect-intro") == []
