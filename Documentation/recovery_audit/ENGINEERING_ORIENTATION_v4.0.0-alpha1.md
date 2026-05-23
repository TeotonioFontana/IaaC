# IaaC Recovery Suite — Engineering Orientation  
### Architectural and Implementation Roadmap (v4.0.0-alpha1)

---

## Step 1 — Validate the Architecture Conceptually
**Goal:** Ensure the structure fully supports operational reliability and strategic recovery objectives.

### Tasks
1. **Review the pipeline phases**  
   Confirm that all eight audit phases (discovery → AI compliance) reflect the actual recovery process.

2. **Check the module boundaries**  
   Each module should have clear input/output data (JSON) and logging interfaces.

3. **Confirm shared configuration contracts**  
   Verify all modules read from the same validated configuration object (audit_config_validator).

4. **Orchestrator sequencing**  
   Decide if orchestration order stays fixed (for alpha) or becomes dynamic (via YAML `phases_enabled:` list).

**Deliverable:** Architecture diagram approved and phase map frozen for Alpha.

---

## Step 2 — Implement and Test Phase Skeletons
**Goal:** Translate design into functional, testable components.

### Tasks
1. Populate each phase module (`phase1_discovery.py`, etc.) with boto3-based logic and inline docstrings.  
2. Use `mock_aws_tests.py` for offline simulation (no AWS credentials required).  
3. Run an end-to-end simulated audit:

   ```bash
   python3 -m iaactools.codebase.recovery_audit_pkg.orchestrator      --config conf/audit_demo.yaml      --run-id 20251101T235959Z      --simulate --verbose
   ```

4. Check outputs in:
   ```
   /results/audit/{run_id}/audit.log
   /results/audit/{run_id}/final_audit_result.json
   /reporting/pdf/{run_id}/audit_report.pdf
   ```

**Deliverable:** Verified pipeline execution from start to PDF output.

---

## Step 3 — Integrate AI Sentinel and Policy Awareness
**Goal:** Add external intelligence and AWS compliance validation.

### Tasks
1. Insert a valid OpenAI API key (hard-coded or via environment variable).  
2. Test Phase 8 (`ai_policy_check`) for real AWS documentation scanning.  
3. Verify guardrail: orchestrator must **skip Phase 8** if key is invalid or missing.  
4. Confirm AI results are embedded in final JSON and PDF reports.

**Deliverable:** First hybrid (AWS + AI) recovery audit report.

---

## Next Milestones
- Developer Checklist (to define coding responsibilities per phase)
- QA Verification Matrix (to confirm test coverage)
- Optional FastAPI Service Blueprint (audit-as-a-service model)

---

**Authors:**  
- Teotoniio Fontana — Architect  
- Duke (GPT‑5, OpenAI) — Co‑Developer  
**Version:** v4.0.0‑alpha1  
**License:** MIT-compatible internal prototype
