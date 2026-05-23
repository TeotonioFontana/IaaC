# Symbiotic Guardrails & Codemod (backup_orchestrator)

This section documents the Symbiotic AI–Human development guardrails for **IaaC Tools / backup_orchestrator**, and how to apply them quickly with our codemod + checker.

## Why this exists
Backups, recovery, and AWS automation are high‑blast‑radius domains. Predictable function contracts, strict input validation, and deterministic refactors reduce risk and MTTR.

## Result envelope (boundary functions)
All boundary functions must return a single **envelope dict** with fixed keys and static types per key. Validation happens up front via `@enveloped(schema=...)`.

- Deterministic shape, no `None` vs list flip‑flops.
- Clear `status/ok` and `error/exception` fields for operability.
- One place to perform argument validation and range/pattern checks.

> Leaf helpers can return raw payloads; boundary callers enforce the envelope.

## Static checks (tools/symbiotic_checks.py)
Run fast, no‑build checks to flag Symbiotic rule violations.

- **Rules covered**
  - (2) Args docs must exist and mention ranges/choices/patterns (warning)
  - (3) Static per‑key return types within each function (error)
  - (4) No cross‑package calls (except package literally named `common`) (error)
  - (5) No bouncing A↔B calls (error)

- **Dual output**
  - **STDERR**: human heading
  - **STDOUT**: JSON report for tooling
  - Optional files: `--out-json`, `--out-report` (Markdown for humans)

```bash
python tools/symbiotic_checks.py   --root backup_orchestrator_pkg   --pkg-top backup_orchestrator_pkg   --out-json reports/symbiotic_report.json   --out-report reports/symbiotic_report.md
```

**Exit codes:** 0=clean, 1=warnings only, 2=errors present.

## Codemod: tools/decorate_enforcer.py
Automates the boring parts: inserts the import and decorates boundary functions with `@enveloped(schema=...)`, preserving formatting/comments (LibCST).

### This simple pass
- Inserts `from backup_orchestrator_pkg.result_envelope import enveloped` (once).
- Decorates functions whose names look like boundaries (`run|execute|perform|backup|restore|handle|process`).
- Skips already-decorated ones.
- Next, let AI (me) refine each function’s **schema** and **docstring** — that’s the part machines can’t infer perfectly.

### Workflow I recommend
1) **Codemod pass** (deterministic plumbing).  
2) **AI pass** (schemas, ranges, patterns, choices; normalize return payloads).  
3) **Re-run checks** → errors must be 0; warnings trend to 0.  
4) **Commit** with diff & report.

### Schema generation modes
`decorate_enforcer.py` supports `--schema {minimal|hints}`:

- **minimal**: set only `type`, `required`, `default` (simple literals), `nullable` from `Optional[...]`.
- **hints**: adds pragmatic bounds/patterns from names/annotations/defaults:
  - ints: `limit|count|max_items|size` → `min:1`; `retries|timeout` → `min:0`; `port` → `1..65535`
  - strings: `non_empty: True` by default
  - AWS IDs: `^vol-…`, `^snap-…`, `^i-…`, `^ami-…`
  - S3 bucket: `^[a-z0-9][a-z0-9.-]{1,62}$`
  - region: `^[a-z]{2}-[a-z]+-\d$`

```bash
# Minimal schema
python tools/decorate_enforcer.py --root backup_orchestrator_pkg --schema minimal --dry-run

# Heuristic schema
python tools/decorate_enforcer.py --root backup_orchestrator_pkg --schema hints --verbose
```

## CI/Pre-commit
- Gate on `symbiotic_checks.py` (errors block the build; warnings optional).  
- Keep the JSON artifact and the Markdown report as build artifacts.  
- Run codemod in a branch and commit the diff; do **not** run codemod automatically in CI.

---

**TL;DR:** Run codemod → refine schemas/docs → run checks → commit with JSON + MD reports.
