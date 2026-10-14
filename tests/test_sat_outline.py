from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import make_context, messages, run_rule
from tests.test_sat_pdf import example_pdf, transform, use_pdf

if TYPE_CHECKING:
    from pathlib import Path

    from thesis_lint.pdf import PdfChar, PdfPage

CHAPTERS = (
    "Einleitung",
    "Methoden",
    "Ergebnisse",
    "Diskussion",
    "Zusammenfassung",
    "Literaturverzeichnis",
    "Danksagungen",
    "Eidesstattliche Erklärung",
    "Anhang",
)
DECLARATION_PARTS = (
    "Hiermit erkläre ich an Eides statt, dass ich die vorliegende Arbeit selbstständig",
    "erstellt, keine nicht genannte fremde Hilfe in Anspruch genommen und alle von mir",
    "verwendeten Hilfsmittel und Quellen in der Arbeit benannt und kenntlich gemacht habe.",
    "Die Arbeit oder Teile davon wurden in keinem Prüfungsmodul zur Prüfung vorgelegt und",
    "verletzt in keiner Weise Rechte Dritter.\n\n",
    "Mir ist bekannt, dass eine unwahre Erklärung als Täuschung gewertet wird.\n",
)
DECLARATION = " ".join(DECLARATION_PARTS)


def body(*titles: str) -> str:
    return "".join(f"= {title}\n\nText.\n\n" for title in titles)


def test_outline_accepts_the_sat_chapters(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, body(*CHAPTERS))
    assert run_rule(ctx, "sat.outline") == []


def test_outline_reports_missing_extra_and_misplaced_chapters(tmp_path: Path) -> None:
    titles = ("Methoden", "Einleitung", "Technik", *CHAPTERS[2:-1])
    found = messages(run_rule(make_context(tmp_path, body(*titles)), "sat.outline"))
    assert any("'Technik' is not a SAT chapter" in m for m in found)
    assert any("'Anhang' is missing" in m for m in found)
    assert any("'Methoden' is at the wrong position" in m for m in found)


def test_max_depth_allows_vs_headings_in_the_appendix(tmp_path: Path) -> None:
    text = "= Methoden\n\n== A\n\n= Anhang\n\n== Verbesserungsvorschläge\n\n==== VS001-Komma\n"
    assert run_rule(make_context(tmp_path, text), "sat.max-depth") == []


def test_max_depth_reports_level_three(tmp_path: Path) -> None:
    text = "= Methoden\n\n== A\n\n=== Zu tief\n\n= Anhang\n\n==== Kein VS\n"
    found = messages(run_rule(make_context(tmp_path, text), "sat.max-depth"))
    assert len(found) == 2
    assert "'Zu tief' has level 3" in found[0]


def test_directories_accepts_the_template(tmp_path: Path) -> None:
    files = {"metadata.typ": '#let settings = (layout: "sat-meti")\n'}
    ctx = use_pdf(make_context(tmp_path, files=files), example_pdf())
    assert run_rule(ctx, "sat.directories") == []


def test_directories_reports_a_missing_list_and_layout(tmp_path: Path) -> None:
    def drop_glossary(page: PdfPage, char: PdfChar) -> PdfChar | None:
        return None if page.index == 7 and char.size > 15 else char

    files = {"metadata.typ": '#let settings = (layout: "default")\n'}
    ctx = use_pdf(make_context(tmp_path, files=files), transform(example_pdf(), drop_glossary))
    found = messages(run_rule(ctx, "sat.directories"))
    assert len(found) == 2
    assert "layout is 'default'" in found[0]
    assert "'Glossar'" in found[1]


def test_declaration_accepts_the_function(tmp_path: Path) -> None:
    text = "= Eidesstattliche Erklärung\n#declaration()\n"
    assert run_rule(make_context(tmp_path, text), "sat.declaration") == []


def test_declaration_accepts_the_exact_text(tmp_path: Path) -> None:
    text = "= Eidesstattliche Erklärung\n\n" + DECLARATION
    assert run_rule(make_context(tmp_path, text), "sat.declaration") == []


def test_declaration_reports_a_changed_text(tmp_path: Path) -> None:
    text = "= Eidesstattliche Erklärung\n\n" + DECLARATION.replace("unwahre", "falsche")
    found = messages(run_rule(make_context(tmp_path, text), "sat.declaration"))
    assert len(found) == 1
    assert "falsche" in found[0]
