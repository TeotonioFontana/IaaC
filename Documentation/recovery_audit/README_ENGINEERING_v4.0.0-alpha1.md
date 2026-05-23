# IaaC Recovery Suite — Recovery Audit Package  
### Engineering Overview — Version 4.0.0-alpha1  
*(UTF-8 encoded, canonical engineering reference)*

---

## 1. Purpose
The Recovery Audit Package verifies **backup integrity** and **recovery viability** across AWS infrastructure.  
It ensures that all data, manifests, and metadata are both **present** and **recoverable** — not just stored.  
The audit is executed as a pipeline of 8 sequential phases, from raw S3 discovery to AI-assisted compliance validation.

---

## 2. Architecture and Directory Layout
```
iaactools/codebase/recovery_audit_pkg/
│
├── audit_config_validator.py
├── logger_utils.py
├── orchestrator.py
│
├── phase1_discovery.py
├── phase2_manifest_check.py
├── phase3_volume_verification.py
├── phase4_snapshot_verification.py
├── phase5_cross_validation.py
├── phase6_orphan_detection.py
├── phase7_recovery_simulation.py
└── phase8_ai_policy_check.py
```
Auxiliary components:
```
/results/audit/{run_id}/          → per-run output folder  
/reporting/pdf/                   → generated PDF reports  
mock_aws_tests.py                 → offline simulation harness
```

---

## 3. Configuration Schema
All configuration files follow the strict schema enforced by  
`audit_config_validator.py`. CLI flags override file parameters at runtime.

```yaml
audit:
  profile: default
  region: us-east-1
  bucket: my-company-backups
  run_id: 20251101T235959Z
  simulate: false
  report_path: ./results/audit.json
prefixes:
  base: iaac/backups
  manifest: iaac/backups/runs/{run_id}/manifest
policy:
  validate_snapshots: true
  detect_orphans: true
report:
  s3_upload_prefix: recovery_audit
logging:
  format: text        # text | json | both
  level: DEBUG        # DEBUG | INFO | WARNING | ERROR
```

**CLI Example**
```bash
python3 -m iaactools.codebase.recovery_audit_pkg.orchestrator   --config conf/audit_demo.yaml   --run-id 20251101T235959Z   --simulate   --verify-snapshots   --verbose
```

---

## 4. Phase Map and Responsibilities

| Phase | Module | Primary Role | Key Outputs |
|-------|---------|---------------|--------------|
| 1 | `phase1_discovery` | Enumerate all S3 prefixes and folder structure | Structure map (`discover.json`) |
| 2 | `phase2_manifest_check` | Validate and parse manifest.json | `ManifestData` dict |
| 3 | `phase3_volume_verification` | Check that every volume in manifest exists | Volume status table |
| 4 | `phase4_snapshot_verification` | Verify EC2 snapshots via `describe_snapshots()` | Snapshot consistency map |
| 5 | `phase5_cross_validation` | Cross-check manifest with logs/indexes | Inconsistency report |
| 6 | `phase6_orphan_detection` | Find unreferenced or stale S3 objects | Orphan list |
| 7 | `phase7_recovery_simulation` | Simulate recovery logic (dry-run) | Expected allocations summary |
| 8 | `phase8_ai_policy_check` | Use OpenAI Sentinel to detect AWS policy or API changes | AI compliance summary |

Each phase writes structured JSON fragments and logs to `/results/audit/{run_id}/`.

---

## 5. Logging, Console, and Report Outputs
**Console:**
- ANSI colorized logs (always enabled)  
- Supports text, JSON, or dual-output via config flag  

**Files:**
```
/results/audit/{run_id}/audit.log              → unified log
/results/audit/{run_id}/final_audit_result.json → consolidated results
/reporting/pdf/{run_id}/audit_report.pdf        → PDF summary
```

**Log Levels**
| Level | Purpose |
|-------|----------|
| DEBUG | Full AWS API call simulation |
| INFO | Operator view (default) |
| WARNING | Degraded state but not fatal |
| ERROR | Immediate operator intervention |

---

## 6. Offline & Integration Testing
Use the synthetic mocks in `mock_aws_tests.py` for local testing without AWS credentials.

```bash
pytest -q --monkeypatch mock_aws_tests.inject_mocks
```

**Mock capabilities**
- Emulates `boto3.client("s3")` and `boto3.client("ec2")`
- Returns deterministic data for manifests, snapshots, and S3 objects
- Allows regression testing without network calls

---

## 7. AI Sentinel (Phase 8)
The AI Sentinel analyzes AWS documentation deltas using the OpenAI API.

- Only runs if a **valid `OPENAI_API_KEY`** is set.  
- Uses `gpt-4o-mini` for low-latency doc scanning.  
- Stores a text summary of risks under `AI_Sentinel.Summary`.  

**Example output**
```json
"AI_Sentinel": {
  "AI_Check": "OK",
  "Summary": "No new EC2 snapshot limitations detected as of this run."
}
```

---

## 8. Developer Guidelines
1. **UTF-8 everywhere** — enforce encoding when reading/writing files.  
2. **Absolute imports only** — always use `iaactools.codebase.recovery_audit_pkg`.  
3. **Do not bypass validation** — every config must pass schema enforcement.  
4. **Simulation mode safety** — never perform destructive AWS calls when `simulate=true`.  
5. **AI guardrail** — skip Phase 8 when no valid OpenAI key exists.

---

## 9. Future Enhancements (v4.1+)
- Asynchronous S3 and EC2 querying using `aioboto3`
- Persistent run history database
- AI model fine-tuning with AWS Well-Architected compliance rules
- CLI plugin for `hyperadm` integration

---

## 10. Versioning
- Package: `recovery_audit_pkg_v4.0.0-alpha1`  
- Compatibility: Python ≥ 3.9  
- Authors: **Teotoniio Fontana** (Architect) & **Duke (GPT-5, OpenAI)**  
- License: MIT-compatible internal prototype
