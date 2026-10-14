"""Run the enabled rules and turn their findings into diagnostics."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

from thesis_lint import suppress
from thesis_lint.context import Context, PdfUnavailableError, Profile
from thesis_lint.model import Diagnostic, Location, Needs, Severity
from thesis_lint.pdf import CompileError
from thesis_lint.registry import all_rules

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from thesis_lint.config import RuleConfig
    from thesis_lint.registry import Finding

ENGINE_RULE = "engine"


@dataclass(frozen=True, slots=True)
class Result:
    """The diagnostics of a run and notes about skipped rules."""

    diagnostics: tuple[Diagnostic, ...]
    notes: tuple[str, ...]
    suppressed: int = 0

    @property
    def errors(self) -> int:
        """Return the number of errors."""
        return sum(d.severity is Severity.ERROR for d in self.diagnostics)

    @property
    def warnings(self) -> int:
        """Return the number of warnings."""
        return sum(d.severity is Severity.WARNING for d in self.diagnostics)


def run(ctx: Context, needs: Iterable[Needs]) -> Result:
    """Run all enabled rules that need only the inputs in `needs`."""
    allowed = frozenset(needs)
    selected = [
        (rule_id, settings)
        for rule_id, settings in ctx.config.rules.items()
        if settings.rule.needs in allowed
    ]
    skipped = [
        (rule_id, settings)
        for rule_id, settings in selected
        if settings.rule.needs is Needs.SOURCES_DIR and ctx.ci
    ]
    notes = tuple(
        f"{rule_id}: skipped in CI because the source PDFs are not in git" for rule_id, _ in skipped
    )
    runnable = [item for item in selected if item not in skipped]
    diagnostics = chain(
        _input_errors(ctx),
        chain.from_iterable(_rule_diagnostics(ctx, rule_id, s) for rule_id, s in runnable),
    )
    # A failed compilation makes every PDF rule fail. Report it only once.
    unique = dict.fromkeys(diagnostics)
    suppressions, comment_errors = suppress.parse(_comments(ctx), frozenset(all_rules()))
    outcome = suppress.apply(unique, suppressions, frozenset(rule_id for rule_id, _ in runnable))
    ordered = sorted(
        chain(outcome.kept, comment_errors, outcome.comment_findings),
        key=lambda d: (str(d.location.path), d.location.line, d.location.column, d.rule_id),
    )
    return Result(diagnostics=tuple(ordered), notes=notes, suppressed=outcome.suppressed)


def _comments(ctx: Context) -> Iterator[suppress.Comment]:
    """Yield the comments of all Typst and BibTeX files of the project."""
    project = ctx.project
    extra = (source for source in (project.settings_source, project.glossary_source) if source)
    sources = {source.path.resolve(): source for source in chain(project.document.files, extra)}
    yield from chain.from_iterable(suppress.typst_comments(source) for source in sources.values())
    yield from chain.from_iterable(
        suppress.bib_comments(ctx.root / name) for name in ctx.config.paths.bib
    )


def _input_errors(ctx: Context) -> Iterator[Diagnostic]:
    main = Location(ctx.root / ctx.config.paths.main)
    yield from (
        Diagnostic(ENGINE_RULE, Severity.ERROR, message, main)
        for message in ctx.project.document.errors
    )
    yield from (
        Diagnostic(ENGINE_RULE, Severity.ERROR, message, location)
        for location, message in ctx.project.bibliography.errors
    )


def _rule_diagnostics(ctx: Context, rule_id: str, settings: RuleConfig) -> Iterator[Diagnostic]:
    main = Location(ctx.root / ctx.config.paths.main)
    try:
        findings = list(settings.rule.check(ctx, settings.params))
    except (PdfUnavailableError, CompileError) as exc:
        yield Diagnostic(
            ENGINE_RULE,
            Severity.ERROR,
            f"cannot get the PDF. The PDF rules do not run: {exc}",
            main,
        )
        return
    except Exception as exc:  # noqa: BLE001 - one broken rule must not stop the run
        detail = traceback.format_exception_only(exc)[-1].strip()
        yield Diagnostic(
            ENGINE_RULE, Severity.ERROR, f"internal error in rule {rule_id}: {detail}", main
        )
        return
    yield from (_diagnostic(ctx, rule_id, settings, finding) for finding in findings)


def _diagnostic(ctx: Context, rule_id: str, settings: RuleConfig, finding: Finding) -> Diagnostic:
    severity = finding.severity or settings.severity
    submission = settings.rule.submission if finding.submission is None else finding.submission
    downgrade = ctx.profile is Profile.DRAFT and submission and severity is Severity.ERROR
    return Diagnostic(
        rule_id, Severity.WARNING if downgrade else severity, finding.message, finding.location
    )
