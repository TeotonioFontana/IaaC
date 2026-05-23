#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 symbiotic_checks.py — Static guardrails for Symbiotic rules (v1.3)
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / backup_orchestrator
 Purpose............: Fast, no-build static checks to flag Symbiotic-rule
                      non-compliance in Python packages.

 What this lints (best-effort heuristics):
   (2) Argument docs exist and mention ranges/choices/patterns
   (3) Per-key return types stay consistent within each function
   (4) No cross-package calls (except to a package literally named "common")
   (5) No A↔B bouncing (mutual calls between two functions)

 Outputs:
   • STDERR: human run heading (quick context)
   • STDOUT: machine-readable JSON report (backward compatible)
   • Files (optional):
       --out-json   : write the JSON report to a path
       --out-report : write a human Markdown report to a path

 Exit codes (CI-friendly):
   0 = clean
   1 = warnings only (arg docs heuristic)
   2 = errors found (type inconsistency, cross-package call, bouncing)

 Usage:
   python tools/symbiotic_checks.py \
     --root backup_orchestrator_pkg \
     --pkg-top backup_orchestrator_pkg \
     --out-json reports/symbiotic_report.json \
     --out-report reports/symbiotic_report.md

 Limitations:
   - Heuristics, not a type checker. False positives/negatives can happen.
   - Only inspects *literal dict* returns for key/type consistency (no dataflow).
   - Call graph is shallow (name/attribute resolution only).
===============================================================================
"""
import ast
import sys
import json
import re
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional, Any
from datetime import datetime

# Minimal hints we look for inside docstrings to count as "args are documented".
ARG_DOC_HINTS = ("Args:", "Arguments:", ":param", "@param")


def module_name_from_path(path: Path, pkg_top: str) -> str:
    """Convert a filesystem path into a dotted module name anchored at pkg_top."""
    parts = list(path.with_suffix("").parts)  # drop ".py"
    if pkg_top in parts:
        i = parts.index(pkg_top)
        parts = parts[i:]
    return ".".join(parts)


def top_package_of(dotted: str) -> str:
    """Return top-level package segment of a dotted name ('a.b.c' -> 'a')."""
    return dotted.split(".")[0] if dotted else ""


class FuncRecord:
    """
    Lightweight record describing a discovered function/method.

    Attributes:
      module   : dotted module name
      qualname : dotted qualified name (module[.Class].func)
      doc      : function docstring (or empty)
      args     : positional arg names (ids only; no types)
      returns  : list of (key, type_name, lineno) extracted from *literal dict* returns
      calls    : set of *best-effort* callee names (dotted-ish strings)
    """
    def __init__(self, module: str, qualname: str):
        self.module = module
        self.qualname = qualname
        self.doc: str = ""
        self.args: List[str] = []
        self.returns: List[Tuple[str, str, int]] = []
        self.calls: Set[str] = set()


class ModuleInfo:
    """
    Info captured for a parsed module.

    Attributes:
      path         : filesystem path
      module       : dotted module name
      tree, src    : AST and raw source
      imports      : map(alias -> top package) for 'import X as alias'
      from_imports : map(name -> top package) for 'from pkg.mod import name'
    """
    def __init__(self, path: Path, pkg_top: str):
        self.path = path
        self.module = module_name_from_path(path, pkg_top)
        self.tree: Optional[ast.AST] = None
        self.src: Optional[str] = None
        self.imports: Dict[str, str] = {}
        self.from_imports: Dict[str, str] = {}


class Analyzer(ast.NodeVisitor):
    """
    AST visitor that extracts:
      - function structure (docstring, args)
      - literal dict return shapes (for per-key type consistency)
      - rough call graph edges
    """
    def __init__(self, src: str, module: str, imports: Dict[str, str], from_imports: Dict[str, str]):
        self.src = src
        self.module = module
        self.imports = imports
        self.from_imports = from_imports
        self.func_stack: List[FuncRecord] = []
        self.funcs: List[FuncRecord] = []
        self.class_stack: List[str] = []

    # ---------- Function & class discovery ----------

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Enter a function, collect doc + arg names, then walk its body."""
        qual = f"{self.module}.{node.name}" if not self.class_stack else f"{self.module}.{self.class_stack[-1]}.{node.name}"
        fr = FuncRecord(self.module, qual)
        fr.doc = ast.get_docstring(node) or ""
        fr.args = [a.arg for a in node.args.args]
        self.func_stack.append(fr)
        self.generic_visit(node)
        self.func_stack.pop()
        self.funcs.append(fr)

    visit_AsyncFunctionDef = visit_FunctionDef  # treat async the same

    def visit_ClassDef(self, node: ast.ClassDef):
        """Track class nesting so qualified names include the class."""
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    # ---------- Return dict shape capture ----------

    def visit_Return(self, node: ast.Return):
        """
        If returning a *literal dict*, record each literal key and the AST node type
        of the corresponding value. This is enough to detect per-key type flips
        across different return statements within the same function.
        """
        if not self.func_stack:
            return
        if isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                key = None
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    key = k.value
                elif isinstance(k, ast.Str):  # Py<3.8 legacy
                    key = k.s
                if key is None:
                    continue
                type_name = type(v).__name__  # *AST* node type, not runtime type
                self.func_stack[-1].returns.append((key, type_name, node.lineno))
        self.generic_visit(node)

    # ---------- Call graph (best-effort) ----------

    def visit_Call(self, node: ast.Call):
        """
        Try to infer a dotted-ish name for the callee.
        This is shallow but good enough for cross-package and A↔B checks.
        """
        if not self.func_stack:
            return self.generic_visit(node)
        name = self._qualname_from_call(node.func)
        if name:
            self.func_stack[-1].calls.add(name)
        self.generic_visit(node)

    def _qualname_from_call(self, func_node: ast.AST) -> Optional[str]:
        """
        Turn a call target AST node into a dotted name when possible.

        Cases:
          - bare name: foo() → "module.foo" or "top.name" if imported-from
          - attribute chain: x.y.z() → try to map 'x' to an imported top package
        """
        # foo(...)
        if isinstance(func_node, ast.Name):
            n = func_node.id
            if n in self.from_imports:
                return f"{self.from_imports[n]}.{n}"   # from pkg.mod import n  -> "pkg"
            return f"{self.module}.{n}"                # local symbol fallback

        # pkg.mod.func(...) or alias.attr(...)
        if isinstance(func_node, ast.Attribute):
            parts = []
            cur = func_node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                base = cur.id
                parts.append(base)
                parts = list(reversed(parts))
                dotted = ".".join(parts)
                if base in self.imports:
                    # If 'base' came from 'import X as base', rewrite to top package
                    top = self.imports[base]
                    dotted = ".".join([top] + parts[1:])
                return dotted
        return None


def parse_module(path: Path, pkg_top: str) -> ModuleInfo:
    """Read a Python file, parse AST, and harvest import context (no code execution)."""
    mi = ModuleInfo(path, pkg_top)
    src = path.read_text(encoding="utf-8", errors="ignore")
    mi.src = src
    mi.tree = ast.parse(src, filename=str(path))
    for node in ast.walk(mi.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mi.imports[alias.asname or alias.name] = top_package_of(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            for alias in node.names:
                mi.from_imports[alias.asname or alias.name] = top_package_of(base)
    return mi


def scan(root: Path, pkg_top: str):
    """
    Recursively find Python files under 'root', parse each, and collect function data.
    Returns:
      modules: [ModuleInfo]
      funcs  : [FuncRecord]
      pyfiles: [Path]
    """
    pyfiles = [p for p in root.rglob("*.py") if not p.name.startswith(".")]
    modules: List[ModuleInfo] = []
    funcs: List[FuncRecord] = []
    for p in pyfiles:
        mi = parse_module(p, pkg_top)
        modules.append(mi)
        an = Analyzer(mi.src or "", mi.module, mi.imports, mi.from_imports)
        an.visit(mi.tree)  # type: ignore
        funcs.extend(an.funcs)
    return modules, funcs, pyfiles


# ----------------------------- Rule detectors --------------------------------

def detect_arg_docs(funcs: List[FuncRecord]) -> List[Dict[str, Any]]:
    """
    Rule (2): Argument docs + ranges/choices/patterns must be present.

    Heuristic:
      - If a function has any positional args:
          * docstring must contain one of ARG_DOC_HINTS, and
          * mentions of "min|max|range|choice(s)|pattern" somewhere.
      - Also checks that each arg name appears somewhere in the docstring.
    """
    issues = []
    for f in funcs:
        if not f.args:
            continue
        doc = f.doc or ""
        missing = [a for a in f.args if a not in doc]
        has_hint = any(h in doc for h in ARG_DOC_HINTS)
        has_range = bool(re.search(r"\b(min|max|range|choices?|pattern)\b", doc, re.IGNORECASE))
        if missing or not has_hint or not has_range:
            issues.append({
                "kind": "arg_docs",
                "function": f.qualname,
                "missing_args": missing,
                "has_args_section": has_hint,
                "has_range_hint": has_range,
                "message": "Argument documentation incomplete (names + ranges/choices/patterns required)."
            })
    return issues


def detect_static_key_types(funcs: List[FuncRecord]) -> List[Dict[str, Any]]:
    """
    Rule (3): Per-key types must be consistent across returns within a single function.

    Implementation:
      - Looks only at *literal dict* returns and records the AST node class for values.
      - If the same key appears with different AST node classes across returns, flag it.
    """
    issues = []
    for f in funcs:
        seen: Dict[str, str] = {}
        for key, tname, lineno in f.returns:
            if key in seen and seen[key] != tname:
                issues.append({
                    "kind": "static_key_type",
                    "function": f.qualname,
                    "key": key,
                    "types": [seen[key], tname],
                    "lineno": lineno,
                    "message": f"Key '{key}' has inconsistent return value types within function."
                })
            else:
                seen[key] = tname
    return issues


def detect_cross_package_calls(mods: List[ModuleInfo], funcs: List[FuncRecord], pkg_top: str) -> List[Dict[str, Any]]:
    """
    Rule (4): No cross-package calls, except to a package literally named 'common'.
    """
    issues = []
    for f in funcs:
        my_top = f.module.split(".")[0]
        for callee in f.calls:
            top = callee.split(".")[0] if callee else ""
            if not top:
                continue
            if top not in {pkg_top, "common", my_top}:
                issues.append({
                    "kind": "cross_package_call",
                    "function": f.qualname,
                    "callee": callee,
                    "message": f"Cross-package call to '{callee}' is forbidden (only 'common' allowed)."
                })
    return issues


def detect_bouncing_calls(funcs: List[FuncRecord]) -> List[Dict[str, Any]]:
    """
    Rule (5): No bouncing (mutual) calls: if A calls B, then B must not call A.
    """
    issues = []
    callmap = {f.qualname: set(f.calls) for f in funcs}

    def fkey(q: str) -> str:
        return q.split(".")[-1]  # compare just by the function name

    for a in callmap:
        for b in list(callmap[a]):
            b_funcs = [f.qualname for f in funcs if fkey(f.qualname) == fkey(b)]
            for bf in b_funcs:
                if a == bf:
                    continue
                if any(fkey(x) == fkey(a) for x in callmap.get(bf, set())):
                    issues.append({
                        "kind": "bouncing_call",
                        "a": a,
                        "b": bf,
                        "message": f"Mutual call detected between '{a}' and '{bf}'."
                    })

    # Deduplicate symmetric pairs (A,B) and (B,A)
    dedup = []
    seen = set()
    for it in issues:
        key = tuple(sorted([it["a"], it["b"]]))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(it)
    return dedup


# ----------------------------- Reporting helpers -----------------------------

def _print_heading(root: Path, pkg_top: str, py_count: int, mod_count: int, fn_count: int):
    """Human-friendly run heading to STDERR (keeps STDOUT clean for JSON)."""
    print(
        f"[Symbiotic Checks] root={root}  pkg_top={pkg_top}\n"
        f"  discovered .py files: {py_count}\n"
        f"  parsed modules/functions: {mod_count}/{fn_count}",
        file=sys.stderr,
    )
    if py_count == 0:
        print(
            "  NOTE: No Python files found under --root.\n"
            "        • Check the path (does it point to the package directory?).\n"
            "        • Are your sources under a deeper folder (e.g., iaactools/codebase/...)?\n"
            "        • Do files use a different extension or are they excluded?\n"
            "        • Permissions or VCS ignore filters hiding files?\n",
            file=sys.stderr,
        )


def _count_by(items: List[Dict[str, Any]], field: str) -> List[Tuple[str, int]]:
    """Return list of (value, count) for a field, sorted desc by count."""
    from collections import Counter
    c = Counter([it.get(field, "") for it in items])
    return sorted(c.items(), key=lambda kv: kv[1], reverse=True)


def _hotspots(errors: List[Dict[str, Any]], warnings: List[Dict[str, Any]], top_n: int = 12) -> List[Tuple[str, int]]:
    """Return top-N functions by total issues (errors + warnings)."""
    from collections import Counter
    all_items = errors + warnings
    c = Counter([it.get("function", it.get("a", "")) for it in all_items if it.get("function") or it.get("a")])
    return c.most_common(top_n)


def _write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _render_markdown_report(root: Path,
                            pkg_top: str,
                            report: Dict[str, Any]) -> str:
    """
    Build a concise, human-friendly Markdown report highlighting:
      - run context & stats
      - counts by kind (errors/warnings)
      - hotspots (top offender functions)
      - quick fix recipes per rule when issues exist
    """
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    stats = report.get("stats", {})
    errors = report.get("errors", [])
    warnings = report.get("warnings", [])

    # Summaries
    err_counts = _count_by(errors, "kind")
    warn_counts = _count_by(warnings, "kind")
    hot = _hotspots(errors, warnings, top_n=12)

    lines: List[str] = []
    lines.append(f"# Symbiotic Checks — Human Report")
    lines.append("")
    lines.append(f"- **When**: {ts} UTC")
    lines.append(f"- **Root**: `{root}`")
    lines.append(f"- **Package top**: `{pkg_top}`")
    lines.append(f"- **Discovered**: {stats.get('py_files', 0)} .py files")
    lines.append(f"- **Parsed**: {stats.get('modules', 0)} modules / {stats.get('functions', 0)} functions")
    lines.append("")

    # Status line
    if errors:
        lines.append("> **Status:** ❌ Errors present (CI-blocker). Fix errors first.")
    elif warnings:
        lines.append("> **Status:** ⚠️ Warnings only (docs/ranges).")
    else:
        lines.append("> **Status:** ✅ Clean (no issues).")
    lines.append("")

    # Counts
    lines.append("## Summary by kind")
    if not errors and not warnings:
        lines.append("_No issues found._")
    else:
        if errors:
            lines.append("**Errors:**")
            for k, n in err_counts:
                lines.append(f"- `{k}`: **{n}**")
        if warnings:
            if errors:
                lines.append("")  # spacer
            lines.append("**Warnings:**")
            for k, n in warn_counts:
                lines.append(f"- `{k}`: **{n}**")
    lines.append("")

    # Hotspots
    if hot:
        lines.append("## Hotspots (functions with most issues)")
        for fn, n in hot:
            lines.append(f"- `{fn}` — **{n}** finding(s)")
        lines.append("")

    # Quick recipes (only include sections relevant to current issues)
    if any(it.get("kind") == "static_key_type" for it in errors):
        lines.append("### Fix recipe — Rule 3: Static key types")
        lines.append("- Ensure the same type per returned key across all returns.")
        lines.append("- Prefer consistent empties: lists→`[]`, dicts→`{}`, str→`\"\"`, int→`0`.")
        lines.append("- Wrap with `@enveloped(...)` and return payload dicts only.")
        lines.append("")

    if any(it.get("kind") == "cross_package_call" for it in errors):
        lines.append("### Fix recipe — Rule 4: Cross-package calls")
        lines.append("- Move shared helpers into `common/` and import from there; or")
        lines.append("- Use relative imports if both modules belong to the same package; or")
        lines.append("- Inline tiny helpers (last resort).")
        lines.append("")

    if any(it.get("kind") == "bouncing_call" for it in errors):
        lines.append("### Fix recipe — Rule 5: Bouncing calls (A↔B)")
        lines.append("- Extract shared logic into a third function, then call that from A and B.")
        lines.append("- Alternatively, make one a coordinator and the other a pure helper.")
        lines.append("")

    if any(it.get("kind") == "arg_docs" for it in warnings):
        lines.append("### Fix recipe — Rule 2: Argument docs + ranges")
        lines.append("- Add docstrings with an Args section and explicit bounds/choices/patterns.")
        lines.append("- If public/CLI-facing, add a schema in `@enveloped(...)` to enforce at runtime.")
        lines.append("")

    # Empty diagnostics
    if "diagnostics" in report:
        d = report["diagnostics"]
        lines.append("## Diagnostics")
        lines.append(f"- root_exists: **{d.get('root_exists')}**")
        lines.append(f"- root_is_dir: **{d.get('root_is_dir')}**")
        lines.append(f"- hint: {d.get('hint')}")
        lines.append("")

    # Optional tail with next steps
    lines.append("---")
    lines.append("_Tip: Fix errors first, then rerun. Aim for 0 warnings. Keep JSON for CI; share this Markdown with the human reviewer._")
    lines.append("")
    return "\n".join(lines)


# ----------------------------- CLI Entrypoint --------------------------------

def main():
    """
    CLI wrapper: scans, runs detectors, prints JSON, writes optional files, sets exit code.

    Flags:
      --root        : Path to the package directory to scan (default: ./backup_orchestrator_pkg)
      --pkg-top     : The top-level package name to consider “local” (default: backup_orchestrator_pkg)
      --out-json    : (optional) Path to write the JSON report file
      --out-report  : (optional) Path to write a human-friendly Markdown report
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(".") / "backup_orchestrator_pkg"))
    ap.add_argument("--pkg-top", default="backup_orchestrator_pkg")
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-report", default=None)
    args = ap.parse_args()

    root = Path(args.root)
    pkg_top = args.pkg_top

    modules, funcs, pyfiles = scan(root, pkg_top)

    # Human heading (stderr)
    _print_heading(root, pkg_top, len(pyfiles), len(modules), len(funcs))

    warnings: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    # Warnings: doc coverage heuristic (rule 2).
    warnings.extend(detect_arg_docs(funcs))

    # Errors: actual non-compliance (rules 3–5).
    errors.extend(detect_static_key_types(funcs))
    errors.extend(detect_cross_package_calls(modules, funcs, pkg_top))
    errors.extend(detect_bouncing_calls(funcs))

    report: Dict[str, Any] = {
        "root": str(root.resolve()),
        "stats": {"py_files": len(pyfiles), "modules": len(modules), "functions": len(funcs)},
        "warnings": warnings,
        "errors": errors,
    }

    # Enrich with diagnostics when nothing was found
    if len(pyfiles) == 0:
        report["diagnostics"] = {
            "root_exists": root.exists(),
            "root_is_dir": root.is_dir(),
            "hint": "No *.py files under --root. Verify the path and package location.",
        }

    # 1) Print JSON to STDOUT (backward compatibility)
    print(json.dumps(report, indent=2))

    # 2) Optional: write JSON to file
    if args.out_json:
        out_json = Path(args.out_json)
        try:
            _write_text(out_json, json.dumps(report, indent=2))
            print(f"[Symbiotic Checks] Wrote JSON report → {out_json}", file=sys.stderr)
        except Exception as e:
            print(f"[Symbiotic Checks] Failed writing JSON report: {e}", file=sys.stderr)

    # 3) Optional: write human-friendly Markdown report
    if args.out_report:
        out_report = Path(args.out_report)
        try:
            md = _render_markdown_report(root, pkg_top, report)
            _write_text(out_report, md)
            print(f"[Symbiotic Checks] Wrote human report → {out_report}", file=sys.stderr)
        except Exception as e:
            print(f"[Symbiotic Checks] Failed writing human report: {e}", file=sys.stderr)

    # Exit discipline (CI-friendly).
    if errors:
        sys.exit(2)
    if warnings:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
