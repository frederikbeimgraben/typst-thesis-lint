from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import make_context, messages, run_rule

if TYPE_CHECKING:
    from pathlib import Path

SENTENCE = "Dieser Satz hat neunundvierzig Zeichen am Ende. "


def test_paragraph_length_accepts_short_paragraphs(tmp_path: Path) -> None:
    text = "= Einleitung\n\n" + SENTENCE * 8 + "\n"
    assert run_rule(make_context(tmp_path, text), "sat.paragraph-length") == []


def test_paragraph_length_reports_long_paragraphs(tmp_path: Path) -> None:
    text = "= Einleitung\n\n" + SENTENCE * 9 + "\n\n= Eidesstattliche Erklärung\n\n"
    text += SENTENCE * 9 + "\n"
    found = messages(run_rule(make_context(tmp_path, text), "sat.paragraph-length"))
    assert len(found) == 1
    assert "431 characters" in found[0]


FIGURE = '#figure(image("a.png"), caption: [Bild]) <fig:a>\n\n'


def test_figure_ref_parens_accepts_brackets(tmp_path: Path) -> None:
    text = FIGURE + "Das Bild zeigt den Aufbau (@fig:a). Siehe auch (vgl. @tab:b).\n"
    assert run_rule(make_context(tmp_path, text), "sat.figure-ref-parens") == []


def test_figure_ref_parens_reports_a_bare_reference(tmp_path: Path) -> None:
    text = FIGURE + "Wie @fig:a zeigt, ist es so (siehe oben). Kapitel @sec:x zählt nicht.\n"
    found = messages(run_rule(make_context(tmp_path, text), "sat.figure-ref-parens"))
    assert found == ["the reference @fig:a is not in round brackets. Write (@fig:a)"]


def test_abbrev_style_accepts_the_short_forms(tmp_path: Path) -> None:
    text = "Das gilt z.B. hier, d.h. dort, u.a. bzw. ggf. auch usw. weiter.\n"
    assert run_rule(make_context(tmp_path, text), "sat.abbrev-style") == []


def test_abbrev_style_reports_spaces_and_missing_periods(tmp_path: Path) -> None:
    text = 'Das gilt z. B. hier, d.~h. dort, bzw das. Zitat: "z. B. erlaubt" @key.\n'
    found = messages(run_rule(make_context(tmp_path, text), "sat.abbrev-style"))
    assert found == [
        "write 'z.B.' instead of 'z. B.'",
        "write 'd.h.' instead of 'd. h.'",
        "write 'bzw.' instead of 'bzw'",
    ]
