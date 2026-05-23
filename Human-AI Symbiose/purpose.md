# Purpose

> One-page statement of **objective and scope**. Keep it crisp; this guides both humans and the checker.

## Project Overview
- **Project name**: {PROJECT_NAME}
- **Owner / Architect**: {OWNER_OR_TEAM}
- **Effective date**: 2025-11-12
- **Status**: Draft | Stable

## Objective (single sentence)
Describe the core outcome in one sentence. *Example:* “Provide a codemod and checker that enforce envelope and contract rules across Python projects.”

## Outcomes (measurable)
- O1: {MEASURABLE_OUTCOME_1}
- O2: {MEASURABLE_OUTCOME_2}
- O3: {MEASURABLE_OUTCOME_3}

## Scope
### In-Scope
- {IN_SCOPE_ITEM_1}
- {IN_SCOPE_ITEM_2}
- {IN_SCOPE_ITEM_3}

### Out-of-Scope
- {OUT_OF_SCOPE_ITEM_1}
- {OUT_OF_SCOPE_ITEM_2}
- {OUT_OF_SCOPE_ITEM_3}

## Assumptions & Dependencies
- Assumptions: {ASSUMPTION_1}, {ASSUMPTION_2}
- External dependencies: {SERVICE_OR_LIB_1}, {SERVICE_OR_LIB_2}

## Constraints
- Technical: {PYTHON_VERSION}, packaging via `pyproject.toml`, CI on GitHub Actions.
- Regulatory / Compliance: {COMPLIANCE_OR_POLICY}
- Performance / SLAs: {SLA_OR_LATENCY}

## Interfaces & Entry Points (Boundaries)
List public entry points (CLI commands, API endpoints, scheduled jobs). For each, define the envelope and schemas.

| Name | Kind (CLI/API/Job) | Module.fn | Schema ref | Envelope | Owner |
|------|---------------------|-----------|------------|----------|-------|
| `sym-check` | CLI | `symbiotic_devkit.cli.main:cmd_check` | `.symbiotic.yaml#checks` | Yes | Platform |

## Data Model & Contracts (Stable)
- Payload keys and their **stable types** (Rule R-300).
- Example payloads for success/invalid/error.
- PII/Secrets handling (masking, never logged).

## Operational Model
- Environments: Dev / CI / Prod
- Logging: boundary-only, context-rich; exceptions mapped to envelope.
- Observability: metrics, reports uploaded to `reports/` in CI.
- Rollout: mirroring mode first (`sym-decorate --write-mode mirror`), then selective merge.

## Risks & Mitigations
- Risk: {RISK} → Mitigation: {MITIGATION}

## Success Criteria & KPIs
- {KPI_1} (target)
- {KPI_2} (target)
- {KPI_3} (target)

## Stakeholders & Roles
- Architect: {NAME} — decides purpose/scope.
- AI (ChatGPT): code generation under constraints.
- Maintainers: {TEAM} — reviews, releases.

## Versioning & Change Control
- SemVer for releases; rule changes bump minor/major accordingly.
- Changes proposed via short RFC in `docs/rfcs/` and PR.

## Glossary
- **Boundary function** — public entrypoint using the envelope.
- **Envelope** — standardized outcome wrapper around a payload dict.
- **Bounce** — A↔B mutual calls in a module.
