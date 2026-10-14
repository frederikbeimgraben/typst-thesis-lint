"""Helpers to build small test projects and to run one rule."""

from __future__ import annotations

from typing import TYPE_CHECKING

from thesis_lint import config as config_module
from thesis_lint.context import Context, Milestone, Profile
from thesis_lint.pdf import read_pdf
from thesis_lint.project import load_project
from thesis_lint.registry import all_rules, apply_params

if TYPE_CHECKING:
    from pathlib import Path

    from thesis_lint.pdf import PdfDocument
    from thesis_lint.registry import Finding

DEFAULT_MAIN = '#include "body.typ"\n'


def make_context(  # noqa: PLR0913 - test setup has many optional parts
    tmp_path: Path,
    body: str = "",
    *,
    files: dict[str, str] | None = None,
    lint_toml: str = "",
    profile: Profile = Profile.DRAFT,
    milestone: Milestone | None = None,
    pdf: Path | None = None,
) -> Context:
    """Write a project to `tmp_path` and return a context for it.

    `body` goes to `body.typ`, which `main.typ` includes. `files` adds or replaces
    other files, for example `main.bib`, `metadata.typ` or `glossary.typ`.
    """
    contents = {"main.typ": DEFAULT_MAIN, "body.typ": body, "main.bib": ""} | (files or {})
    for name, text in contents.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (tmp_path / "lint.toml").write_text(lint_toml, encoding="utf-8")
    config = config_module.load(tmp_path)

    def provide() -> PdfDocument:
        if pdf is None:
            msg = "no PDF in this test"
            raise FileNotFoundError(msg)
        return read_pdf(pdf)

    return Context(
        config=config,
        project=load_project(config),
        profile=profile,
        milestone=milestone,
        pdf_provider=provide,
    )


def run_rule(ctx: Context, rule_id: str, **params: object) -> list[Finding]:
    """Run one rule with its default parameters and the given overrides."""
    rule = all_rules()[rule_id]
    values = apply_params(rule.params, {k.replace("_", "-"): v for k, v in params.items()}, rule_id)
    return list(rule.check(ctx, values))


def messages(findings: list[Finding]) -> list[str]:
    """Return the messages of the findings."""
    return [finding.message for finding in findings]
