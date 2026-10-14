"""Command line interface. The commands are `check` (default), `lsp` and `rules-doc`."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from thesis_lint import config as config_module
from thesis_lint import engine
from thesis_lint.context import Context, Milestone, Profile
from thesis_lint.model import Needs
from thesis_lint.pdf import PdfDocument, compile_document, read_pdf
from thesis_lint.project import load_project
from thesis_lint.registry import ConfigError

if TYPE_CHECKING:
    from collections.abc import Sequence

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface and return the exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args and args[0] in {"check", "lsp", "rules-doc"} else "check"
    if args and args[0] == command:
        args = args[1:]
    if command == "lsp":
        from thesis_lint.lsp import serve  # noqa: PLC0415 - pygls loads only for this command

        serve()
        return EXIT_OK
    if command == "rules-doc":
        return _rules_doc(args)
    parser = argparse.ArgumentParser(prog="thesis-lint", description="Lint a Typst thesis.")
    _check_arguments(parser)
    return _check(parser.parse_args(args, namespace=CheckArgs()))


def _rules_doc(args: list[str]) -> int:
    from thesis_lint.rules_doc import render  # noqa: PLC0415 - not needed for checks

    parser = argparse.ArgumentParser(prog="thesis-lint rules-doc")
    parser.add_argument("--output", type=Path, default=Path("RULES.md"))
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    parsed = parser.parse_args(args, namespace=RulesDocArgs())
    output = parsed.output
    text = render()
    if parsed.check:
        current = output.read_text(encoding="utf-8") if output.is_file() else ""
        if current != text:
            sys.stderr.write(f"{output} is out of date. Run `thesis-lint rules-doc`.\n")
            return EXIT_FINDINGS
        return EXIT_OK
    output.write_text(text, encoding="utf-8")
    return EXIT_OK


class CheckArgs(argparse.Namespace):
    """Typed arguments of the `check` command."""

    path: str = "."
    final: bool = False
    milestone: str | None = None
    source_only: bool = False
    ci: bool = False
    pdf: Path | None = None


class RulesDocArgs(argparse.Namespace):
    """Typed arguments of the `rules-doc` command."""

    output: Path = Path("RULES.md")
    check: bool = False


def _check_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", nargs="?", default=".", help="project directory or a file in it")
    parser.add_argument("--final", action="store_true", help="use the final profile")
    parser.add_argument(
        "--milestone", choices=[m.value for m in Milestone], help="SAT milestone of the submission"
    )
    parser.add_argument(
        "--source-only", action="store_true", help="do not compile, run only the source rules"
    )
    parser.add_argument(
        "--ci", action="store_true", help="CI mode, skip rules that need the source PDFs"
    )
    parser.add_argument("--pdf", type=Path, help="keep the compiled PDF at this path")


def _check(args: CheckArgs) -> int:
    try:
        root = config_module.find_root(Path(args.path))
        config = config_module.load(root)
    except ConfigError as exc:
        sys.stderr.write(f"thesis-lint: {exc}\n")
        return EXIT_USAGE
    project = load_project(config)
    source_only = args.source_only
    ci = args.ci or os.environ.get("CI") == "true"
    keep = args.pdf
    with tempfile.TemporaryDirectory(prefix="thesis-lint-") as tmp:
        output = keep or Path(tmp) / "document.pdf"

        def provide() -> PdfDocument:
            fonts = [root / path for path in config.paths.font_paths]
            path = compile_document(root, root / config.paths.main, fonts, output)
            return read_pdf(path)

        ctx = Context(
            config=config,
            project=project,
            profile=Profile.FINAL if args.final else Profile.DRAFT,
            milestone=Milestone(args.milestone) if args.milestone else None,
            ci=ci,
            pdf_provider=None if source_only else provide,
        )
        needs = {Needs.SOURCE} if source_only else {Needs.SOURCE, Needs.PDF, Needs.SOURCES_DIR}
        result = engine.run(ctx, needs)
    for diagnostic in result.diagnostics:
        sys.stdout.write(diagnostic.format(root) + "\n")
    for note in result.notes:
        sys.stderr.write(f"note: {note}\n")
    counts = f"{result.errors} error(s), {result.warnings} warning(s)"
    sys.stderr.write(f"{counts}, {result.suppressed} suppressed, profile {ctx.profile}\n")
    return EXIT_FINDINGS if result.errors else EXIT_OK
