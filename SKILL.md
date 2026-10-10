---
name: sysml-skill
description: SysML v2 / KerML linter for opencode agents. Use when editing, creating, or reviewing SysML v2 textual notation files (.sysml or .kerml). Runs sysmlpy for syntax parsing and semantic well-formedness (undefined symbols, cyclic specialization, invalid multiplicity, unresolved imports, incompatible redefinition/subsetting) and sysml-style for formatting/style rules (SML1xx whitespace, SML2xx naming, SML3xx structure, SML4xx idioms). Use ONLY for SysML v2 / KerML textual notation; not for SysML v1 XMI, MDXML, or other modeling formats.
---

# SysML v2 check

Check `.sysml` and `.kerml` files for **syntax**, **semantic**, and **style/formatting** issues in one pass.

## When to use

Trigger this skill whenever you (the agent) are about to finish editing, or are asked to review, one or more `.sysml` / `.kerml` files. Run the checker *before* declaring a SysML editing task done, and whenever the user asks to "lint", "check", "validate", or "format" SysML v2 files.

Do **not** trigger for SysML v1, XMI, MDXML, or `.sysml` files that are actually SysML v1 — this skill is SysML v2 / KerML textual notation only.

## Prerequisites

Both tools are pip-installable (`sysml-style` depends on `sysmlpy`):

```
pip install sysmlpy sysml-style
```

If `sysmlpy` is missing the script exits with code 2 and prints the install hint. If `sysml-style` is missing the STYLE layer is skipped with a note (syntax + semantic still run).

## Run the checker

The checker script lives at `scripts/check_sysml.py` in this skill's directory. Invoke it by absolute path — the skill's base directory is shown at the bottom of this skill text.

```
python3 <SKILL_DIR>/scripts/check_sysml.py FILE [FILE ...]
```

Options:

| Flag | Effect |
| --- | --- |
| `--library PATH` | Library path for import resolution (repeatable). Defaults to the bundled sysmlpy standard library. |
| `--no-library` | Disable library import resolution (may produce `UNDEFINED_SYMBOL` false positives for stdlib references like `ScalarValues::Integer`). |
| `--no-style` | Skip `sysml-style` (syntax + semantic only). |
| `--no-semantic` | Skip `sysmlpy.analyze` (syntax + style only). Also skips library preload. |
| `--ignore CODES` | Comma-separated SML codes to ignore, passed to `sysml-style` (repeatable). |
| `--quiet` | Suppress the per-file header for clean files. |

Exit codes: `0` = no errors (warnings OK), `1` = errors found, `2` = dependency failure.

### Single file vs. multi-file

- **One file:** syntax + semantic + style are reported for that file.
- **Multiple files:** syntax + style are reported per file; semantic analysis runs once on the combined model (via `sysmlpy.load_files`) so **cross-file imports and references resolve correctly**. Semantic issues appear under a `project (combined, cross-file imports)` header. Files with syntax errors are excluded from the combined semantic pass (a model that does not parse cannot be analyzed).

### Library import resolution and caching

By default the checker uses the **bundled sysmlpy standard library** for import resolution (e.g. `ScalarValues::*`, `ISQ::*`). This is fast because `analyze()` uses `LibrarySymbolIndex` — a regex-based scanner, not the ANTLR parser.

A **disk cache** of the library symbol set is kept at `$XDG_CACHE_HOME/sysml-skill/library-index.pkl` (default `~/.cache/sysml-skill/`), keyed by `sysmlpy.__version__` + a content hash of the library directory:

- **First run:** scans the library directory (~0.6s) and writes the pickle.
- **Subsequent runs:** loads the pickle (instant). Cache auto-invalidates when sysmlpy is upgraded or library files change.

Pass `--no-library` to disable import resolution entirely (faster, but stdlib references become `UNDEFINED_SYMBOL` false positives). Pass `--library PATH` (repeatable) to use a custom library instead of the bundled one.

### Performance expectations

Each invocation pays a **one-time ~4-8s ANTLR parser cold start** (loading lexer/parser tables — inherent to the ANTLR Python runtime). Subsequent files in the same process parse in ~0.01s each. The library disk cache adds ~0s on cache hit. Total wall time for a single-file check: ~8-10s. For a long-running alternative that avoids the cold-start tax, use a SysML v2 language server (e.g. `sysml-v2-lsp`) instead of this per-invocation script.

## Reading the output

Issues are grouped per file under `== <file> ==` headers, each prefixed by layer:

```
== vehicle.sysml ==
  SYNTAX    1:28: mismatched input '}' expecting {';', '{'}
  SEMANTIC  [error] UNDEFINED_SYMBOL: Undefined symbol 'Wheel' referenced in Part 'myWheel' on 'myWheel'
  STYLE     3:19: SML101 expected spaces around '=' operator  [fixable]
== summary ==
  errors: 3  warnings: 0
  fixable style issues present — run: sysml-style format vehicle.sysml
RESULT: FAIL
```

- `SYNTAX` lines are `line:col: <message>` from the ANTLR parser. Syntax errors block semantic analysis for that file.
- `SEMANTIC` lines are `[severity] CODE: message on '<element>'`. Severity is `error` or `warning`.
- `STYLE` lines are `line:col: SMLxxx message`, with `  [fixable]` when `sysml-style format` can auto-fix them.
- The final `RESULT: PASS|FAIL` line is the single signal: **PASS only when there are zero errors** (warnings do not fail).

## Fix policy — report first, format on request

1. **Always run the checker and report results first.** Never rewrite files silently.
2. **Syntax and semantic errors are fixed by editing the `.sysml` source directly** (you, the agent). `sysml-style format` does not fix those.
3. **Style/formatting** (`[fixable]` STYLE issues) is fixed by running:
   ```
   sysml-style format FILE [FILE ...]
   ```
   Run `sysml-style format` **only when the user asks to fix formatting** (or after you have fixed all syntax/semantic errors and want to tidy). To preview without writing, use `sysml-style format --diff FILE`. For CI-style non-writing checks, use `sysml-style format --check FILE` (exit 1 if it would reformat).
4. After any fix, **re-run the checker** to confirm `RESULT: PASS`.

## Rule reference

### Style rules (sysml-style, `SMLxxx`)

| Code | Layer | Rule | Fixable |
| --- | --- | --- | --- |
| SML101 | Whitespace | Spaces around `=` and `:>>` | yes |
| SML102 | Whitespace | No space before `;` | yes |
| SML103 | Whitespace | No trailing whitespace | yes |
| SML104 | Whitespace | Indentation a multiple of the detected unit (2/3/4) | no |
| SML105 | Whitespace | Blank line between top-level definitions | yes |
| SML106 | Whitespace | Space before `{` | yes |
| SML201 | Naming | Definition names `UpperCamelCase` | no |
| SML202 | Naming | Usage/feature names `lowerCamelCase` | no |
| SML203 | Naming | Port names end with `Port` | no |
| SML204 | Naming | Avoid spaces in element names (warning-level) | no |
| SML301 | Structure | `import`/`alias` before definitions | no |
| SML302 | Structure | Empty block body `{}` can be omitted | no |
| SML303 | Structure | Filename matches outermost package name (warning-level) | no |
| SML304 | Structure | Usages should have a descriptive name (no anonymous usages) | no |
| SML305 | Structure | `import` must have a visibility (`public`/`private`/`protected`) | yes |
| SML401 | Idioms | Doc comment before element, not after `;` | no |
| SML402 | Idioms | Use `doc` keyword for documentation comments | no |

Configure via `[tool.sysml-style]` in `pyproject.toml`: `max_line_length`, `indent_size`, `ignore = ["SML303", "SML204"]`, `naming_convention = "strict"|"relaxed"`. `sysml-style` walks up from the target file to find `pyproject.toml`; use `--config PATH` to point at a specific one.

### Semantic rules (sysmlpy, from `analyze`)

| Code | Rule |
| --- | --- |
| `UNDEFINED_SYMBOL` | A referenced type/feature/package does not exist (also covers unresolved imports). |
| `DUPLICATE_NAME` | Two members share the same name in one namespace. |
| `CYCLIC_SPECIALIZATION` | A type directly or indirectly specializes itself. |
| `INCOMPATIBLE_SUBSETTING` | A subsetting feature does not reference a defined feature in the inheritance chain. |
| `INCOMPATIBLE_REDEFINITION` | A redefining feature does not reference a defined feature in the inheritance chain. |
| `INCOMPATIBLE_PART_DEFINITION` | A part usage is not typed by a part definition. |
| `INCOMPATIBLE_PORT_DEFINITION` | A port usage is not typed by a port definition. |
| `INCOMPATIBLE_FEATURE_CHAIN` | A chained feature `a.b.c` has incompatible types at some step. |
| `INVALID_MULTIPLICITY_BOUNDS` | Lower bound > upper bound (e.g. `[5..2]`). |
| `UNRESOLVED_IMPORT` | An import target does not exist in the model. |

## Workflow summary

1. After editing `.sysml`/`.kerml`, run `python3 <SKILL_DIR>/scripts/check_sysml.py <files>`.
2. If `RESULT: FAIL`, fix `SYNTAX` first (it blocks semantics), then `SEMANTIC` errors by editing source.
3. If fixable `STYLE` issues remain and the user wants formatting applied, run `sysml-style format <files>`.
4. Re-run the checker until `RESULT: PASS`.
5. Report the final `RESULT` line to the user.
