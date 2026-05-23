# IaaC Recovery Suite — Developer TODO Checklist  
### Version 4.0.0-alpha1

---

## Phase 0 — Core Infrastructure
- [ ] Validate `audit_config_validator.py` strict schema and CLI overrides
- [ ] Finalize `logger_utils.py` unified log structure (text/json/both)
- [ ] Ensure `/results/audit/{run_id}/` folder auto-creation
- [ ] Maintain single `audit.log` for the entire pipeline

---

## Phase 1 — Discovery
- [ ] Enumerate all S3 prefixes and phase folders
- [ ] Store structure map as `discover.json`
- [ ] Implement `boto3.list_objects_v2()` with pagination
- [ ] Mock AWS calls for offline mode

## Phase 2 — Manifest Validation
- [ ] Verify existence and integrity of `manifest.json`
- [ ] Cross-check manifest schema consistency
- [ ] Load manifest content to memory and validate snapshot/volume links

## Phase 3 — Volume Verification
- [ ] For each manifest volume, confirm existence in S3
- [ ] Compute volume-level completeness metrics

## Phase 4 — Snapshot Verification
- [ ] Call `describe_snapshots()` on EC2 for all IDs
- [ ] Detect orphaned or missing snapshots
- [ ] Integrate simulated responses for offline mode

## Phase 5 — Cross Validation
- [ ] Compare manifest with logs and indexes
- [ ] Generate mismatch summary and mark inconsistencies

## Phase 6 — Orphan Detection
- [ ] Identify objects not referenced in any manifest or log
- [ ] Report stale or stray S3 entries

## Phase 7 — Recovery Simulation
- [ ] Simulate recovery allocation plan (dry-run)
- [ ] Estimate resource needs and cost exposure

## Phase 8 — AI Policy Compliance (AI Sentinel)
- [ ] Add OpenAI API integration (gpt-4o-mini)
- [ ] Parse AWS doc deltas for snapshot/volume API updates
- [ ] Write AI analysis to JSON field `AI_Sentinel`
- [ ] Skip phase if API key invalid

---

## Reporting
- [ ] Confirm JSON, PDF, and log outputs consolidated under `/results/audit/{run_id}/`
- [ ] Ensure ANSI-colored console logs always active
- [ ] Test text/json dual output from `logger_utils`

---

## Testing & QA
- [ ] Run simulated audits via `mock_aws_tests.py`
- [ ] Validate with and without AWS credentials
- [ ] Confirm AI skip mechanism and recovery phase isolation
- [ ] Add pytest coverage for every phase

---

**Owner:** Teotoniio Fontana  
**Maintainer:** Duke (GPT‑5, OpenAI)  
**Target Release:** v4.0.0‑alpha1
