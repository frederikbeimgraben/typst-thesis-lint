from typing import TYPE_CHECKING

import pytest

from tests.helpers import make_context, messages, run_rule

if TYPE_CHECKING:
    from pathlib import Path

    from thesis_lint.context import Context

GLOSSARY = """
#let terms = (
  "Halluzination": (
    name: "Halluzination",
    description: [Falsche Ausgabe.],
    genitive: "Halluzination",
    plural: "Halluzinationen",
  ),
  "Grounding": (name: "Grounding", description: [Rückbindung.]),
)

#let acronyms = (
  "AIA": (short: "AI Act", long: "Verordnung (EU) 2024/1689 über künstliche Intelligenz"),
  "IFU": "Gebrauchsanweisung (Instructions for Use)",
  "eIFU": "elektronische Gebrauchsanweisung",
  "KI": "Künstliche Intelligenz",
  "LLM": "Large Language Model",
  "MDR": "Medical Device Regulation, Verordnung (EU) 2017/745",
)
"""

USE_ALL = (
    '#gls("Halluzination") #gls("Grounding") #gls("AIA") #gls("IFU") #gls("eIFU") '
    '#gls("KI") #gls("LLM") #gls("MDR")'
)


def context(tmp_path: Path, body: str) -> Context:
    return make_context(tmp_path, f"= Kapitel\n\n{body}\n", files={"glossary.typ": GLOSSARY})


def found(tmp_path: Path, rule_id: str, body: str) -> list[str]:
    return messages(run_rule(context(tmp_path, body), rule_id))


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("Die DSGVO gilt.", 1),
        ("Die SaMD und die BfArM prüfen.", 2),
        ("Die Norm ISO 13485 gilt in der EU.", 0),
        ("Die Klasse IIa gilt nach Anhang VIII.", 0),
        ('Die #gls("MDR") gilt.', 0),
        ("Die MDR gilt.", 0),
        ("Der AI Act gilt.", 0),
        ("Das Unternehmen OpenAI und GitHub.", 0),
        ('Er sagt: "Die DSGVO gilt."', 0),
    ],
)
def test_abbrev_glossary(tmp_path: Path, text: str, count: int) -> None:
    assert len(found(tmp_path, "core.abbrev.glossary", text)) == count


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Die MDR gilt.", ["raw short form 'MDR'. Use #gls(\"MDR\")."]),
        ("Viele LLMs antworten.", ["raw short form 'LLMs'. Use #glspl(\"LLM\")."]),
        ("Der AI Act gilt.", ["raw short form 'AI Act'. Use #gls(\"AIA\")."]),
        (
            "Die elektronische Gebrauchsanweisung gilt.",
            ["raw long form 'elektronische Gebrauchsanweisung'. Use #gls(\"eIFU\")."],
        ),
        (
            "Die Gebrauchsanweisungen gelten.",
            ["raw long form 'Gebrauchsanweisungen'. Use #glspl(\"IFU\")."],
        ),
        (
            "Die künstliche Intelligenz hilft.",
            ["raw long form 'künstliche Intelligenz'. Use #gls(\"KI\")."],
        ),
        ('Die #gls("MDR") und die #gls("eIFU") gelten.', []),
        ("Die Kinder mögen Kirschen.", []),
    ],
)
def test_raw_form(tmp_path: Path, text: str, expected: list[str]) -> None:
    assert found(tmp_path, "core.abbrev.raw-form", text) == expected


def test_unused(tmp_path: Path) -> None:
    ctx = context(tmp_path / "a", '#gls("MDR") und #gls("Grounding").')
    findings = run_rule(ctx, "core.abbrev.unused")
    assert len(findings) == 6
    halluzination = next(f for f in findings if "Halluzination" in f.message)
    assert halluzination.location.path.name == "glossary.typ"
    assert halluzination.location.line == 3
    assert found(tmp_path / "b", "core.abbrev.unused", USE_ALL) == []


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("Das gilt. Z. B. hier.", 1),
        ("Das gilt. Bzw. hier.", 1),
        ('#gls("MDR") gilt. #gls("MDR") regelt das.', 1),
        ('#gls("MDR") gilt. Die #gls("MDR") regelt das.', 0),
        ("Das gilt z.B. hier.", 0),
    ],
)
def test_sentence_start(tmp_path: Path, text: str, count: int) -> None:
    assert len(found(tmp_path, "core.abbrev.sentence-start", text)) == count


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Eine Halluzination entsteht.",
            ["raw glossary term 'Halluzination'. Use #gls(\"Halluzination\")."],
        ),
        (
            "Viele Halluzinationen entstehen.",
            ["raw glossary term 'Halluzinationen'. Use #glspl(\"Halluzination\")."],
        ),
        ("Das grounding hilft.", ["raw glossary term 'grounding'. Use #gls(\"Grounding\")."]),
        ('Eine #gls("Halluzination") entsteht.', []),
        ("Die Halluzinationsrate sinkt.", []),
    ],
)
def test_raw_term(tmp_path: Path, text: str, expected: list[str]) -> None:
    assert found(tmp_path, "core.glossary.raw-term", text) == expected
