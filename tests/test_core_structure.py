from typing import TYPE_CHECKING

from tests.helpers import make_context, run_rule

if TYPE_CHECKING:
    from pathlib import Path


def test_min_children_reports_single_subsection(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, "= Eins\n\n== Nur eins\n\nText.\n\n= Zwei\n\n== A\n\n== B\n")
    findings = run_rule(ctx, "core.heading.min-children")
    assert len(findings) == 1
    assert "Eins" in findings[0].message


def test_min_children_accepts_two_subsections(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, "= Zwei\n\n== A\n\n== B\n")
    assert run_rule(ctx, "core.heading.min-children") == []
