"""Language server. It publishes the findings of the source rules as diagnostics.

The server does not compile the document. Rules that need the PDF or the
source PDF directory run only in the command line interface.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path

from lsprotocol import types
from pygls.lsp.server import LanguageServer
from pygls.uris import from_fs_path, to_fs_path

from thesis_lint import config as config_module
from thesis_lint import engine
from thesis_lint.context import Context
from thesis_lint.model import Diagnostic, Location, Needs, Severity
from thesis_lint.project import load_project
from thesis_lint.registry import ConfigError

DEBOUNCE_SECONDS = 0.4
WATCHED_SUFFIXES = frozenset({".typ", ".bib", ".toml"})


class ThesisLintServer(LanguageServer):
    """The language server with the state of one editor session."""

    def __init__(self) -> None:
        """Make the server and the state for debounced runs."""
        # pygls declares untyped *args and **kwargs on this constructor.
        super().__init__("thesis-lint", "0.1.0")  # pyright: ignore[reportUnknownMemberType]
        self.published: dict[Path, set[str]] = defaultdict(set)
        self.pending: dict[Path, asyncio.Task[None]] = {}


server = ThesisLintServer()


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def did_open(ls: ThesisLintServer, params: types.DidOpenTextDocumentParams) -> None:
    """Lint the project of the opened file."""
    _schedule(ls, params.text_document.uri, delay=0)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
async def did_change(ls: ThesisLintServer, params: types.DidChangeTextDocumentParams) -> None:
    """Lint the project of the changed file after a short pause."""
    _schedule(ls, params.text_document.uri, delay=DEBOUNCE_SECONDS)


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
async def did_save(ls: ThesisLintServer, params: types.DidSaveTextDocumentParams) -> None:
    """Lint the project of the saved file."""
    _schedule(ls, params.text_document.uri, delay=0)


def _schedule(ls: ThesisLintServer, uri: str, delay: float) -> None:
    path_text = to_fs_path(uri)
    if path_text is None:
        return
    path = Path(path_text)
    if path.suffix not in WATCHED_SUFFIXES:
        return
    try:
        root = config_module.find_root(path)
    except ConfigError:
        return
    running = ls.pending.get(root)
    if running is not None and not running.done():
        running.cancel()
    ls.pending[root] = asyncio.ensure_future(_run_later(ls, root, delay))


async def _run_later(ls: ThesisLintServer, root: Path, delay: float) -> None:
    if delay:
        await asyncio.sleep(delay)
    lint_and_publish(ls, root)


def lint_and_publish(ls: ThesisLintServer, root: Path) -> None:
    """Run the source rules for the project at `root` and publish the diagnostics."""
    overrides = _open_buffers(ls, root)
    by_file: dict[Path, list[types.Diagnostic]] = defaultdict(list)
    try:
        config = config_module.load(root)
        project = load_project(config, overrides)
        result = engine.run(Context(config=config, project=project), {Needs.SOURCE})
        diagnostics = result.diagnostics
    except ConfigError as exc:
        diagnostics = [
            Diagnostic(
                "engine", Severity.ERROR, str(exc), Location(root / config_module.CONFIG_NAME)
            )
        ]
    for diagnostic in diagnostics:
        path = diagnostic.location.path.resolve()
        by_file[path].append(_to_lsp(diagnostic, _line_texts(path, overrides)))
    uris = {from_fs_path(str(path)) or path.as_uri() for path in by_file}
    stale = ls.published[root] - uris
    for path, items in by_file.items():
        uri = from_fs_path(str(path)) or path.as_uri()
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=items)
        )
    for uri in stale:
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
        )
    ls.published[root] = uris


def _open_buffers(ls: ThesisLintServer, root: Path) -> dict[Path, str]:
    buffers: dict[Path, str] = {}
    for uri, document in ls.workspace.text_documents.items():
        path_text = to_fs_path(uri)
        if path_text is None:
            continue
        path = Path(path_text).resolve()
        if path.is_relative_to(root.resolve()):
            buffers[path] = document.source
    return buffers


def _line_texts(path: Path, overrides: dict[Path, str]) -> list[str]:
    text = overrides.get(path)
    if text is None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
    return text.split("\n")


def _utf16_column(lines: list[str], line: int, column: int) -> int:
    """Convert a 1-based character column to a 0-based UTF-16 column."""
    if line - 1 >= len(lines) or line < 1:
        return max(column - 1, 0)
    prefix = lines[line - 1][: max(column - 1, 0)]
    return len(prefix.encode("utf-16-le")) // 2


def _to_lsp(diagnostic: Diagnostic, lines: list[str]) -> types.Diagnostic:
    loc = diagnostic.location
    start_line = max(loc.line - 1, 0)
    start = types.Position(start_line, _utf16_column(lines, loc.line, loc.column))
    if loc.end_line is not None and loc.end_column is not None:
        end = types.Position(loc.end_line - 1, _utf16_column(lines, loc.end_line, loc.end_column))
    else:
        width = len(lines[start_line].encode("utf-16-le")) // 2 if start_line < len(lines) else 0
        end = types.Position(start_line, max(width, start.character))
    severity = (
        types.DiagnosticSeverity.Error
        if diagnostic.severity is Severity.ERROR
        else types.DiagnosticSeverity.Warning
    )
    return types.Diagnostic(
        range=types.Range(start=start, end=end),
        message=diagnostic.message,
        severity=severity,
        code=diagnostic.rule_id,
        source="thesis-lint",
    )


def serve() -> None:
    """Start the server on standard input and output."""
    server.start_io()
