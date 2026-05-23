# Contributing — Symbiotic Rules (backup_orchestrator)

We keep this codebase safe and operable by enforcing a few non‑negotiables. Follow this checklist before opening a PR.

## Core rules
1. **Envelope returns (boundary functions):** Every boundary function is decorated with `@enveloped(schema=...)` and returns a single dict with fixed keys. No ad‑hoc tuples, no mixed types per key across code paths.
2. **Argument docs:** Public functions document *each argument* with allowed ranges/choices/patterns in the docstring `Args:` section.
3. **Static per‑key types:** A given return key must **never** change type between return statements (e.g., `items` is always `list`, never `None`).
4. **No cross‑package calls:** Only call outside your top package if the target is the `common` package.
5. **No bouncing calls:** If `A()` calls `B()`, then `B()` must not call `A()` (extract a third helper `C()` instead).

## Tools you must use
- **Codemod:** `tools/decorate_enforcer.py` (LibCST).  
  - Adds the import and `@enveloped(schema=...)` to boundary functions.
  - Modes: `--schema minimal|hints` (use `hints` to bootstrap sensible constraints).
- **Checker:** `tools/symbiotic_checks.py`.  
  - Outputs JSON (for CI) and optional Markdown (`--out-report`) for humans.

## This simple pass (codemod behavior)
- Inserts `from backup_orchestrator_pkg.result_envelope import enveloped` (once).
- Decorates functions whose names look like boundaries (`run|execute|perform|backup|restore|handle|process`).
- Skips already-decorated ones.
- Next, let AI (me) refine each function’s **schema** and **docstring** — that’s the part machines can’t infer perfectly.

## Workflow I recommend
1) **Codemod pass** (deterministic plumbing).  
2) **AI pass** (schemas, ranges, patterns, choices; normalize return payloads).  
3) **Re-run checks** → errors must be 0; warnings trend to 0.  
4) **Commit** with diff & report.

## PR checklist
- [ ] Boundary functions are decorated with `@enveloped(schema=...)`.
- [ ] Docstrings include `Args:` with ranges/choices/patterns.
- [ ] No cross‑package calls (except `common`).
- [ ] No A↔B bouncing. Shared logic extracted.
- [ ] `symbiotic_checks.py` returns **exit 0** (or 1 only if warnings are temporarily tolerated).
- [ ] JSON report attached; Markdown report included in the PR description.
- [ ] Tests updated/added where behavior changed.

## Tips
- Tune the codemod with `--name-pattern` to catch your module’s naming style.
- Keep helpers small and pure; put validation at the boundary.
- If a constraint is uncertain, pick a safe default and leave a `# TODO(schema)` note. The AI pass will refine it.
