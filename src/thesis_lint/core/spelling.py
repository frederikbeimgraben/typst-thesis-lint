"""A small wrapper around the hunspell spell checker.

The rules `core.style.spelling` and `core.style.compound-hyphen` use this
module. It starts `hunspell -l` once for a set of words and returns the words
that the dictionary does not know. Hunspell finds the dictionary files in the
directories of the `DICPATH` environment variable and in its default paths.

The caller can give the lines of a personal dictionary. This module writes them
to a temporary file and gives the file to hunspell with `-p`. Each line is a
word (`Hirsch`), a word and a model word (`Validierung/Hoffnung`), or a
forbidden word (`*Fehlwort`). With a model word, the word gets the affixes of
the model word. The model word must be a root word of the hunspell dictionary.

If the hunspell program or the dictionary is missing, the functions raise
`SpellCheckUnavailableError`. The rules then report one warning and stop.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# The maximum time in seconds for one hunspell run.
_TIMEOUT = 60.0


class SpellCheckUnavailableError(Exception):
    """Hunspell or its dictionary is not available."""


def unknown_words(
    words: Iterable[str], language: str = "de_DE", personal: Iterable[str] = ()
) -> frozenset[str]:
    """Return the words of `words` that the hunspell dictionary `language` does not know.

    Give one word per item. A word must not contain white space. `personal` are
    the lines of a hunspell personal dictionary (see the module docstring).
    """
    return _unknown(
        frozenset(word for word in words if word and not _has_space(word)),
        language,
        tuple(line.strip() for line in personal if line.strip()),
    )


def available(language: str = "de_DE") -> bool:
    """Return True if hunspell and the dictionary `language` are available."""
    try:
        _ = unknown_words(("Haus",), language)
    except SpellCheckUnavailableError:
        return False
    return True


def _has_space(word: str) -> bool:
    return any(char.isspace() for char in word)


@cache
def _unknown(words: frozenset[str], language: str, personal: tuple[str, ...]) -> frozenset[str]:
    program = shutil.which("hunspell")
    if program is None:
        msg = "the program 'hunspell' is not on the PATH"
        raise SpellCheckUnavailableError(msg)
    try:
        with tempfile.TemporaryDirectory(prefix="thesis-lint-") as folder:
            options: list[str] = []
            if personal:
                path = Path(folder) / "personal.dic"
                _ = path.write_text("\n".join(personal) + "\n", encoding="utf-8")
                options = ["-p", str(path)]
            result = subprocess.run(  # noqa: S603 - the arguments are fixed, the words go to stdin
                [program, "-d", language, "-l", "-i", "utf-8", *options],
                input="\n".join(sorted(words)) + "\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=_TIMEOUT,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        msg = f"hunspell did not run ({exc})"
        raise SpellCheckUnavailableError(msg) from exc
    if result.returncode != 0:
        detail = next(iter(result.stderr.strip().splitlines()), f"exit code {result.returncode}")
        msg = f"hunspell failed for the dictionary {language!r}: {detail}"
        raise SpellCheckUnavailableError(msg)
    return frozenset(line.strip() for line in result.stdout.splitlines() if line.strip())
