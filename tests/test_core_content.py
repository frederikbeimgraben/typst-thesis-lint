from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import make_context, messages, run_rule

if TYPE_CHECKING:
    from pathlib import Path

    from thesis_lint.context import Context

GLOSSARY = """
#let terms = (
  "Halluzination": (name: "Halluzination", description: [Falsche Ausgabe.]),
)

#let acronyms = (
  "IFU": "Gebrauchsanweisung",
  "KI": "Künstliche Intelligenz",
)
"""

GOOD_ABSTRACT = (
    "Die Hypothese lautet: Ein Agent ergänzt die Gebrauchsanweisung. "
    'Die Arbeit wertet Studien zur #gls("Halluzination") aus. '
    "Die Ergebnisse zeigen, dass der Agent die Gebrauchsanweisung nicht ersetzen kann."
)


def abstract_context(tmp_path: Path, abstract: str, body: str = "") -> Context:
    meta = f"#let settings = (abstract: [{abstract}])\n"
    return make_context(tmp_path, body, files={"metadata.typ": meta, "glossary.typ": GLOSSARY})


def count(tmp_path: Path, rule_id: str, body: str) -> int:
    return len(run_rule(make_context(tmp_path, body), rule_id))


# core.abstract.no-abbreviations


def test_abstract_abbreviations_reports_acronym_and_raw_token(tmp_path: Path) -> None:
    ctx = abstract_context(tmp_path, 'Ein #gls("KI")-Agent ersetzt die IFU nicht.')
    found = messages(run_rule(ctx, "core.abstract.no-abbreviations"))
    assert len(found) == 2
    assert "Künstliche Intelligenz" in found[0]
    assert "'IFU'" in found[1]


def test_abstract_abbreviations_accepts_terms_and_allowed_tokens(tmp_path: Path) -> None:
    ctx = abstract_context(tmp_path, 'Eine #gls("Halluzination") nach ISO 14971 ist ein Risiko.')
    assert run_rule(ctx, "core.abstract.no-abbreviations") == []


def test_abstract_abbreviations_ignores_a_missing_abstract(tmp_path: Path) -> None:
    assert count(tmp_path, "core.abstract.no-abbreviations", "= Einleitung\n\nKI.\n") == 0


# core.abstract.no-outline


def test_abstract_outline_reports_chapter_and_sequence(tmp_path: Path) -> None:
    abstract = (
        "Kapitel 2 beschreibt die Methoden. Zuerst wurde das Thema gesucht. "
        "Dann wurden die Daten bearbeitet."
    )
    ctx = abstract_context(tmp_path, abstract)
    assert len(run_rule(ctx, "core.abstract.no-outline")) == 2


def test_abstract_outline_reports_gliedert_sich(tmp_path: Path) -> None:
    ctx = abstract_context(tmp_path, "Die Arbeit gliedert sich in fünf Teile.")
    assert len(run_rule(ctx, "core.abstract.no-outline")) == 1


def test_abstract_outline_accepts_content_statements(tmp_path: Path) -> None:
    ctx = abstract_context(tmp_path, GOOD_ABSTRACT + " Danach folgt keine Liste.")
    assert run_rule(ctx, "core.abstract.no-outline") == []


# core.abstract.elements


def test_abstract_elements_reports_each_missing_element(tmp_path: Path) -> None:
    ctx = abstract_context(tmp_path, "Agenten sind ein wichtiges Thema der Medizintechnik.")
    found = messages(run_rule(ctx, "core.abstract.elements"))
    assert [m.split(".")[0] for m in found] == [
        "the abstract does not name the hypothesis",
        "the abstract does not name the method",
        "the abstract does not name the result",
    ]


def test_abstract_elements_accepts_all_elements(tmp_path: Path) -> None:
    ctx = abstract_context(tmp_path, GOOD_ABSTRACT)
    assert run_rule(ctx, "core.abstract.elements") == []


# core.abstract.conclusion-overlap

CONCLUSION = (
    '= Zusammenfassung\n\nDer Agent ergänzt die #gls("IFU"). Validierung mit '
    "unbeantwortbaren Fragen senkt Risiken. Harmonisierte Normen fehlen noch.\n"
)


def test_conclusion_overlap_reports_unrelated_abstract(tmp_path: Path) -> None:
    ctx = abstract_context(tmp_path, "Agenten sind ein wichtiges Thema.", CONCLUSION)
    found = messages(run_rule(ctx, "core.abstract.conclusion-overlap"))
    assert len(found) == 1
    assert "0% of the content words" in found[0]


def test_conclusion_overlap_accepts_shared_statements(tmp_path: Path) -> None:
    abstract = (
        "Ein Agent ergänzt die Gebrauchsanweisung. Eine Validierung mit unbeantwortbaren "
        "Fragen senkt die Risiken. Harmonisierte Normen fehlen."
    )
    ctx = abstract_context(tmp_path, abstract, CONCLUSION)
    assert run_rule(ctx, "core.abstract.conclusion-overlap") == []


# core.hypothesis.statement


def hypothesis(text: str) -> str:
    return f"= Anhang\n\n== Arbeitshypothese\n\n{text}\n"


def test_hypothesis_statement_reports_question(tmp_path: Path) -> None:
    body = hypothesis("Kann ein Agent die Gebrauchsanweisung ersetzen?")
    found = messages(run_rule(make_context(tmp_path, body), "core.hypothesis.statement"))
    assert len(found) == 2
    assert "question mark" in found[0]
    assert "period" in found[1]


def test_hypothesis_statement_accepts_statement(tmp_path: Path) -> None:
    body = hypothesis("Ein Agent kann die Gebrauchsanweisung nicht ersetzen.")
    assert count(tmp_path, "core.hypothesis.statement", body) == 0


def test_hypothesis_statement_ignores_placeholder(tmp_path: Path) -> None:
    body = hypothesis("\\[Hier die Arbeitshypothese eintragen\\]")
    assert count(tmp_path, "core.hypothesis.statement", body) == 0


# core.hypothesis.verdict


def test_hypothesis_verdict_reports_missing_verdict(tmp_path: Path) -> None:
    body = "= Diskussion\n\nDie Hypothese ist interessant.\n\n= Zusammenfassung\n\nEnde.\n"
    assert count(tmp_path, "core.hypothesis.verdict", body) == 1


def test_hypothesis_verdict_accepts_confirmation(tmp_path: Path) -> None:
    body = "= Diskussion\n\nText.\n\n= Zusammenfassung\n\nDie Ergebnisse stützen die Hypothese.\n"
    assert count(tmp_path, "core.hypothesis.verdict", body) == 0


def test_hypothesis_verdict_needs_both_words_in_one_sentence(tmp_path: Path) -> None:
    body = "= Diskussion\n\nDie Hypothese gilt. Das Ergebnis ist bestätigt.\n"
    assert count(tmp_path, "core.hypothesis.verdict", body) == 1


# core.methods.literature-search


def test_literature_search_reports_each_missing_part(tmp_path: Path) -> None:
    body = "= Methoden\n\nDie Arbeit wertet Fachliteratur aus.\n"
    found = messages(run_rule(make_context(tmp_path, body), "core.methods.literature-search"))
    assert len(found) == 4


def test_literature_search_accepts_complete_description(tmp_path: Path) -> None:
    body = (
        "= Methoden\n\nDie Suche in PubMed und IEEE Xplore nutzte die Suchbegriffe "
        "Agent und Gebrauchsanweisung. Sie umfasst die Jahre 2017 bis 2026. "
        "Die Einschlusskriterien sind Sprache und Begutachtung.\n"
    )
    assert count(tmp_path, "core.methods.literature-search", body) == 0


def test_literature_search_reports_only_missing_criteria(tmp_path: Path) -> None:
    body = "= Methoden\n\nSuche in EDDI mit dem Suchstring Agent im Zeitraum ab 2020.\n"
    found = messages(run_rule(make_context(tmp_path, body), "core.methods.literature-search"))
    assert len(found) == 1
    assert "selection criteria" in found[0]


# core.results.has-figure

TABLE = "#figure(table(columns: 2, [a], [b]), caption: [Werte]) <tab:a>\n"


def test_results_has_figure_reports_text_only(tmp_path: Path) -> None:
    body = "= Ergebnisse\n\nNur Text.\n\n= Diskussion\n\n" + TABLE
    assert count(tmp_path, "core.results.has-figure", body) == 1


def test_results_has_figure_accepts_table(tmp_path: Path) -> None:
    body = "= Ergebnisse\n\n== Teil\n\nText.\n\n" + TABLE
    assert count(tmp_path, "core.results.has-figure", body) == 0


# core.results.not-in-discussion


def test_not_in_discussion_reports_figures(tmp_path: Path) -> None:
    body = "= Diskussion\n\n" + TABLE + "\n= Zusammenfassung\n\n#table(columns: 1, [x])\n"
    assert count(tmp_path, "core.results.not-in-discussion", body) == 2


def test_not_in_discussion_accepts_figures_in_results(tmp_path: Path) -> None:
    body = "= Ergebnisse\n\n" + TABLE + "\n= Diskussion\n\nText.\n"
    assert count(tmp_path, "core.results.not-in-discussion", body) == 0
