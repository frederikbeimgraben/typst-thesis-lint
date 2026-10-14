from typing import TYPE_CHECKING

from tests.helpers import make_context, messages, run_rule

if TYPE_CHECKING:
    from pathlib import Path

SENTENCES = "Erster Satz hier. Zweiter Satz hier. Dritter Satz hier.\n\n"


def count(tmp_path: Path, rule_id: str, body: str, **files: str) -> int:
    ctx = make_context(tmp_path, body, files=files or None)
    return len(run_rule(ctx, rule_id))


# core.heading.min-children


def test_min_children_reports_single_subsection(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, "= Eins\n\n== Nur eins\n\nText.\n\n= Zwei\n\n== A\n\n== B\n")
    findings = run_rule(ctx, "core.heading.min-children")
    assert len(findings) == 1
    assert "Eins" in findings[0].message


def test_min_children_accepts_two_subsections(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, "= Zwei\n\n== A\n\n== B\n")
    assert run_rule(ctx, "core.heading.min-children") == []


def test_min_children_ignores_level_four_entries(tmp_path: Path) -> None:
    body = "= Anhang\n\n== Teil A\n\n== Vorschläge\n\n==== VS001-Eins\n"
    assert count(tmp_path, "core.heading.min-children", body) == 0


# core.heading.duplicate


def test_duplicate_reports_repeated_heading(tmp_path: Path) -> None:
    body = "= Eins\n\n== Grundlagen\n\n= Zwei\n\n== Grundlagen\n"
    assert count(tmp_path, "core.heading.duplicate", body) == 1


def test_duplicate_reports_thesis_title(tmp_path: Path) -> None:
    meta = "#let settings = (title: [Agenten in der Medizin])\n"
    body = "= Agenten in der Medizin\n"
    assert count(tmp_path, "core.heading.duplicate", body, **{"metadata.typ": meta}) == 1


def test_duplicate_accepts_unique_headings(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.duplicate", "= Eins\n\n= Zwei\n") == 0


# core.heading.max-siblings


def test_max_siblings_reports_seven_subsections(tmp_path: Path) -> None:
    body = "= Kapitel\n\n" + "".join(f"== Teil {c}\n\n" for c in "ABCDEFG")
    assert count(tmp_path, "core.heading.max-siblings", body) == 1


def test_max_siblings_accepts_six_subsections(tmp_path: Path) -> None:
    body = "= Kapitel\n\n" + "".join(f"== Teil {c}\n\n" for c in "ABCDEF")
    assert count(tmp_path, "core.heading.max-siblings", body) == 0


# core.heading.unnumbered


def test_unnumbered_reports_heading_without_number(tmp_path: Path) -> None:
    body = "= Methoden\n\n#heading(level: 2, numbering: none)[Ablauf]\n"
    assert count(tmp_path, "core.heading.unnumbered", body) == 1


def test_unnumbered_reports_set_rule(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.unnumbered", "#set heading(numbering: none)\n") == 1


def test_unnumbered_accepts_improvement_entries(tmp_path: Path) -> None:
    body = "= Anhang\n\n== Vorschläge\n\n#heading(level: 4, outlined: false)[VS001-Komma]\n"
    assert count(tmp_path, "core.heading.unnumbered", body) == 0


# core.heading.punctuation


def test_punctuation_reports_question_mark_and_math(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, "= Ersatz oder Ergänzung?\n\n= Formel $x$\n")
    found = messages(run_rule(ctx, "core.heading.punctuation"))
    assert len(found) == 2
    assert "$...$" in found[1]


def test_punctuation_accepts_version_number(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.punctuation", "= Änderungen in Version 2.0\n") == 0


# core.heading.capital


def test_capital_reports_lowercase_start(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.capital", "= bei konstanten Zahlungen\n") == 1


def test_capital_accepts_uppercase_start(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.capital", "= Konstante Zahlungen\n") == 0


# core.heading.quotes


def test_quotes_reports_quoted_heading(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.quotes", '= Die sogenannte "Inversion"\n') == 1


def test_quotes_accepts_plain_heading(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.quotes", "= Phaseninversion\n") == 0


# core.heading.first-person


def test_first_person_reports_ich(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.first-person", "= So bin ich vorgegangen\n") == 1


def test_first_person_accepts_neutral_heading(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.first-person", "= Vorgehen der Untersuchung\n") == 0


# core.heading.evaluative


def test_evaluative_reports_inflected_word(tmp_path: Path) -> None:
    body = "= Voraussetzungen erfolgreicher Fertigungskonzepte\n"
    assert count(tmp_path, "core.heading.evaluative", body) == 1


def test_evaluative_accepts_neutral_heading(tmp_path: Path) -> None:
    body = "= Bestimmung der Fertigungstiefe\n"
    assert count(tmp_path, "core.heading.evaluative", body) == 0


# core.heading.verb


def test_verb_reports_sentence(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.verb", "= Die Mischungen werden gemessen\n") == 1


def test_verb_accepts_nominal_style(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.verb", "= Messung der Mischungen\n") == 0


# core.heading.other-misc


def test_other_misc_reports_early_catch_all_and_digression(tmp_path: Path) -> None:
    body = "= Ziele\n\n== Kostenreduktion\n\n== Sonstige Ziele\n\n= Exkurs zur Geschichte\n"
    assert count(tmp_path, "core.heading.other-misc", body) == 2


def test_other_misc_accepts_catch_all_after_two_siblings(tmp_path: Path) -> None:
    body = "= Ziele\n\n== Kosten\n\n== Qualität\n\n== Weitere Ziele\n"
    assert count(tmp_path, "core.heading.other-misc", body) == 0


# core.heading.placeholder-first


def test_placeholder_first_reports_general_first_subsection(tmp_path: Path) -> None:
    body = "= Verfahren\n\n== Überblick\n\n== Statische Verfahren\n"
    assert count(tmp_path, "core.heading.placeholder-first", body) == 1


def test_placeholder_first_accepts_specific_subsections(tmp_path: Path) -> None:
    body = "= Verfahren\n\n== Dynamische Verfahren\n\n== Statische Verfahren\n"
    assert count(tmp_path, "core.heading.placeholder-first", body) == 0


# core.heading.article-consistent


def test_article_consistent_reports_mixed_siblings(tmp_path: Path) -> None:
    body = "= Batterie\n\n== Die Anode\n\n== Kathode\n\n== Separator\n"
    assert count(tmp_path, "core.heading.article-consistent", body) == 1


def test_article_consistent_accepts_uniform_siblings(tmp_path: Path) -> None:
    body = "= Batterie\n\n== Anode\n\n== Kathode\n"
    assert count(tmp_path, "core.heading.article-consistent", body) == 0


# core.heading.abbreviation


def test_abbreviation_reports_acronym_and_gls(tmp_path: Path) -> None:
    body = '= Blick auf die FDA\n\n= Grundlagen zu #gls("llm")\n'
    assert count(tmp_path, "core.heading.abbreviation", body) == 2


def test_abbreviation_accepts_full_terms(tmp_path: Path) -> None:
    body = "= Teil II der Verordnung\n"
    assert count(tmp_path, "core.heading.abbreviation", body) == 0


# core.heading.repeats-parent


def test_repeats_parent_reports_repeated_word(tmp_path: Path) -> None:
    body = "= Batterien\n\n== Batterien allgemein\n\n== Aufbau\n"
    assert count(tmp_path, "core.heading.repeats-parent", body) == 1


def test_repeats_parent_accepts_new_words(tmp_path: Path) -> None:
    body = "= Batterien\n\n== Aufbau\n\n== Funktion\n"
    assert count(tmp_path, "core.heading.repeats-parent", body) == 0


# core.heading.suspense


def test_suspense_reports_phrase(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.suspense", "= Zum Schluss\n") == 1


def test_suspense_accepts_plain_heading(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.suspense", "= Zusammenfassung\n") == 0


# core.heading.numbering-format


def test_numbering_format_reports_final_period(tmp_path: Path) -> None:
    assert (
        count(tmp_path, "core.heading.numbering-format", '#set heading(numbering: "1.1.")\n') == 1
    )


def test_numbering_format_accepts_pattern_without_period(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.numbering-format", '#set heading(numbering: "1.1")\n') == 0


# core.heading.citation


def test_citation_reports_reference_in_heading(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.citation", "= Modelle nach @smith\n") == 1


def test_citation_accepts_plain_heading(tmp_path: Path) -> None:
    assert count(tmp_path, "core.heading.citation", "= Modelle\n") == 0


# core.section.min-sentences


def test_min_sentences_reports_short_section(tmp_path: Path) -> None:
    body = "= Kapitel\n\nNur ein Satz.\n"
    assert count(tmp_path, "core.section.min-sentences", body) == 1


def test_min_sentences_accepts_three_sentences_and_excluded_chapters(tmp_path: Path) -> None:
    body = "= Kapitel\n\n" + SENTENCES + "= Danksagungen\n\nDanke.\n"
    assert count(tmp_path, "core.section.min-sentences", body) == 0


# core.section.preamble


def test_preamble_reports_long_preamble(tmp_path: Path) -> None:
    body = "= Kapitel\n\n" + SENTENCES + "== A\n\n== B\n"
    assert count(tmp_path, "core.section.preamble", body) == 1


def test_preamble_accepts_short_preamble(tmp_path: Path) -> None:
    body = "= Kapitel\n\nKurz zum Vorgehen. Dann folgt mehr.\n\n== A\n\n== B\n"
    assert count(tmp_path, "core.section.preamble", body) == 0


# core.section.balance


def test_balance_reports_short_chapter(tmp_path: Path) -> None:
    body = "= Methoden\n\n" + "Wort " * 100 + "\n\n= Ergebnisse\n\nWort wort.\n"
    assert count(tmp_path, "core.section.balance", body) == 1


def test_balance_accepts_similar_chapters(tmp_path: Path) -> None:
    body = "= Methoden\n\n" + "Wort " * 30 + "\n\n= Ergebnisse\n\n" + "Wort " * 20 + "\n"
    assert count(tmp_path, "core.section.balance", body) == 0


# core.intro.no-figure


def test_intro_no_figure_reports_figure_and_table(tmp_path: Path) -> None:
    body = '= Einleitung\n\n#figure(image("a.png"), caption: [Bild])\n\n#table([a])\n'
    assert count(tmp_path, "core.intro.no-figure", body) == 2


def test_intro_no_figure_accepts_figure_in_later_chapter(tmp_path: Path) -> None:
    body = '= Einleitung\n\nText.\n\n= Methoden\n\n#figure(image("a.png"), caption: [Bild])\n'
    assert count(tmp_path, "core.intro.no-figure", body) == 0


# core.conclusion.apology


def test_apology_reports_leider(tmp_path: Path) -> None:
    body = "= Zusammenfassung\n\nLeider konnte der Test nicht erfolgen.\n"
    assert count(tmp_path, "core.conclusion.apology", body) == 2


def test_apology_accepts_neutral_conclusion(tmp_path: Path) -> None:
    body = "= Zusammenfassung\n\nDie Arbeit zeigt drei Ergebnisse.\n\n= Methoden\n\nLeider.\n"
    assert count(tmp_path, "core.conclusion.apology", body) == 0


# core.appendix.referenced


def test_appendix_referenced_reports_missing_reference(tmp_path: Path) -> None:
    body = "= Methoden\n\nText.\n\n= Anhang\n\n== Projektplan <sec:plan>\n"
    assert count(tmp_path, "core.appendix.referenced", body) == 1


def test_appendix_referenced_accepts_reference(tmp_path: Path) -> None:
    body = "= Methoden\n\nSiehe @sec:plan.\n\n= Anhang\n\n== Projektplan <sec:plan>\n"
    assert count(tmp_path, "core.appendix.referenced", body) == 0


# core.list.share


def test_list_share_reports_list_section(tmp_path: Path) -> None:
    body = "= Kapitel\n\nKurz.\n\n- Erster langer Punkt der Liste\n- Zweiter langer Punkt\n"
    assert count(tmp_path, "core.list.share", body) == 1


def test_list_share_accepts_mostly_text(tmp_path: Path) -> None:
    body = "= Kapitel\n\n" + SENTENCES + "- Punkt\n"
    assert count(tmp_path, "core.list.share", body) == 0


# core.list.consistent


def test_list_consistent_reports_mixed_items(tmp_path: Path) -> None:
    body = "- Ein ganzer Satz.\n- Noch ein Satz.\n- Stichwort\n"
    assert count(tmp_path, "core.list.consistent", body) == 1


def test_list_consistent_accepts_sentences_and_enumerations(tmp_path: Path) -> None:
    body = "- Ein Satz.\n- Noch ein Satz.\n\nText.\n\n- Äpfel,\n- Birnen und\n- Kirschen.\n"
    assert count(tmp_path, "core.list.consistent", body) == 0


# core.list.punctuation


def test_list_punctuation_reports_bare_items(tmp_path: Path) -> None:
    body = "- Äpfel\n- Birnen\n- Kirschen\n"
    ctx = make_context(tmp_path, body)
    found = messages(run_rule(ctx, "core.list.punctuation"))
    assert len(found) == 3
    assert "comma" in found[0]
    assert "'und'" in found[1]
    assert "period" in found[2]


def test_list_punctuation_accepts_enumeration_and_sentences(tmp_path: Path) -> None:
    body = "- Äpfel,\n- Birnen sowie\n- Kirschen.\n\nText.\n\n- Ein Satz.\n- Noch einer.\n"
    assert count(tmp_path, "core.list.punctuation", body) == 0


def test_list_punctuation_handles_nested_lists(tmp_path: Path) -> None:
    body = "- Fragen:\n  - Erste Frage,\n  - zweite Frage und\n  - dritte Frage.\n- Methode.\n"
    assert count(tmp_path, "core.list.punctuation", body) == 0


def test_list_consistent_counts_only_periods(tmp_path: Path) -> None:
    body = "- Ersatz oder Ergänzung?\n- Stichwort\n- Noch ein Stichwort\n"
    assert count(tmp_path, "core.list.consistent", body) == 0
