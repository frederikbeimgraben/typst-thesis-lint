from typing import TYPE_CHECKING

import pytest

from tests.helpers import make_context, messages, run_rule

if TYPE_CHECKING:
    from pathlib import Path


def findings_for(tmp_path: Path, rule_id: str, body: str) -> list[str]:
    ctx = make_context(tmp_path, f"= Kapitel\n\n{body}\n")
    return messages(run_rule(ctx, rule_id))


def test_spell_small_reports_digit(tmp_path: Path) -> None:
    found = findings_for(tmp_path, "core.number.spell-small", "Es gibt 3 Modelle und 12 Tests.")
    assert len(found) == 2


@pytest.mark.parametrize(
    "text",
    [
        "Es gibt drei Modelle.",
        "Das dauert 5~ms.",
        "Der Anteil ist 5~%.",
        "Siehe S. 3 und Kapitel 2.",
        "Das ist die 3. Auflage.",
        "Es sind 3–4 Seiten.",
        "Der Wert ist 2,5.",
        "Version 2.1 erschien.",
        "Art. 6(1) gilt.",
        "Das Modell GPT 4 antwortet.",
        "Es gibt 20 Tests.",
        "Der Code $x = 3$ gilt.",
        'Er sagt: "Es gibt 3 Fälle."',
    ],
)
def test_spell_small_exceptions(tmp_path: Path, text: str) -> None:
    assert findings_for(tmp_path, "core.number.spell-small", text) == []


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("Der Wert ist 2.5 hoch.", 1),
        ("Es kostet 1.000 Euro.", 1),
        ("Es gibt 12500 Fälle.", 1),
        ("Der Wert ist 2,5 hoch.", 0),
        ("Es gibt 12~500 Fälle.", 0),
        ("Im Jahr 2024 gilt es.", 0),
        ("Die Norm ISO 13485 gilt.", 0),
        ("Die DVO 2017/745 gilt.", 0),
        ("Kapitel 3.2 zeigt es.", 0),
        ("Am 01.03.2024 gilt es.", 0),
    ],
)
def test_decimal(tmp_path: Path, text: str, count: int) -> None:
    assert len(findings_for(tmp_path, "core.number.decimal", text)) == count


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("Der Anteil ist 5 %.", 1),
        ("Der Anteil ist 5%.", 1),
        ("Das dauert 10 ms.", 1),
        ("Der Anteil ist 5~%.", 0),
        ("Das dauert 10 ms.", 0),
        ("Der Winkel ist 90°.", 0),
        ("Es sind 5 Modelle.", 0),
    ],
)
def test_unit_space(tmp_path: Path, text: str, count: int) -> None:
    assert len(findings_for(tmp_path, "core.number.unit-space", text)) == count


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("Es gilt 3 + 4 Fälle.", 1),
        ("Die Fehlerrate = 0 ist das Ziel.", 1),
        ("Es gilt 3+4 immer.", 1),
        ("Die Sprache C++ und die Formel $a + b$ gelten.", 0),
        ("Der Pfeil -> zeigt es.", 0),
        ("Das Plus von +5 zählt.", 0),
    ],
)
def test_operators(tmp_path: Path, text: str, count: int) -> None:
    assert len(findings_for(tmp_path, "core.number.operators", text)) == count


def test_dash(tmp_path: Path) -> None:
    assert len(findings_for(tmp_path / "a", "core.typo.dash", "Das ist - wie gesagt - so.")) == 2
    good = "Das ist -- wie gesagt -- so. Ein Bindestrich-Wort."
    assert findings_for(tmp_path / "b", "core.typo.dash", good) == []


def test_double_space(tmp_path: Path) -> None:
    found = findings_for(tmp_path / "a", "core.typo.double-space", "Das ist  so. Und  das.")
    assert len(found) == 2
    good = "Das ist so,\n  und das hier ist eingerückt.   \nDas ist gut. // Kommentar  hier"
    assert findings_for(tmp_path / "b", "core.typo.double-space", good) == []


def test_double_space_location(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, "= Kapitel\n\nDas ist  so.\n")
    [finding] = run_rule(ctx, "core.typo.double-space")
    assert (finding.location.line, finding.location.column) == (3, 8)
