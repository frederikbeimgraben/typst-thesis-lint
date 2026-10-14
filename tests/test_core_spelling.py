"""Tests of the hunspell rules core.style.spelling and core.style.compound-hyphen."""

from typing import TYPE_CHECKING

import pytest

from tests.helpers import make_context, messages, run_rule
from thesis_lint.core import spelling
from thesis_lint.core.style import SpellToken, is_misspelled, spell_tokens
from thesis_lint.model import Severity

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from thesis_lint.context import Context

needs_hunspell = pytest.mark.skipif(
    not spelling.available("de_DE"), reason="hunspell or the de_DE dictionary is missing"
)

GLOSSARY = """
#let terms = (
  "Grounding": (name: "Grounding", description: [Rückbindung.]),
)

#let acronyms = (
  "LLM": "Large Language Model",
)
"""

BIB = "@book{steddin2026, author = {Steddin, Sven}, title = {Titel}, year = {2026}}\n"


def context(tmp_path: Path, body: str, dictionary: str | None = None) -> Context:
    files = {"glossary.typ": GLOSSARY, "main.bib": BIB}
    if dictionary is not None:
        files["dictionary.txt"] = dictionary
    return make_context(tmp_path, f"= Kapitel\n\n{body}\n", files=files)


def found(tmp_path: Path, rule_id: str, body: str, dictionary: str | None = None) -> list[str]:
    return messages(run_rule(context(tmp_path, body, dictionary), rule_id))


def test_tokens_skip_abbreviations_digits_and_glossary(tmp_path: Path) -> None:
    ctx = context(tmp_path, 'Das LLMs 3D z. B. #gls("Grounding") Grounding Steddin Haus-Tür.')
    unit = next(u for u in ctx.project.document.units if "Haus" in u.text)
    words = [token.word for token in spell_tokens(unit, frozenset({"grounding", "steddin"}))]
    assert words == ["Das", "Haus-Tür"]


def test_hyphen_parts_and_joint_s() -> None:
    token = SpellToken(
        unit=None,  # pyright: ignore[reportArgumentType] - the check does not read the unit
        start=0,
        end=0,
        word="Nutzungs-Analyse",
        whole=("Nutzungs-Analyse",),
        parts=(("Nutzungs", "Nutzung"), ("Analyse",)),
    )
    assert not is_misspelled(token, frozenset({"Nutzungs-Analyse", "Nutzungs"}))
    assert is_misspelled(token, frozenset({"Nutzungs-Analyse", "Analyse"}))


def test_missing_hunspell_gives_one_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "")
    findings = run_rule(
        context(tmp_path, "Ein Satz ohne Prüfprogramm-Kontrolle."), "core.style.spelling"
    )
    assert len(findings) == 1
    assert findings[0].severity == Severity.WARNING
    assert "did not run" in findings[0].message


def test_missing_dictionary_gives_one_warning(tmp_path: Path) -> None:
    findings = run_rule(
        context(tmp_path, "Ein anderer Satz."), "core.style.spelling", language="xx_NONE"
    )
    assert len(findings) == 1
    assert findings[0].severity == Severity.WARNING


@needs_hunspell
def test_spelling(tmp_path: Path) -> None:
    bad = found(tmp_path / "a", "core.style.spelling", "Die Dokumentatoin ist fehlerhaft.")
    assert len(bad) == 1
    assert "Dokumentatoin" in bad[0]
    good = "Die Gebrauchsanweisung beschreibt das Medizinprodukt, bzw. die KI-gestützte Prüfung."
    assert found(tmp_path / "b", "core.style.spelling", good) == []


@needs_hunspell
def test_spelling_ignores_quotes_names_and_dictionary(tmp_path: Path) -> None:
    body = 'Laut Steddin nutzt Grounding den Copilot und "Fehlerr". Das LLM hilft.'
    assert found(tmp_path / "a", "core.style.spelling", body, "# Projektwörter\nCopilot\n") == []
    assert len(found(tmp_path / "b", "core.style.spelling", body)) == 1


@needs_hunspell
def test_compound_hyphen(tmp_path: Path) -> None:
    rule_id = "core.style.compound-hyphen"
    bad = found(tmp_path / "a", rule_id, "Die Daten-Basis und die Risiko-Analyse fehlen.")
    assert len(bad) == 2
    assert "'Datenbasis'" in bad[0]
    good = "Die Datenbasis, Steddin-Verfahren, KI-Agenten, ISO-Normen und Grounding-Verfahren."
    assert found(tmp_path / "b", rule_id, good) == []


def test_compound_hyphen_skips_proper_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unknown_words(
        _words: Iterable[str], _language: str = "de_DE", _personal: Iterable[str] = ()
    ) -> frozenset[str]:
        # Hunspell knows all joined words, but not the name 'Steddin'.
        return frozenset({"Steddin"})

    monkeypatch.setattr(spelling, "unknown_words", unknown_words)
    body = "Das Steddin-Verfahren nutzt die Daten-Basis."
    bad = found(tmp_path, "core.style.compound-hyphen", body)
    assert len(bad) == 1
    assert "'Datenbasis'" in bad[0]


@needs_hunspell
def test_dictionary_model_word_adds_inflections(tmp_path: Path) -> None:
    body = "Die Validierungen sind fertig."
    assert len(found(tmp_path / "a", "core.style.spelling", body)) == 1
    assert len(found(tmp_path / "b", "core.style.spelling", body, "Validierung\n")) == 1
    dictionary = "# Projektwörter\nValidierung/Hoffnung\n"
    assert found(tmp_path / "c", "core.style.spelling", body, dictionary) == []
