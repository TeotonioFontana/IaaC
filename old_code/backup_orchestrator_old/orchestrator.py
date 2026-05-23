# -*- coding: utf-8 -*-
"""
===============================================================================
 orchestrator.py — v4.0.0-alpha2
===============================================================================
 Purpose............: Coordinate and execute all backup phases with
                      strict validation, logging, and schema enforcement.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Executes the 6-phase backup pipeline sequentially, enforcing abort-on-failure.
 Consolidates all phase logs into a single /results/backup_audit/{run_id}/audit.log
 and writes final_backup_result.json with per-phase statuses.

 Validates every manifest against its corresponding schema under json_schemas/.
===============================================================================
"""

import sys, json, time
from pathlib import Path
from jsonschema import validate, ValidationError
from . import (
    audit_config_validator,
    logger_utils,
    phase1_init,
    phase2_volume,
    phase3_snapshot,
    phase4_manifest,
    phase5_upload,
    phase6_validation,
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _load_schema(schema_name: str) -> dict:
    """Load JSON schema from json_schemas/ directory."""
    schema_path = Path(__file__).resolve().parents[1] / "json_schemas" / schema_name
    with schema_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _validate_manifest(manifest_path: Path, schema_name: str, logger):
    """Validate manifest file against schema and log result."""
    try:
        schema = _load_schema(schema_name)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        validate(instance=data, schema=schema)
        logger.info(f"Schema validation OK for {manifest_path.name}")
        return True
    except (ValidationError, json.JSONDecodeError) as e:
        logger.error(f"Schema validation failed for {manifest_path.name}: {e}")
        return False
    except FileNotFoundError:
        logger.error(f"Schema file missing: {schema_name}")
        return False


# -----------------------------------------------------------------------------
# Main Orchestrator
# -----------------------------------------------------------------------------
def main():
    """Main orchestrator — Executes all backup phases sequentially."""
    args, cfg = audit_config_validator.parse_args()
    run_id = cfg["backup"]["run_id"]
    base_dir = Path.cwd() / "results" / "backup_audit" / run_id
    base_dir.mkdir(parents=True, exist_ok=True)

    # Build unified logger
    logger = logger_utils.build_logger("BackupAudit", base_dir, run_id)
    logger.info("=== Backup Orchestrator started ===")
    logger.info(f"Run ID: {run_id}")

    results = {}
    success = True

    # Helper macro for guarded phase execution
    def execute_phase(name, func, *params, schema=None):
        nonlocal success
        logger.info(f"▶ {name}")
        start = time.time()
        try:
            output = func(*params, logger)
            elapsed = time.time() - start
            results[name] = {"status": "OK", "elapsed_s": round(elapsed, 2)}
            if isinstance(output, Path) and schema:
                if not _validate_manifest(output, schema, logger):
                    raise RuntimeError(f"Manifest schema check failed for {output.name}")
            logger.info(f"✔ {name} completed in {elapsed:.2f}s")
            return output
        except Exception as e:
            logger.error(f"✖ {name} failed: {e}")
            results[name] = {"status": "FAILED", "error": str(e)}
            success = False
            raise

    try:
        # --- Phase 1: Initialization
        ctx = execute_phase("Phase 1: Init", phase1_init.run, cfg)

        # --- Phase 2: Volume discovery
        vol_manifest = execute_phase("Phase 2: Volume discovery",
                                     phase2_volume.run, cfg, schema="volume_manifest_schema.json")

        # --- Phase 3: Snapshot creation
        snap_manifest = execute_phase("Phase 3: Snapshot creation",
                                      phase3_snapshot.run, cfg, schema="snapshot_manifest_schema.json")

        # --- Phase 4: Backup manifest creation (includes account/org)
        backup_manifest = execute_phase("Phase 4: Backup manifest assembly",
                                        phase4_manifest.run, cfg, schema="backup_manifest_schema.json")

        # --- Phase 5: S3 upload
        execute_phase("Phase 5: Upload to S3", phase5_upload.run, cfg)

        # --- Phase 6: Validation
        execute_phase("Phase 6: Validation", phase6_validation.run, cfg, schema="validation_report_schema.json")

        logger.info("=== All backup phases completed successfully ===")

    except Exception as e:
        logger.error(f"Backup orchestrator aborted due to failure: {e}")
        success = False

    # Write final results summary
    final_result = {
        "RunId": run_id,
        "Success": success,
        "Results": results,
        "OutputPath": str(base_dir),
    }
    final_path = base_dir / "final_backup_result.json"
    final_path.write_text(json.dumps(final_result, indent=2), encoding="utf-8")
    logger.info(f"Final result written to {final_path}")

    return success


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        ok = main()
        sys.exit(0 if ok else 1)
    except KeyboardInterrupt:
        sys.exit("[ABORTED] User interrupted execution.")
