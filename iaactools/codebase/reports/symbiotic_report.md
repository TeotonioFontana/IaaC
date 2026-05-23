# Symbiotic Checks — Human Report

- **When**: 2025-11-11 01:15:09Z UTC
- **Root**: `backup_orchestrator_pkg`
- **Package top**: `backup_orchestrator_pkg`
- **Discovered**: 23 .py files
- **Parsed**: 23 modules / 83 functions

> **Status:** ❌ Errors present (CI-blocker). Fix errors first.

## Summary by kind
**Errors:**
- `cross_package_call`: **410**
- `static_key_type`: **1**
- `bouncing_call`: **1**

**Warnings:**
- `arg_docs`: **69**

## Hotspots (functions with most issues)
- `backup_orchestrator_pkg.orchestrator.main` — **28** finding(s)
- `backup_orchestrator_pkg.phases.phase1_init.run` — **20** finding(s)
- `backup_orchestrator_pkg.discovery_ext.discover_environment` — **18** finding(s)
- `backup_orchestrator_pkg.phases.phase3_snapshot.run` — **18** finding(s)
- `backup_orchestrator_pkg.manifest_aggregator.aggregate_manifests` — **17** finding(s)
- `backup_orchestrator_pkg.phases.phase4_manifest.run` — **17** finding(s)
- `backup_orchestrator_pkg.phases.phase2_volume.run` — **16** finding(s)
- `backup_orchestrator_pkg.discovery_multi.discover_environment_multi` — **14** finding(s)
- `backup_orchestrator_pkg.orchestrator.phase0_global_discovery` — **14** finding(s)
- `backup_orchestrator_pkg.discovery_core.discover_cloudformation` — **13** finding(s)
- `backup_orchestrator_pkg.discovery_core.discover_storage` — **13** finding(s)
- `backup_orchestrator_pkg.phases.phase5_upload.run` — **13** finding(s)

### Fix recipe — Rule 3: Static key types
- Ensure the same type per returned key across all returns.
- Prefer consistent empties: lists→`[]`, dicts→`{}`, str→`""`, int→`0`.
- Wrap with `@enveloped(...)` and return payload dicts only.

### Fix recipe — Rule 4: Cross-package calls
- Move shared helpers into `common/` and import from there; or
- Use relative imports if both modules belong to the same package; or
- Inline tiny helpers (last resort).

### Fix recipe — Rule 5: Bouncing calls (A↔B)
- Extract shared logic into a third function, then call that from A and B.
- Alternatively, make one a coordinator and the other a pure helper.

### Fix recipe — Rule 2: Argument docs + ranges
- Add docstrings with an Args section and explicit bounds/choices/patterns.
- If public/CLI-facing, add a schema in `@enveloped(...)` to enforce at runtime.

---
_Tip: Fix errors first, then rerun. Aim for 0 warnings. Keep JSON for CI; share this Markdown with the human reviewer._
