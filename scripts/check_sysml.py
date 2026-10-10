#!/usr/bin/env python3
"""SysML v2 checker: syntax + semantic (sysmlpy) and style (sysml-style).

Layers:
  SYNTAX   sysmlpy.parse()           parse errors (file:line:col)
  SEMANTIC sysmlpy.analyze()          well-formedness (undefined symbols,
                                      cyclic specialization, bad multiplicity,
                                      unresolved imports, incompatible redefs)
  STYLE    sysml-style check          SML1xx-4xx style/formatting rules

Library handling:
  The ``library`` parameter is passed to ``analyze()`` ONLY, never to
  ``parse()`` or ``load_files()``.  Passing it to the parsing layer makes
  sysmlpy ANTLR-parse all ~88 stdlib files concatenated with the user's
  source (minutes).  ``analyze()`` instead uses ``LibrarySymbolIndex``, a
  fast regex scanner with an in-process cache.

  A disk cache (pickle) of the ``LibrarySymbolIndex`` frozenset is kept
  under ``$XDG_CACHE_HOME/sysml-skill/library-index.pkl``, keyed by
  ``sysmlpy.__version__`` + a hash of the library directory contents.
  First run scans (~0.6s); subsequent runs load the pickle (instant).

Exit codes: 0 = no errors (warnings OK), 1 = errors found, 2 = dep failure.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pickle
import re
import shutil
import subprocess
import sys
from pathlib import Path

STYLE_LINE = re.compile(r"^(.*):(\d+):(\d+):\s*(SML\d+)\s*(.*)$")
PARSE_ERR = re.compile(r"Syntax error at (\d+):(\d+):\s*(.*)$")


# --------------------------------------------------------------------------- #
#  Library index caching
# --------------------------------------------------------------------------- #

def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME", "~/.cache")
    return Path(base).expanduser() / "sysml-skill"


def _library_signature(lib_paths: list[str]) -> str:
    """Hash library directory contents for cache invalidation."""
    h = hashlib.sha256()
    for lp in sorted(lib_paths):
        p = Path(lp)
        h.update(str(p).encode())
        if p.is_dir():
            for ext in ("*.sysml", "*.kerml"):
                for f in sorted(p.rglob(ext)):
                    st = f.stat()
                    h.update(f"{f.relative_to(p)}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()


def _cache_key(lib_paths: list[str]) -> str:
    try:
        import sysmlpy
        ver = sysmlpy.__version__
    except Exception:
        ver = "?"
    return f"{ver}:{_library_signature(lib_paths)}"


def _load_library_cache(lib_paths: list[str]) -> frozenset[str] | None:
    cache_file = _cache_dir() / "library-index.pkl"
    key = _cache_key(lib_paths)
    try:
        with open(cache_file, "rb") as f:
            data = pickle.load(f)
        if data.get("key") == key:
            return data["symbols"]
    except Exception:
        pass
    return None


def _save_library_cache(lib_paths: list[str], symbols: frozenset[str]) -> None:
    cd = _cache_dir()
    cd.mkdir(parents=True, exist_ok=True)
    cache_file = cd / "library-index.pkl"
    key = _cache_key(lib_paths)
    try:
        with open(cache_file, "wb") as f:
            pickle.dump({"key": key, "symbols": symbols}, f)
    except Exception:
        pass


def _bundled_library() -> str | None:
    try:
        import sysmlpy
        p = os.path.join(sysmlpy.__path__[0], "library")
        return p if os.path.isdir(p) else None
    except Exception:
        return None


def preload_library_index(lib_paths: list[str]) -> str:
    """Preload ``LibrarySymbolIndex`` using disk cache when available.

    Returns ``"disk-cache"``, ``"scanned"``, or ``"skipped"``.
    """
    if not lib_paths:
        return "skipped"
    from sysmlpy.semantic import LibrarySymbolIndex

    cached = _load_library_cache(lib_paths)
    if cached is not None:
        LibrarySymbolIndex._cache = cached
        return "disk-cache"

    roots = [Path(p) for p in lib_paths if Path(p).is_dir()]
    if not roots:
        return "skipped"
    symbols = LibrarySymbolIndex.get_symbols(library_roots=roots)
    _save_library_cache(lib_paths, symbols)
    return "scanned"


# --------------------------------------------------------------------------- #
#  Tool discovery
# --------------------------------------------------------------------------- #

def find_sysml_style() -> list[str] | None:
    exe = shutil.which("sysml-style")
    if exe:
        return [exe]
    try:
        r = subprocess.run(
            [sys.executable, "-m", "sysml_style", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return [sys.executable, "-m", "sysml_style"]
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- #
#  Checking layers
# --------------------------------------------------------------------------- #

def read_file(path: str) -> tuple[str | None, str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(), ""
    except OSError as e:
        return None, str(e)


def check_syntax(text: str) -> tuple[list[str], object | None]:
    """Parse with sysmlpy — library is NEVER passed here."""
    try:
        from sysmlpy import parse
        model, errors = parse(text)
        return list(errors or []), model
    except Exception as e:
        return [f"(sysmlpy parse raised: {e})"], None


def elem_name(el) -> str:
    if el is None:
        return ""
    for a in ("name", "qualified_name"):
        v = getattr(el, a, None)
        if v:
            return str(v)
    t = getattr(el, "sysml_type", "")
    return str(t or type(el).__name__)


def check_semantic(model, filename: str | None, library) -> list[str]:
    """Analyze with sysmlpy — library IS passed here (fast regex index)."""
    try:
        from sysmlpy import analyze, validator
        result = analyze(model, library=library, filename=filename, style_checks=False)
    except Exception as e:
        return [f"(sysmlpy analyze raised: {e})"]

    out = []
    for issue in result:
        sev = getattr(issue, "severity", "?")
        code = getattr(issue, "code", "?")
        msg = getattr(issue, "message", str(issue))
        el = elem_name(getattr(issue, "element", None))
        ref = getattr(issue, "reference", None)
        tag = f" on '{el}'" if el else ""
        ref_tag = f" (referencing '{ref}')" if ref else ""
        out.append(f"[{sev}] {code}: {msg}{tag}{ref_tag}")

    # IMPROVEMENT 1: Integrate ISQ/Unit validation
    if model:
        try:
            # we attempt to validate quantity/unit conformance for the model
            # validator.validate_quantity_conformance is the primary entry point
            unit_issues = validator.validate_quantity_conformance(model)
            for ui in unit_issues:
                # unit_issues may be strings or objects depending on version
                msg = str(ui)
                out.append(f"[error] UNIT_CONFORMANCE: {msg}")
        except Exception as e:
            # Unit validation might fail if model is partially broken
            out.append(f"[warning] (unit validation skipped: {e})")

    return out


def check_combined(files: list[str], library) -> list[str]:
    """Multi-file semantic check — load_files WITHOUT library, analyze WITH."""
    try:
        from sysmlpy import load_files, analyze
        model = load_files(files)
    except Exception as e:
        return [f"(sysmlpy load_files raised: {e})"]
    return check_semantic(model, None, library)


def check_combined_advanced(files: list[str], library) -> list[str]:
    """Multi-file semantic check using load_with_dependencies."""
    try:
        from sysmlpy import load_with_dependencies, analyze
        # IMPROVEMENT 2: Load with dependencies for better project resolution
        model = load_with_dependencies(files)
    except Exception as e:
        return [f"(sysmlpy load_with_dependencies raised: {e})"]
    return check_semantic(model, None, library)


def check_style(style_cmd: list[str], file: str, ignore: list[str]) -> tuple[list[str], bool]:
    cmd = style_cmd + ["check"]
    if ignore:
        cmd += ["--ignore", ",".join(ignore)]
    cmd += [file]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as e:
        return [f"(sysml-style failed to run: {e})"], False
    lines: list[str] = []
    any_fixable = False
    for line in (r.stdout + r.stderr).splitlines():
        line = line.strip()
        if not line:
            continue
        m = STYLE_LINE.match(line)
        if m:
            ln, col, code, msg = m.group(2), m.group(3), m.group(4), m.group(5).strip()
            fixable = msg.endswith("[fixable]")
            if fixable:
                any_fixable = True
                msg = msg[: -len("[fixable]")].rstrip()
            lines.append(f"{ln}:{col}: {code} {msg}" + ("  [fixable]" if fixable else ""))
    return lines, any_fixable


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="check_sysml.py",
        description="Check SysML v2 files: syntax + semantic (sysmlpy) and style (sysml-style).",
    )
    ap.add_argument("files", nargs="+", metavar="FILE", help=".sysml or .kerml file(s) to check")
    ap.add_argument("--library", action="append", default=None, metavar="PATH",
                    help="library path(s) for import resolution (repeatable). "
                         "Defaults to the bundled sysmlpy standard library. "
                         "A disk cache is used so the first run scans ~0.6s and "
                         "subsequent runs load instantly. Pass --no-library to disable.")
    ap.add_argument("--no-library", action="store_true",
                    help="disable library import resolution (may produce "
                         "UNDEFINED_SYMBOL false positives for stdlib references)")
    ap.add_argument("--no-style", action="store_true", help="skip sysml-style checks")
    ap.add_argument("--no-semantic", action="store_true", help="skip sysmlpy semantic analysis")
    ap.add_argument("--ignore", action="append", default=None, metavar="CODES",
                    help="comma-separated SML codes to ignore (repeatable; passed to sysml-style)")
    ap.add_argument("--quiet", action="store_true", help="suppress per-file header lines")
    args = ap.parse_args()

    try:
        import sysmlpy  # noqa: F401
    except Exception:
        print("ERROR: sysmlpy is not installed. Run: pip install sysmlpy", file=sys.stderr)
        return 2

    # Determine library paths
    if args.no_library:
        libs = None
    elif args.library:
        libs = args.library
    else:
        bundled = _bundled_library()
        libs = [bundled] if bundled else None

    # Preload library index (disk cache → in-process cache).
    # Only needed for semantic analysis; skip when --no-semantic.
    lib_status = "skipped"
    if libs and not args.no_semantic:
        lib_status = preload_library_index(libs)
        if not args.quiet:
            print(f"[library: {lib_status}, {len(libs)} path(s)]", file=sys.stderr)

    ignore = [c for grp in (args.ignore or []) for c in grp.split(",") if c]

    style_cmd = None if args.no_style else find_sysml_style()
    if not args.no_style and style_cmd is None:
        print("NOTE: sysml-style not found; skipping STYLE layer. Install: pip install sysml-style",
              file=sys.stderr)

    total_err = 0
    total_warn = 0
    total_fixable = False
    file_results: list[tuple[str, dict]] = []

    parseable: list[str] = []
    for path in args.files:
        syntax: list[str] = []
        semantic: list[str] = []
        style: list[str] = []
        fixable_here = False

        text, rerr = read_file(path)
        if text is None:
            syntax.append(f"(could not read file: {rerr})")
            file_results.append((path, {"syntax": syntax, "semantic": semantic, "style": style, "fixable": False}))
            total_err += 1
            continue

        syntax_errs, model = check_syntax(text)
        for e in syntax_errs:
            m = PARSE_ERR.match(e)
            if m:
                syntax.append(f"{m.group(1)}:{m.group(2)}: {m.group(3)}")
            else:
                syntax.append(e)
        if model is not None:
            parseable.append(path)
            if not args.no_semantic and len(args.files) == 1:
                semantic = check_semantic(model, path, libs)

        if style_cmd is not None:
            style, fixable_here = check_style(style_cmd, path, ignore)
            if fixable_here:
                total_fixable = True

        file_results.append((path, {
            "syntax": syntax, "semantic": semantic, "style": style, "fixable": fixable_here,
        }))

    if not args.no_semantic and len(args.files) > 1 and parseable:
        # IMPROVEMENT 2: Use load_with_dependencies for multi-file projects
        combined = check_combined_advanced(parseable, libs)
        file_results.append(("project (combined, cross-file imports)", {
            "syntax": [], "semantic": combined, "style": [], "fixable": False,
        }))

    for path, r in file_results:
        syn, sem, sty = r["syntax"], r["semantic"], r["style"]
        if not syn and not sem and not sty:
            if not args.quiet:
                print(f"== {path} ==")
                print("  OK — no issues")
            continue
        print(f"== {path} ==")
        for s in syn:
            print(f"  SYNTAX    {s}")
            total_err += 1
        for s in sem:
            print(f"  SEMANTIC  {s}")
            if s.startswith("[error]"):
                total_err += 1
            elif s.startswith("[warning]"):
                total_warn += 1
        for s in sty:
            print(f"  STYLE     {s}")
            total_err += 1

    print("== summary ==")
    print(f"  errors: {total_err}  warnings: {total_warn}")
    if total_fixable:
        print(f"  fixable style issues present — run: sysml-style format {' '.join(args.files)}")
    result = "PASS" if total_err == 0 else "FAIL"
    print(f"RESULT: {result}")
    return 0 if total_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
