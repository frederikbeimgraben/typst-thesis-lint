from typing import TYPE_CHECKING

import pytest

from tests.helpers import make_context, messages, run_rule

if TYPE_CHECKING:
    from pathlib import Path


def findings_for(tmp_path: Path, rule_id: str, body: str) -> list[str]:
    ctx = make_context(tmp_path, f"= Kapitel\n\n{body}\n")
    return messages(run_rule(ctx, rule_id))


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("Das ist so#footnote[Ein Hinweis.] im Text.", 1),
        ("Das ist so.#footnote[Ein Hinweis.] Weiter.", 0),
        ("Das ist so,#footnote[Ein Hinweis.] im Text.", 0),
        ("Das ist so --#footnote[Ein Hinweis.] im Text.", 0),
        ("Das ist so.#footnote[Eins.]#footnote[Zwei.] Weiter.", 0),
    ],
)
def test_after_punctuation(tmp_path: Path, text: str, count: int) -> None:
    assert len(findings_for(tmp_path, "core.footnote.after-punctuation", text)) == count


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("Text.#footnote[ein Hinweis.] Weiter.", 1),
        ("Text.#footnote[Ein Hinweis] Weiter.", 1),
        ("Text.#footnote[ein Hinweis] Weiter.", 2),
        ("Text.#footnote[Ein Hinweis.] Weiter.", 0),
        ('Text.#footnote["Ein Zitat."] Weiter.', 0),
    ],
)
def test_format(tmp_path: Path, text: str, count: int) -> None:
    assert len(findings_for(tmp_path, "core.footnote.format", text)) == count


def test_after_digit(tmp_path: Path) -> None:
    rule_id = "core.footnote.after-digit"
    assert len(findings_for(tmp_path / "a", rule_id, "Es sind 42#footnote[Quelle.] Fälle.")) == 1
    assert findings_for(tmp_path / "b", rule_id, "Es sind 42 Fälle.#footnote[Quelle.]") == []
