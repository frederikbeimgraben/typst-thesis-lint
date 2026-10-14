# typst-thesis-lint

A linter for scientific papers and theses that are written in [Typst](https://typst.app).
It checks the structure, the citations, the bibliography, the language style and the
layout of the compiled PDF. Each rule cites the guideline or the book that it comes from.

The rules are in two groups:

- **Pack `core`**: general rules for scientific writing. Every rule has parameters.
- **Pack `sat`**: rules of the SAT seminar of the course Medizinisch-Technische
  Informatik (meti) at Reutlingen University. The preset `sat-meti` enables the
  rules of both packs with the values of the SAT guideline and the SAT template.

[RULES.md](RULES.md) lists all rules with their sources, severities and parameters.

## Usage

The linter needs a `lint.toml` in the root of the Typst project:

```toml
extends = ["sat-meti"]

[paths]
main = "main.typ"
bib = ["main.bib"]
metadata = "metadata.typ"   # file with `#let settings = (...)`
glossary = "glossary.typ"   # file with `#let terms` and `#let acronyms`
sources-dir = "sources"     # PDFs of the cited sources, one file per bib key

[rules."core.style.sentence-length"]
max-words = 30              # change a parameter

[rules."core.style.man"]
enabled = false             # disable a rule

[rules."core.style.filler"]
severity = "warning"        # change the severity
```

Run the linter in the project root:

```sh
nix run github:frederikbeimgraben/typst-thesis-lint -- .
# or, in a checkout of this repository:
uv run thesis-lint path/to/project
```

Options:

| Option | Effect |
| --- | --- |
| `--final` | Use the final profile. Submission rules report errors, not warnings. |
| `--milestone ew\|fa\|sa32` | Enable the rules for one SAT milestone, for example the file name. |
| `--source-only` | Do not compile. Run only the rules that read the source files. |
| `--ci` | Skip the rules that need the source PDFs. `CI=true` has the same effect. |
| `--pdf PATH` | Keep the compiled PDF at this path. |

The exit code is 1 if the linter finds an error, and 2 if the config is not valid.

### Profiles

The default profile is `draft`. In this profile, a submission rule reports a warning
instead of an error. Examples of submission rules are the word count, placeholders
such as `TODO`, and uncited bibliography entries. Use `--final` before you submit.

### Typst and fonts

The linter runs `typst compile` for the PDF rules. Typst must be on the `PATH`.
Set `TYPST_FONT_PATHS` and `TYPST_PACKAGE_PATH` if the template needs them.

## Language server

`thesis-lint lsp` starts a language server on standard input and output. The server
runs the source rules when you open, change or save a `.typ`, `.bib` or `lint.toml`
file. It does not compile the document.

### Zed

The directory `editors/zed` contains a Zed extension for the server.

Zed compiles the extension with rustup. Rustup must have a default toolchain,
because Zed runs `rustc` outside the extension directory:

```sh
rustup default stable
```

1. In Zed, run the command `zed: install dev extension`.
2. Select the directory `editors/zed`.
3. Make sure that `thesis-lint` is on the `PATH`, or set the command in the
   project settings `.zed/settings.json`:

```json
{
  "languages": {
    "Typst": { "language_servers": ["tinymist", "thesis-lint", "..."] }
  },
  "lsp": {
    "thesis-lint": {
      "binary": { "path": "scripts/thesis-lint", "arguments": ["lsp"] }
    }
  }
}
```

A relative `path` is relative to the root of the project.

## Rule packs and presets

A rule is a generator function with the `rule` decorator:

```python
@rule(
    "core.heading.min-children",
    summary="A heading with subsections has at least two subsections.",
    severity=Severity.ERROR,
    sources=[ref(BRINK, "S. 146 f.", "Keinesfalls darf ...")],
)
def min_children(ctx: Context, _params: NoParams) -> Iterator[Finding]:
    ...
```

The first part of the rule ID is the pack. A rule is disabled until a preset or the
project config enables it. A preset is a directory of TOML files in a pack. The loader
merges the files in name order. Add a new preset to `PRESETS` in `config.py`.

## Development

```sh
nix develop
uv sync
uv run pytest
ruff check src tests && ruff format --check src tests
basedpyright
uv run thesis-lint rules-doc   # write RULES.md
```

The dev shell provides `ruff` and `basedpyright` from nixpkgs, because the PyPI
wheels do not run on NixOS.

Code rules:

- basedpyright runs in mode `all`. The type `Any` is not allowed.
- Use generators, comprehensions and small pure functions where possible.
- Write comments and docstrings in STE-flavored English, with ASCII characters only.

## License

MIT. See [LICENSE](LICENSE).
