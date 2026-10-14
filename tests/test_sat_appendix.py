from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import make_context, messages, run_rule
from thesis_lint.context import Milestone

if TYPE_CHECKING:
    from pathlib import Path

GOOD = """= Methoden <sec:methoden>

Text.

= Anhang

== Arbeitshypothese

KI-Agenten ersetzen die Gebrauchsanweisung nicht.

== Projektplan

#figure(image("plan.png"), caption: [Projektplan])

== Verbesserungsvorschläge

==== VS001-Kommasetzung beachten

Umgesetzt in #link(<sec:methoden>)[Methoden].

==== VS002-Quellen ergänzen

Umgesetzt in @sec:methoden.
"""


def test_appendix_hypothesis_accepts_text(tmp_path: Path) -> None:
    assert run_rule(make_context(tmp_path, GOOD), "sat.appendix-hypothesis") == []


def test_appendix_hypothesis_reports_placeholder_and_missing(tmp_path: Path) -> None:
    text = "= Anhang\n\n== Arbeitshypothese\n\n[Hier die Arbeitshypothese eintragen]\n"
    found = messages(run_rule(make_context(tmp_path, text), "sat.appendix-hypothesis"))
    assert found == ["the section 'Arbeitshypothese' is empty. Write the working hypothesis"]
    found = messages(run_rule(make_context(tmp_path, "= Anhang\n"), "sat.appendix-hypothesis"))
    assert "has no section 'Arbeitshypothese'" in found[0]


def test_appendix_projectplan_accepts_an_image(tmp_path: Path) -> None:
    assert run_rule(make_context(tmp_path, GOOD), "sat.appendix-projectplan") == []


def test_appendix_projectplan_reports_a_plan_without_image(tmp_path: Path) -> None:
    text = "= Anhang\n\n== Projektplan\n\n#figure(rect(), caption: [Plan])\n"
    found = messages(run_rule(make_context(tmp_path, text), "sat.appendix-projectplan"))
    assert len(found) == 1
    assert "no figure with an image" in found[0]


def test_improvements_runs_only_for_sa32(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, "= Anhang\n", milestone=Milestone.FA)
    assert run_rule(ctx, "sat.improvements") == []


def test_improvements_accepts_a_missing_or_empty_section(tmp_path: Path) -> None:
    for text in ("= Anhang\n", "= Anhang\n\n== Verbesserungsvorschläge\n\nKeine.\n"):
        ctx = make_context(tmp_path, text, milestone=Milestone.SA32)
        assert run_rule(ctx, "sat.improvements") == []


def test_improvements_accepts_linked_vs_headings(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, GOOD, milestone=Milestone.SA32)
    assert run_rule(ctx, "sat.improvements") == []


def test_improvements_reports_level_number_and_link(tmp_path: Path) -> None:
    text = """= Methoden <sec:m>

= Anhang

== Verbesserungsvorschläge

=== VS001-Falsche Ebene

Siehe @sec:m.

==== Ohne Nummer

Kein Link.
"""
    found = messages(
        run_rule(make_context(tmp_path, text, milestone=Milestone.SA32), "sat.improvements")
    )
    assert len(found) == 3
    assert "has level 3" in found[0]
    assert "'Ohne Nummer' has no number" in found[1]
    assert "'Ohne Nummer' has no link" in found[2]
