from typing import TYPE_CHECKING

from tests.helpers import make_context, run_rule

if TYPE_CHECKING:
    from pathlib import Path

BIB = "@book{smith, author = {Smith, A.}, title = {Buch}, year = {2020}}\n"
GOOD_TABLE = "table(columns: 2, table.header[A][B], [a], [b], [c], [d])"


def count(tmp_path: Path, rule_id: str, body: str) -> int:
    ctx = make_context(tmp_path, body, files={"main.bib": BIB})
    return len(run_rule(ctx, rule_id))


def figure(caption: str = "Aufbau des Systems", label: str = "<fig:a>") -> str:
    return f'#figure(image("a.png"), caption: [{caption}]) {label}\n\n'


# core.figure.caption-label-ref


def test_caption_label_ref_reports_missing_parts(tmp_path: Path) -> None:
    body = '#figure(image("a.png"))\n\n' + figure()
    assert count(tmp_path, "core.figure.caption-label-ref", body) == 2


def test_caption_label_ref_accepts_complete_figure(tmp_path: Path) -> None:
    assert count(tmp_path, "core.figure.caption-label-ref", "Siehe @fig:a.\n\n" + figure()) == 0


def test_caption_label_ref_finds_label_after_table_with_citation(tmp_path: Path) -> None:
    body = f"Siehe @tab:a.\n\n#figure({GOOD_TABLE}, caption: [Werte nach @smith]) <tab:a>\n"
    assert count(tmp_path, "core.figure.caption-label-ref", body) == 0


# core.figure.ref-before


def test_ref_before_reports_late_reference(tmp_path: Path) -> None:
    assert count(tmp_path, "core.figure.ref-before", figure() + "Siehe @fig:a.\n") == 1


def test_ref_before_accepts_early_reference(tmp_path: Path) -> None:
    assert count(tmp_path, "core.figure.ref-before", "Siehe @fig:a.\n\n" + figure()) == 0


# core.figure.own-figure


def test_own_figure_reports_own_work_note(tmp_path: Path) -> None:
    body = figure("Aufbau des Systems (eigene Darstellung)")
    assert count(tmp_path, "core.figure.own-figure", body) == 1


def test_own_figure_accepts_plain_caption(tmp_path: Path) -> None:
    assert count(tmp_path, "core.figure.own-figure", figure()) == 0


# core.figure.foreign-source


def test_foreign_source_reports_missing_citation(tmp_path: Path) -> None:
    body = (
        figure("Modell nach Smith (2020)")
        + figure("Quelle: Smith 2020", "<fig:b>")
        + figure("Ablauf, verändert nach Jones", "<fig:c>")
    )
    assert count(tmp_path, "core.figure.foreign-source", body) == 3


def test_foreign_source_accepts_citation_and_plain_words(tmp_path: Path) -> None:
    body = (
        figure("Modell nach @smith")
        + figure("Verteilung nach Alter", "<fig:b>")
        + figure("Werte aus Messreihe A", "<fig:c>")
    )
    assert count(tmp_path, "core.figure.foreign-source", body) == 0


# core.figure.caption-position


def test_caption_position_reports_top(tmp_path: Path) -> None:
    body = "#show figure.where(kind: table): set figure.caption(position: top)\n"
    assert count(tmp_path, "core.figure.caption-position", body) == 1


def test_caption_position_accepts_bottom(tmp_path: Path) -> None:
    body = "#set figure.caption(position: bottom)\n\n" + figure()
    assert count(tmp_path, "core.figure.caption-position", body) == 0


# core.figure.caption-period


def test_caption_period_reports_period_and_verb(tmp_path: Path) -> None:
    body = figure("Aufbau des Systems.") + figure("Das System wird gezeigt", "<fig:b>")
    assert count(tmp_path, "core.figure.caption-period", body) == 2


def test_caption_period_accepts_title(tmp_path: Path) -> None:
    assert count(tmp_path, "core.figure.caption-period", figure()) == 0


# core.figure.numbering


def test_numbering_reports_overrides(tmp_path: Path) -> None:
    body = (
        '#set figure(numbering: "1")\n'
        '#figure(image("a.png"), numbering: none, caption: [Bild])\n'
        "#counter(figure.where(kind: image)).update(0)\n"
    )
    assert count(tmp_path, "core.figure.numbering", body) == 3


def test_numbering_accepts_template_numbering(tmp_path: Path) -> None:
    assert count(tmp_path, "core.figure.numbering", figure()) == 0


# core.table.header-repeat


def test_header_repeat_reports_missing_and_disabled_header(tmp_path: Path) -> None:
    body = (
        "#table(columns: 2, [a], [b])\n\n"
        "#table(columns: 2, table.header(repeat: false)[A][B], [a], [b])\n"
    )
    assert count(tmp_path, "core.table.header-repeat", body) == 2


def test_header_repeat_accepts_header(tmp_path: Path) -> None:
    body = f"#set table(stroke: none)\n#figure({GOOD_TABLE}, caption: [Werte])\n"
    assert count(tmp_path, "core.table.header-repeat", body) == 0


# core.figure.see-text


def test_see_text_reports_reference_to_text(tmp_path: Path) -> None:
    assert count(tmp_path, "core.figure.see-text", figure("Messwerte, siehe Text")) == 1


def test_see_text_accepts_complete_caption(tmp_path: Path) -> None:
    assert count(tmp_path, "core.figure.see-text", figure("Messwerte der Reihe A")) == 0


# core.table.single-column


def test_single_column_reports_one_column_and_one_row(tmp_path: Path) -> None:
    body = (
        "#table(table.header[A], [a], [b])\n\n"
        "#table(columns: 3, table.header[A][B][C], [a], [b], [c])\n"
    )
    assert count(tmp_path, "core.table.single-column", body) == 2


def test_single_column_accepts_real_table(tmp_path: Path) -> None:
    assert count(tmp_path, "core.table.single-column", f"#{GOOD_TABLE}\n") == 0


# core.table.footnote


def test_table_footnote_reports_footnote(tmp_path: Path) -> None:
    body = "#table(columns: 2, table.header[A][B], [a#footnote[Hinweis.]], [b])\n"
    assert count(tmp_path, "core.table.footnote", body) == 1


def test_table_footnote_accepts_table_without_footnote(tmp_path: Path) -> None:
    assert count(tmp_path, "core.table.footnote", f"#{GOOD_TABLE}\n") == 0


# core.table.unit-brackets


def test_unit_brackets_reports_bracketed_unit(tmp_path: Path) -> None:
    body = "#table(columns: 2, table.header[Masse [kg]][Zeit \\[s\\]], [1], [2])\n"
    assert count(tmp_path, "core.table.unit-brackets", body) == 2


def test_unit_brackets_accepts_unit_in_words(tmp_path: Path) -> None:
    body = "#table(columns: 2, table.header[Masse in kg][Zeit (s)], [1], [2])\n"
    assert count(tmp_path, "core.table.unit-brackets", body) == 0


# core.math.numbered


def test_math_numbered_reports_disabled_numbers(tmp_path: Path) -> None:
    body = "#set math.equation(numbering: none)\n\n$ a = b $\n"
    assert count(tmp_path, "core.math.numbered", body) == 1


def test_math_numbered_accepts_default(tmp_path: Path) -> None:
    assert count(tmp_path, "core.math.numbered", "$ a = b $ <eq:a>\n") == 0


# core.ref.forward


def test_forward_reports_reference_to_later_section(tmp_path: Path) -> None:
    body = "= Eins\n\nSiehe @sec:zwei.\n\n= Zwei <sec:zwei>\n"
    assert count(tmp_path, "core.ref.forward", body) == 1


def test_forward_accepts_backward_reference(tmp_path: Path) -> None:
    body = "= Eins <sec:eins>\n\nText.\n\n= Zwei\n\nSiehe @sec:eins.\n"
    assert count(tmp_path, "core.ref.forward", body) == 0


def test_forward_skips_excluded_chapters(tmp_path: Path) -> None:
    body = "= Einleitung\n\nSiehe @sec:zwei.\n\n= Zwei <sec:zwei>\n"
    ctx = make_context(tmp_path, body)
    assert run_rule(ctx, "core.ref.forward", excluded_chapters=["Einleitung"]) == []
