# -*- coding: utf-8 -*-
"""
===============================================================================
 phase1_discovery.py — v4.0.1-alpha2
===============================================================================
 Purpose............: Discover and validate the expected S3 structure under the
                      configured backup base prefix.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Scans the target S3 bucket for all expected orchestrator phases:
   discover → plan → prep → backup → manifest → logs → artifacts → indexes → latest

 Each prefix is validated for presence and object count. The phase returns
 a structured result with {"Status": "OK"|"FAIL"} and details per section.

 Features restored from earlier versions:
   • Simulation-safe execution
   • Structured error reporting
   • Policy enforcement for mandatory paths
   • Tolerant of partial access issues
===============================================================================
"""
import boto3
import logging
from botocore.exceptions import ClientError, NoCredentialsError

# -----------------------------------------------------------------------------
# Main Phase Runner
# -----------------------------------------------------------------------------
def run(cfg, logger: logging.Logger) -> dict:
    """
    Phase 1 — Discover and verify S3 bucket structure.
    Returns {"Status": "OK"/"FAIL", "Structure": {...}, "Missing": [...]}.
    """
    audit = cfg.get("audit", {})
    bucket = audit.get("bucket")
    region = audit.get("region")
    base = cfg.get("prefixes", {}).get("base", "")
    simulate = audit.get("simulate", False)

    result = {
        "Status": "OK",
        "Structure": {},
        "Missing": [],
    }

    expected_phases = [
        "discover", "plan", "prep", "backup",
        "manifest", "logs", "artifacts", "indexes", "latest"
    ]

    try:
        if simulate:
            logger.debug("[SIMULATE] Skipping real S3 calls for phase 1 discovery.")
            for p in expected_phases:
                result["Structure"][p] = {"Exists": True, "Objects": 10}
            return result

        # --- Live S3 discovery
        s3 = boto3.client("s3", region_name=region)
        for phase in expected_phases:
            prefix = f"{base.rstrip('/')}/{phase}/"
            try:
                response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=5)
                count = response.get("KeyCount", 0)
                exists = count > 0
                result["Structure"][phase] = {"Exists": exists, "Objects": count}
                msg = f"{'FOUND' if exists else 'MISSING'} {phase:10s} → {count} objects"
                color = "\033[32m" if exists else "\033[33m"
                logger.info(f"{color}{msg}\033[0m")
                if not exists:
                    result["Missing"].append(phase)
            except ClientError as e:
                logger.error(f"S3 list_objects_v2 failed for prefix '{prefix}': {e}")
                result["Structure"][phase] = {"Exists": False, "Objects": 0}
                result["Missing"].append(phase)
            except NoCredentialsError:
                logger.error("AWS credentials not found — cannot access S3.")
                return {"Status": "FAIL", "Error": "No AWS credentials"}

        # --- Post-scan evaluation
        if result["Missing"]:
            logger.warning(f"Missing phases: {', '.join(result['Missing'])}")
            # If critical paths are missing, mark FAIL
            critical = {"discover", "plan", "backup", "manifest"}
            if critical.intersection(result["Missing"]):
                result["Status"] = "FAIL"
                logger.error("Critical phases missing — discovery incomplete.")
        else:
            logger.info("All expected S3 prefixes discovered successfully.")

    except Exception as e:
        logger.error(f"[EXCEPTION] Phase 1 discovery failed: {e}")
        result["Status"] = "FAIL"
        result["Error"] = str(e)

    return result


# -----------------------------------------------------------------------------
# Synthetic Test Entry
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("Synthetic test: Phase 1 Discovery (simulation mode)")
    dummy_cfg = {
        "audit": {"bucket": "demo-bucket", "region": "us-east-1", "simulate": True},
        "prefixes": {"base": "iaac/backups"},
    }

    class DummyLogger:
        def info(self, msg): print(msg)
        def debug(self, msg): print(msg)
        def error(self, msg): print(msg)
        def warning(self, msg): print(msg)

    print(run(dummy_cfg, DummyLogger()))
