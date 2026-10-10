# sysml-skill

A professional-grade SysML v2 / KerML linter and validator designed specifically for coding agents (like Claude Code, OpenCode, and Hermes).

## Overview

`sysml-skill` provides a three-layer validation pipeline for SysML v2 textual notation files (`.sysml`, `.kerml`). It ensures that models are syntactically correct, semantically well-formed, and stylistically consistent.

### Validation Layers

1.  **SYNTAX**: Uses `sysmlpy`'s ANTLR parser to detect structural errors.
2.  **SEMANTIC**: Uses `sysmlpy.analyze` and `sysmlpy.validator` to find:
    - Undefined symbols and unresolved imports.
    - Cyclic specializations.
    - Invalid multiplicities.
    - **ISQ Conformance**: Validates quantities and units (dimensions) against the International System of Quantities.
3.  **STYLE**: Wraps `sysml-style` to enforce naming conventions (e.g., UpperCamelCase for definitions) and formatting rules.

## Installation

### Dependencies

This skill requires:
- `sysmlpy`
- `sysml-style`

```bash
pip install sysmlpy sysml-style
```

## Usage

The checker script is located at `scripts/check_sysml.py`.

```bash
python3 scripts/check_sysml.py FILE [FILE ...]
```

### Key Features

- **Cross-File Resolution**: When multiple files are passed, the tool performs a combined semantic analysis, ensuring that imports and references across files are correctly resolved.
- **Standard Library Support**: Automatically utilizes the bundled `sysmlpy` standard library for import resolution, with a disk-based cache to minimize startup latency.
- **Agent-Friendly Output**: Produces a concise `RESULT: PASS|FAIL` signal, making it ideal for agents to use as a "Definition of Done" check.

### Options

| Flag | Description |
| --- | --- |
| `--library PATH` | Custom library path for import resolution. |
| `--no-library` | Disable library resolution. |
| `--no-style` | Skip style checks. |
| `--no-semantic` | Skip semantic/ISQ analysis. |
| `--ignore CODES` | Ignore specific SML style codes. |

## Fix Policy

1. **Syntax/Semantic Errors**: Must be fixed by editing the source code.
2. **Style Issues**: Fixable style issues can be automatically corrected using:
   ```bash
   sysml-style format FILE [FILE ...]
   ```

## License

MIT
