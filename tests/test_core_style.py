from typing import TYPE_CHECKING

import pytest

from tests.helpers import make_context, messages, run_rule

if TYPE_CHECKING:
    from pathlib import Path


def findings_for(tmp_path: Path, rule_id: str, body: str, **params: object) -> list[str]:
    ctx = make_context(tmp_path, f"= Kapitel\n\n{body}\n")
    return messages(run_rule(ctx, rule_id, **params))


@pytest.mark.parametrize(
    ("rule_id", "bad", "good"),
    [
        ("core.style.first-person", "Hier zeige ich das Ergebnis.", "Das Ergebnis folgt."),
        ("core.style.first-person", "Das ist m. E. falsch.", "Das ist falsch."),
        ("core.style.we", "Hier sehen wir das Ergebnis.", "Hier steht das Ergebnis."),
        ("core.style.man", "Das kann man messen.", "Das ist messbar."),
        ("core.style.filler", "Das ist also richtig.", "Das ist richtig."),
        ("core.style.vague", "Das gilt meistens.", "Das gilt in 80~% der Fälle."),
        ("core.style.vague", "Das kostet in etwa zehn Euro.", "Das kostet zehn Euro."),
        ("core.style.emotional", "Das ist leider so.", "Das ist so."),
        ("core.style.emotional", "Eine wichtige Frage bleibt.", "Eine Frage bleibt."),
        ("core.style.false-superlative", "Die optimalste Lösung.", "Die optimale Lösung."),
        ("core.style.platitude", "Nebenbei bemerkt ist das so.", "Das ist so."),
        ("core.style.generalization", "Das gilt weltweit.", "Das gilt in der EU."),
        ("core.style.so-called", "Das sog. Grounding hilft.", "Das Grounding hilft."),
        ("core.style.so-called", "Die sogenannte Methode.", "Die Methode."),
        (
            "core.style.function-verb",
            "Das System stellt das unter Beweis.",
            "Das System beweist das.",
        ),
        ("core.style.function-verb", "Das ist nicht unwichtig.", "Das ist nicht unbedingt so."),
        (
            "core.phrase.intro-cliche",
            "Dieses Kapitel befasst sich mit Normen.",
            "Normen regeln die Gebrauchsanweisung.",
        ),
        (
            "core.phrase.scope-excuse",
            "Das sprengt den Rahmen dieser Arbeit.",
            "Das Thema hat einen Rahmen.",
        ),
    ],
)
def test_word_rules(tmp_path: Path, rule_id: str, bad: str, good: str) -> None:
    assert len(findings_for(tmp_path / "bad", rule_id, bad)) == 1
    assert findings_for(tmp_path / "good", rule_id, good) == []


def test_word_rules_skip_quotes(tmp_path: Path) -> None:
    assert findings_for(tmp_path, "core.style.first-person", 'Er sagt: "Ich weiß es."') == []


def test_word_rules_skip_declaration(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, "= Eidesstattliche Erklärung\n\nHiermit erkläre ich das.\n")
    assert run_rule(ctx, "core.style.first-person") == []


def test_word_rules_skip_acknowledgements(tmp_path: Path) -> None:
    body = "= Danksagungen\n\nIch danke meiner Familie.\n\n= Kapitel\n\nIch zeige das.\n"
    ctx = make_context(tmp_path, body)
    findings = run_rule(ctx, "core.style.first-person")
    assert [f.location.line for f in findings] == [7]


def test_reader_address(tmp_path: Path) -> None:
    found = findings_for(
        tmp_path / "a", "core.style.reader-address", "Wie geht das? Sehen Sie hin."
    )
    assert len(found) == 2
    good = "Sie zeigen das Ergebnis. Das Ergebnis steht fest."
    assert findings_for(tmp_path / "b", "core.style.reader-address", good) == []


def test_restriction_exception(tmp_path: Path) -> None:
    rule_id = "core.style.restriction-exception"
    assert len(findings_for(tmp_path / "a", rule_id, "Das gilt in der Regel. Es ist so.")) == 1
    good = "Das gilt in der Regel. Eine Ausnahme sind Notfälle."
    assert findings_for(tmp_path / "b", rule_id, good) == []


def test_paired_reference(tmp_path: Path) -> None:
    rule_id = "core.style.paired-reference"
    assert len(findings_for(tmp_path / "a", rule_id, "Anschließend folgt der Test.")) == 1
    good = "Zunächst folgt die Analyse. Anschließend folgt der Test."
    assert findings_for(tmp_path / "b", rule_id, good) == []


def test_subclauses(tmp_path: Path) -> None:
    bad = (
        "Das System prüft, ob die Antwort stimmt, weil Fehler gefährlich sind, "
        "da Patienten davon abhängen."
    )
    assert len(findings_for(tmp_path / "a", "core.style.subclauses", bad)) == 1
    good = "Das System prüft die Antwort, weil Fehler gefährlich sind."
    assert findings_for(tmp_path / "b", "core.style.subclauses", good) == []


def test_relative_clause_needs_verb(tmp_path: Path) -> None:
    text = "Es gibt Hersteller, die Behörde, den Anwender und die Patienten."
    assert findings_for(tmp_path, "core.style.subclauses", text, max_subclauses=0) == []


def test_sentence_length(tmp_path: Path) -> None:
    rule_id = "core.style.sentence-length"
    assert len(findings_for(tmp_path / "a", rule_id, "Ein Wort " * 13 + "Ende.")) == 1
    assert findings_for(tmp_path / "b", rule_id, "Ein kurzer Satz. Noch einer.") == []


def test_single_sentence_paragraph(tmp_path: Path) -> None:
    rule_id = "core.style.single-sentence-paragraph"
    assert len(findings_for(tmp_path / "a", rule_id, "Nur ein Satz.")) == 1
    assert findings_for(tmp_path / "b", rule_id, "Ein Satz. Noch ein Satz.") == []
    assert findings_for(tmp_path / "c", rule_id, "Die Punkte sind:") == []


def test_same_start(tmp_path: Path) -> None:
    rule_id = "core.style.same-start"
    bad = "Das ist eins. Das ist zwei. Das ist drei."
    assert len(findings_for(tmp_path / "a", rule_id, bad)) == 1
    good = "Das ist eins. Hier ist zwei. Das ist drei."
    assert findings_for(tmp_path / "b", rule_id, good) == []


def test_passive_run(tmp_path: Path) -> None:
    rule_id = "core.style.passive-run"
    bad = "Die Daten werden erfasst. Sie wurden geprüft. Das Modell wird verwendet."
    assert len(findings_for(tmp_path / "a", rule_id, bad)) == 1
    good = "Die Daten werden erfasst. Das Team prüft sie. Das Modell wird verwendet."
    assert findings_for(tmp_path / "b", rule_id, good) == []


def test_future_reference(tmp_path: Path) -> None:
    rule_id = "core.style.future-reference"
    bad = "Kapitel drei wird die Ergebnisse zeigen."
    assert len(findings_for(tmp_path / "a", rule_id, bad)) == 1
    bad_passive = "Im Folgenden wird das Modell erläutert werden."
    assert len(findings_for(tmp_path / "b", rule_id, bad_passive)) == 1
    good = "Kapitel drei zeigt die Ergebnisse."
    assert findings_for(tmp_path / "c", rule_id, good) == []


def test_modal_density(tmp_path: Path) -> None:
    rule_id = "core.style.modal-density"
    bad = "Das kann sein. Das muss sein. Das soll sein. Das darf sein. Ein Satz."
    assert len(findings_for(tmp_path / "a", rule_id, bad, min_words=1)) == 1
    good = "Das kann sein. " + "Das ist so. " * 20
    assert findings_for(tmp_path / "b", rule_id, good, min_words=1) == []


def test_gender_consistent(tmp_path: Path) -> None:
    rule_id = "core.style.gender-consistent"
    bad = "Die Leser:innen lesen. Die Nutzer:innen klicken. Die Ärztinnen und Ärzte prüfen."
    found = findings_for(tmp_path / "a", rule_id, bad)
    assert len(found) == 1
    assert "pair" in found[0]
    good = "Die Leser:innen lesen. Die Nutzer:innen klicken."
    assert findings_for(tmp_path / "b", rule_id, good) == []


def test_gender_star_and_slash(tmp_path: Path) -> None:
    text = "Die Leser\\*innen lesen. Die Nutzer/-innen klicken. Die Autor\\*innen schreiben."
    found = findings_for(tmp_path, "core.style.gender-consistent", text)
    assert len(found) == 1
    assert "slash" in found[0]


def test_bold_underline(tmp_path: Path) -> None:
    rule_id = "core.style.bold-underline"
    assert len(findings_for(tmp_path / "a", rule_id, "Das ist *wichtig* hier.")) == 1
    assert len(findings_for(tmp_path / "b", rule_id, "Das ist #underline[so] hier.")) == 1
    assert findings_for(tmp_path / "c", rule_id, "Das ist _kursiv_ hier.") == []


def test_long_parens(tmp_path: Path) -> None:
    rule_id = "core.style.long-parens"
    bad = "Das gilt (" + "ein Wort " * 7 + ") immer."
    assert len(findings_for(tmp_path / "a", rule_id, bad)) == 1
    assert findings_for(tmp_path / "b", rule_id, "Das gilt (laut Norm) immer.") == []


def test_placeholder(tmp_path: Path) -> None:
    ctx = make_context(
        tmp_path / "a",
        "= Kapitel\n\nTODO: Text. [Hier die Hypothese eintragen]\n// XXX prüfen\n",
        files={"metadata.typ": '#let settings = (submitted-on: "TODO")\n'},
    )
    found = run_rule(ctx, "core.placeholder")
    assert len(found) == 4
    good = make_context(tmp_path / "b", "= Kapitel\n\nDas Todo-Listen-Prinzip hilft.\n")
    assert run_rule(good, "core.placeholder") == []
