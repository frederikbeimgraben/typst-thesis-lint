from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import make_context
from thesis_lint import engine
from thesis_lint.model import Needs

if TYPE_CHECKING:
    from pathlib import Path

TOML = '[rules."core.style.man"]\n[rules."core.style.we"]\n'


def _ids(tmp_path: Path, body: str, files: dict[str, str] | None = None) -> list[str]:
    ctx = make_context(tmp_path, body, lint_toml=TOML, files=files)
    return [d.rule_id for d in engine.run(ctx, {Needs.SOURCE}).diagnostics]


def test_same_line_suppresses(tmp_path: Path) -> None:
    body = "Das macht man so. // ignore: core.style.man; Zitat aus der Quelle\n"
    assert _ids(tmp_path, body) == []


def test_previous_line_suppresses_next_line(tmp_path: Path) -> None:
    body = "// ignore: core.style.man; Beispielsatz\nDas macht man so.\n"
    assert _ids(tmp_path, body) == []


def test_two_lines_below_is_not_suppressed(tmp_path: Path) -> None:
    body = "// ignore: core.style.man; Beispielsatz\n\nDas macht man so.\n"
    assert sorted(_ids(tmp_path, body)) == ["core.style.man", "ignore.unused"]


def test_several_ids(tmp_path: Path) -> None:
    body = "Wir machen das, wie man es macht. // ignore: core.style.man,core.style.we; Beispiel\n"
    assert _ids(tmp_path, body) == []


def test_missing_reason_is_an_error(tmp_path: Path) -> None:
    body = "Das macht man so. // ignore: core.style.man\n"
    assert sorted(_ids(tmp_path, body)) == ["core.style.man", "ignore.syntax"]


def test_missing_ids_is_an_error(tmp_path: Path) -> None:
    body = "Das macht man so. // ignore: ; weil\n"
    assert sorted(_ids(tmp_path, body)) == ["core.style.man", "ignore.syntax"]


def test_unknown_rule_is_an_error(tmp_path: Path) -> None:
    body = "Text. // ignore: core.style.nope; weil\n"
    assert _ids(tmp_path, body) == ["ignore.unknown-rule"]


def test_unused_is_a_warning(tmp_path: Path) -> None:
    body = "Ein Satz ohne Befund. // ignore: core.style.man; weil\n"
    assert _ids(tmp_path, body) == ["ignore.unused"]


def test_rule_that_did_not_run_is_not_unused(tmp_path: Path) -> None:
    body = "Ein Satz. // ignore: core.style.filler; weil\n"
    assert _ids(tmp_path, body) == []


def test_bib_comment(tmp_path: Path) -> None:
    bib = (
        "% ignore: core.bib.urldate; Abrufdatum unbekannt\n@online{a, title={T}, url={https://x}}\n"
    )
    ctx = make_context(
        tmp_path, "Text @a.\n", files={"main.bib": bib}, lint_toml='[rules."core.bib.urldate"]\n'
    )
    assert [d.rule_id for d in engine.run(ctx, {Needs.SOURCE}).diagnostics] == []
