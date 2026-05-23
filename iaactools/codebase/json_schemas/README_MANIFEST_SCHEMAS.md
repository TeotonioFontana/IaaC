# 🧾 IaaC Recovery Suite — Manifest Schema Reference (v1.0.0)

## 1. Overview

The **IaaC Recovery Suite** relies on a layered set of JSON manifests that document every aspect of an AWS recovery environment.  
Each manifest corresponds to a structural layer of recoverability — from low-level infrastructure to human operational context.  
Together, they define the **Recovery Intelligence Model** that powers the audit and restoration pipeline.

> **Core principle:** Recovery is not only about restoring bits — it is about restoring context, consistency, and compliance.

---

## 2. Manifest Architecture

Each manifest file adheres to **JSON Schema Draft-07** and includes a shared metadata block:

```json
"meta": {
  "schema_version": "1.0.0",
  "owner": "IaaC Recovery Suite",
  "generated_at": "2025-11-02T14:30:00Z"
}
```

### Relationship Graph

```
┌─────────────────────────────────────┐
│ organizations_manifest.json         │
│   • Defines org structure, OUs, SCPs│
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│ account_manifest.json               │
│   • Captures account-level settings │
│   • IAM, quotas, compliance posture  │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│ infrastructure_manifest.json        │
│   • Volumes, snapshots, S3 artifacts│
│   • Physical recovery data          │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│ environment_manifest.json           │
│   • IaC fingerprints, dependencies  │
│   • Operator notes & context        │
└─────────────────────────────────────┘
```

### Validation Sequence (Audit Orchestrator)

| Phase | Manifest | Primary Purpose |
|-------|-----------|-----------------|
| 2 | `infrastructure_manifest.json` | Validate physical backup artifacts (volumes, snapshots, S3 objects) |
| 3 | `account_manifest.json` | Validate account quotas, IAM, and guardrails consistency |
| 4 | `organizations_manifest.json` | Cross-check org-level policy inheritance and SCPs |
| 5 | `environment_manifest.json` | Confirm reproducibility and document operational context |

---

## 3. Design Philosophy

### 🧩 Version-Agnostic by Design
Manifests use stable key structures — new AWS services or fields can be appended without breaking existing validations.  
Backups remain valid even after years of platform evolution.

### 🔍 Over-Documentation Preferred
Each manifest is verbose by design. Missing or “unimportant” fields are still captured to prevent recovery dead-ends.

### 🛡️ Redundancy Encouraged
Some data overlaps across manifests intentionally:
- **AccountId** appears in all relevant manifests
- **Region** appears in `infrastructure` and `environment`
- **DelegatedAdmin** data mirrors both `organizations` and `account`

This duplication ensures survivability even if one manifest is lost or corrupted.

---

## 4. Schema Summary

| Schema | Core Object | Purpose | Key Sections |
|--------|--------------|----------|---------------|
| `infrastructure_manifest_schema.json` | EC2 + S3 assets | Verifies all recoverable components exist | Volumes, Snapshots, S3Artifacts |
| `account_manifest_schema.json` | Account metadata | Validates identity, quotas, and security | Quotas, Security, Networking |
| `organizations_manifest_schema.json` | Org hierarchy | Ensures correct OU, SCP, and delegation setup | Accounts, SCPs, DelegatedServices |
| `environment_manifest_schema.json` | Operational context | Reconstructs workload state and IaC fingerprints | Workloads, IaC, Dependencies |

---

## 5. Schema Interoperability Rules

1. **Cross-field Validation:**  
   The audit orchestrator enforces consistency across manifests. Example:
   ```python
   assert infra["AccountId"] == account["AccountId"]
   ```

2. **Optional Linking:**  
   Each manifest may contain references to others through:
   ```json
   "LinkedManifests": ["account_manifest.json", "organizations_manifest.json"]
   ```

3. **AI Policy Checks (Phase 8):**  
   During AI Sentinel validation, all manifests are analyzed together to ensure compliance with:
   - AWS best practices (as fetched from the latest docs)
   - Security policy evolution
   - IAM and encryption alignment across resources

---

## 6. Example Directory Layout

```
/results/audit/20251102T140000Z/
 ├── manifests/
 │   ├── infrastructure_manifest.json
 │   ├── account_manifest.json
 │   ├── organizations_manifest.json
 │   └── environment_manifest.json
 ├── audit.log
 ├── audit_result.json
 └── audit_report.pdf
```

---

## 7. Future Extensions

| Area | Planned Addition | Notes |
|------|------------------|-------|
| Multi-region | Introduce `replication_manifest.json` | Captures cross-region snapshot copies |
| AI-driven schema evolution | Use GPT-based validator in Phase 8 | Suggests missing compliance fields |
| Cost footprint manifest | `billing_manifest.json` | Tracks recovery cost projection |

---

## 8. Validation Example (CLI)

```bash
python -m iaactools.codebase.tools.json_validate   --schema json_schemas/infrastructure_manifest_schema.json   --input results/audit/20251102T140000Z/manifests/infrastructure_manifest.json
```

---

## 9. Appendix — Shared Metadata Template

```json
{
  "meta": {
    "schema_version": "1.0.0",
    "owner": "IaaC Recovery Suite",
    "generated_at": "2025-11-02T14:00:00Z",
    "tool_version": "4.0.0-alpha1",
    "purpose": "Disaster recovery verification"
  }
}
```
