from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import make_context, messages, run_rule
from tests.test_sat_pdf import example_pdf, heading_line, text_line, transform, use_pdf
from thesis_lint.model import Severity

if TYPE_CHECKING:
    from pathlib import Path

    from thesis_lint.pdf import PdfChar, PdfPage

# The word count of the example PDF from "Einleitung" up to "Literaturverzeichnis".
EXAMPLE_WORDS = 226
BODY = "= Einleitung\n\nText.\n\n= Literaturverzeichnis\n"


def settings(*entries: str) -> dict[str, str]:
    return {"metadata.typ": "#let settings = (\n" + "".join(f"  {e},\n" for e in entries) + ")\n"}


def test_wordcount_accepts_a_count_in_range(tmp_path: Path) -> None:
    ctx = use_pdf(make_context(tmp_path, BODY), example_pdf())
    assert run_rule(ctx, "sat.wordcount", max=300, min_warn=200) == []


def test_wordcount_reports_too_many_words(tmp_path: Path) -> None:
    ctx = use_pdf(make_context(tmp_path, BODY), example_pdf())
    findings = run_rule(ctx, "sat.wordcount", max=200)
    assert messages(findings) == [
        f"the text has {EXAMPLE_WORDS} words. The maximum is 200. Remove 26 words"
    ]
    assert findings[0].severity is None


def test_wordcount_warns_about_too_few_words(tmp_path: Path) -> None:
    ctx = use_pdf(make_context(tmp_path, BODY), example_pdf())
    findings = run_rule(ctx, "sat.wordcount")
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


def test_wordcount_titlepage_accepts_the_measured_count(tmp_path: Path) -> None:
    files = settings(f"word-count: {EXAMPLE_WORDS}")
    ctx = use_pdf(make_context(tmp_path, BODY, files=files), example_pdf())
    assert run_rule(ctx, "sat.wordcount-titlepage") == []


def test_wordcount_titlepage_gives_the_correct_number(tmp_path: Path) -> None:
    ctx = use_pdf(make_context(tmp_path, BODY, files=settings("word-count: 100")), example_pdf())
    findings = run_rule(ctx, "sat.wordcount-titlepage")
    assert len(findings) == 1
    assert f"Set word-count: {EXAMPLE_WORDS}" in findings[0].message
    assert findings[0].location.path.name == "metadata.typ"
    assert findings[0].location.line == 2


def test_wordcount_titlepage_reports_a_missing_setting(tmp_path: Path) -> None:
    ctx = use_pdf(make_context(tmp_path, BODY, files=settings('title: "T"')), example_pdf())
    found = messages(run_rule(ctx, "sat.wordcount-titlepage"))
    assert found == [
        f"the title page needs the word count of the PDF. Set word-count: {EXAMPLE_WORDS}"
    ]


def test_abstract_length_accepts_a_length_in_range(tmp_path: Path) -> None:
    ctx = use_pdf(make_context(tmp_path), example_pdf())
    assert run_rule(ctx, "sat.abstract-length", min_words=80) == []


def test_abstract_length_reports_a_short_abstract(tmp_path: Path) -> None:
    ctx = use_pdf(make_context(tmp_path), example_pdf())
    assert messages(run_rule(ctx, "sat.abstract-length")) == [
        "the abstract has 85 words. Use 120 to 160 words"
    ]


def test_abstract_length_reports_an_abstract_that_does_not_fit(tmp_path: Path) -> None:
    keywords = text_line(1, "Keywords:")
    contents = heading_line("Inhalt")

    def overflow(page: PdfPage, char: PdfChar) -> PdfChar | None:
        if page.index == 1 and keywords.top - 1 < char.top < 700:
            return None
        if page.index == contents.page and abs(char.top - contents.top) < 1.0:
            return None
        return char

    ctx = use_pdf(make_context(tmp_path), transform(example_pdf(), overflow))
    found = messages(run_rule(ctx, "sat.abstract-length", min_words=80))
    assert len(found) == 2
    assert "keywords are not on PDF page 2" in found[0]
    assert "continues on PDF page 3" in found[1]


def test_keywords_accepts_five_and_five(tmp_path: Path) -> None:
    files = settings('keywords: "a, b, c, d, e"', 'keywords-en: ("a", "b", "c", "d", "e")')
    assert run_rule(make_context(tmp_path, files=files), "sat.keywords") == []


def test_keywords_reports_wrong_counts(tmp_path: Path) -> None:
    files = settings('keywords: "a, b, c, d"')
    found = messages(run_rule(make_context(tmp_path, files=files), "sat.keywords"))
    assert len(found) == 2
    assert "keywords has 4 keywords" in found[0]
    assert "keywords-en is missing" in found[1]


# sat.keywords-title


def test_keywords_title_reports_repeated_title_words(tmp_path: Path) -> None:
    files = settings(
        "title: [KI-Agenten für die Gebrauchsanweisung]",
        'keywords: "Gebrauchsanweisung, Medizinprodukt, Validierung"',
        'keywords-en: ("instructions for use", "ki-agenten")',
    )
    found = messages(run_rule(make_context(tmp_path, files=files), "sat.keywords-title"))
    assert len(found) == 2
    assert "'Gebrauchsanweisung' in keywords" in found[0]
    assert "'ki-agenten' in keywords-en" in found[1]


def test_keywords_title_accepts_new_words(tmp_path: Path) -> None:
    files = settings(
        "title: [KI-Agenten für Medizinprodukte]",
        'keywords: "Validierung, Agentur, Produkt"',
        'keywords-en: "medical devices, agents"',
    )
    assert run_rule(make_context(tmp_path, files=files), "sat.keywords-title") == []


def test_keywords_title_matches_german_inflection(tmp_path: Path) -> None:
    files = settings(
        "title: [Risiken der KI-Agenten für Medizinprodukte]",
        'keywords: "Medizinprodukt, Agent, Risiko, KI-Agent"',
        'keywords-en: "agents for medical devices"',
    )
    found = messages(run_rule(make_context(tmp_path, files=files), "sat.keywords-title"))
    assert [message.split("'")[1] for message in found] == ["Medizinprodukt", "Agent", "KI-Agent"]
