import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from tests.helpers import make_context, run_rule
from thesis_lint.core.plagiarism import Word, matched_runs, normalize

if TYPE_CHECKING:
    from pathlib import Path

SOURCE = (
    "Die Validierung eines Systems erfordert eine sorgfältige Planung "
    "aller Testfälle und eine unab-\nhängige Prüfung der Ergebnisse durch Experten."
)


def make_source_pdf(tmp_path: Path, key: str, text: str) -> None:
    typst = shutil.which("typst")
    if typst is None:
        pytest.skip("typst is not on PATH")
    directory = tmp_path / "sources"
    directory.mkdir(exist_ok=True)
    source = tmp_path / "source.typ"
    source.write_text(text, encoding="utf-8")
    subprocess.run(  # noqa: S603 - fixed executable, no shell
        [typst, "compile", str(source), str(directory / f"{key}.pdf")], check=True
    )


def test_normalize_joins_hyphenated_words() -> None:
    assert normalize("Eine unab-\nhängige Prüfung, 2026!") == ["eine", "unabhängige", "prüfung"]


def test_matched_runs_merges_overlapping_ngrams() -> None:
    tokens = list("xabcdefgy")
    words = [Word(token, index, index + 1) for index, token in enumerate(tokens)]
    index = {tuple("abcdef"): "k1", tuple("bcdefg"): "k1"}
    assert list(matched_runs(words, index, 6)) == [(1, 7, "k1")]


def test_ngram_reports_unquoted_copy(tmp_path: Path) -> None:
    make_source_pdf(tmp_path, "brink2013", SOURCE)
    body = (
        "Wir wissen: Die Validierung eines Systems erfordert eine sorgfältige Planung "
        "aller Testfälle.\n\n"
        'Er sagt "eine unabhängige Prüfung der Ergebnisse durch Experten" @a[S. 3].\n\n'
        "Ganz eigener Text ohne jede Übereinstimmung mit der Quelle hier.\n"
    )
    ctx = make_context(tmp_path, body, files={"main.bib": "@misc{a, title = {A}}\n"})
    findings = run_rule(ctx, "core.plagiarism.ngram")
    assert len(findings) == 1
    assert "'brink2013'" in findings[0].message
    assert findings[0].message.startswith("10 words")


def test_ngram_without_sources_dir(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, SOURCE + "\n")
    assert run_rule(ctx, "core.plagiarism.ngram") == []
