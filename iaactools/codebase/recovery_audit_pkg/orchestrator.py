# -*- coding: utf-8 -*-
"""
===============================================================================
 orchestrator.py — v4.0.1-alpha2
===============================================================================
 Purpose............: Coordinate and execute all recovery audit phases.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 The orchestrator executes the 8-phase pipeline sequentially, storing each
 phase’s result under /results/audit/{run_id}/. Each phase must return a
 structured dict containing {"Status": "OK"|"FAIL"}.
 On failure, the pipeline stops immediately, logs the reason, and writes
 partial results to final_audit_result.json.
===============================================================================
"""

import sys
import json
from pathlib import Path
from . import (
    audit_config_validator,
    logger_utils,
    phase1_discovery,
    phase2_manifest_check,
    phase3_volume_verification,
    phase4_snapshot_verification,
    phase5_cross_validation,
    phase6_orphan_detection,
    phase7_recovery_simulation,
    phase8_ai_policy_check,
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def safe_run(phase_func, name, cfg, logger, *args):
    """
    Execute a phase safely and return a structured result.
    Any exception is caught and converted to {"Status": "FAIL", "Error": str(e)}.
    """
    try:
        result = phase_func(cfg, logger, *args)
        if not isinstance(result, dict) or "Status" not in result:
            raise ValueError(f"Phase {name} did not return a valid dict with 'Status'")
        return result
    except Exception as e:
        logger.error(f"[EXCEPTION] {name} raised an error: {e}")
        return {"Status": "FAIL", "Error": str(e)}


def abort_pipeline(logger, results_dir, run_id, partial_results, reason, code=1):
    """
    Abort execution, persist partial results, log reason, and exit gracefully.
    """
    out_file = results_dir / "final_audit_result.json"
    try:
        with out_file.open("w", encoding="utf-8") as f:
            json.dump(partial_results, f, indent=2)
    except Exception as e:
        logger.error(f"[ABORT] Could not save partial results: {e}")
    logger.error(f"[ABORTED] {reason}")
    logger.error(f"Partial results written → {out_file}")
    sys.exit(code)


# -----------------------------------------------------------------------------
# Main Orchestrator
# -----------------------------------------------------------------------------
def main():
    """
    Run the full recovery audit orchestrator with strict phase-by-phase control.
    """
    args, cfg = audit_config_validator.parse_args()
    run_id = cfg["audit"]["run_id"]
    results_dir = Path.cwd() / "results" / "audit" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    logger = logger_utils.build_logger("RecoveryAudit", results_dir, run_id)
    logger.info("=== Starting Recovery Audit Orchestrator ===")

    partial = {"RunId": run_id}

    PHASES = [
        ("Phase 1: S3 Discovery", phase1_discovery.run, []),
        ("Phase 2: Manifest Validation", phase2_manifest_check.run, []),
        ("Phase 3: Volume Verification", phase3_volume_verification.run, []),
        ("Phase 4: Snapshot Verification", phase4_snapshot_verification.run, []),
        ("Phase 5: Cross-Validation", phase5_cross_validation.run, []),
        ("Phase 6: Orphan Detection", phase6_orphan_detection.run, []),
        ("Phase 7: Recovery Simulation", phase7_recovery_simulation.run, []),
        ("Phase 8: AI Sentinel Compliance Check", phase8_ai_policy_check.run, []),
    ]

    for name, func, extra_args in PHASES:
        logger.info(f"▶ {name}")
        result = safe_run(func, name, cfg, logger, *extra_args)
        partial[name] = result
        if result.get("Status") != "OK":
            abort_pipeline(logger, results_dir, run_id, partial, f"{name} failed", code=1)

    out_file = results_dir / "final_audit_result.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(partial, f, indent=2)

    logger.info(f"Audit completed successfully → {out_file}")
    logger.info("All phases executed successfully.")
    return partial


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("[ABORTED] User interrupted execution.")
