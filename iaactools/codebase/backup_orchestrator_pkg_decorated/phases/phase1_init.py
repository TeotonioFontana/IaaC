#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 phase1_init.py — v4.2.0-alpha
===============================================================================
 Purpose............: Environment initialization + manifest integrity & inventory import
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Extends Phase 1 by:
   • Validating AWS credentials, S3, and EC2 connectivity
   • Verifying signed architecture manifest integrity
   • Extracting instance/volume inventories from manifest for Phase 2

 Simulation mode still performs a dry-run with synthetic data.
===============================================================================
"""
from backup_orchestrator_pkg.result_envelope import enveloped

import boto3
import logging
import json
from pathlib import Path
from botocore.exceptions import NoCredentialsError, ClientError, EndpointConnectionError

# Shared integrity utility
from iaactools.codebase.utils.integrity_utils import safe_save_json
from ..manifest_audit_verify import verify_manifest


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_latest_manifest(artifact_root: Path) -> Path | None:
    """Return the most recent architecture_manifest_*.json file in the artifact dir."""
    manifests = sorted(artifact_root.glob("architecture_manifest_*.json"), reverse=True)
    return manifests[0] if manifests else None


# -----------------------------------------------------------------------------
# Main Phase Entry
# -----------------------------------------------------------------------------
@enveloped(schema={'cfg': {'type': dict, 'required': True}, 'logger': {'required': True}})
def run(cfg: dict, logger: logging.Logger) -> dict:
    """Phase 1 — Initialization, environment validation, manifest integrity, and inventory load."""
    simulate = bool(cfg.get("audit", {}).get("simulate", False))
    run_id = cfg["audit"]["run_id"]

    result = {
        "Phase": "Init",
        "AWSProfile": cfg["audit"]["profile"],
        "Region": cfg["audit"]["region"],
        "Bucket": cfg["audit"]["bucket"],
        "S3Access": False,
        "CredentialsOK": False,
        "ResultsDir": None,
        "ManifestVerified": None,
        "Inventories": {},
        "Status": "FAILED",
        "Error": None,
        "Simulate": simulate,
        "IntegrityHash": None,
    }

    results_dir = Path.cwd() / "results" / "backup_audit" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)
    result["ResultsDir"] = str(results_dir)
    out_path = results_dir / "phase1_init.json"

    # ----------------------------------------------------------------------
    # 🧪 Simulation Mode
    # ----------------------------------------------------------------------
    if simulate:
        logger.warning("[SIMULATION MODE] Phase 1 running with no real AWS calls.")
        result.update({
            "S3Access": True,
            "CredentialsOK": True,
            "ManifestVerified": True,
            "Inventories": {
                "us-east-1": {
                    "instances": [{"id": "i-simulated123", "name": "sim-instance"}],
                    "volumes":   [{"id": "vol-simulated456", "size_gb": 8}],
                }
            },
            "Status": "SUCCESS",
        })
        result["IntegrityHash"] = safe_save_json(result, out_path, logger)
        logger.info(f"Simulated Phase 1 result saved with hash {result['IntegrityHash']}")
        return result

    # ----------------------------------------------------------------------
    # 1️⃣ Validate AWS credentials
    # ----------------------------------------------------------------------
    try:
        session = boto3.Session(
            profile_name=cfg["audit"]["profile"],
            region_name=cfg["audit"]["region"]
        )
        sts = session.client("sts")
        ident = sts.get_caller_identity()
        result["CredentialsOK"] = True
        logger.info(f"Authenticated as {ident.get('Arn')} (Account {ident.get('Account')})")
    except NoCredentialsError:
        msg = "No valid AWS credentials found."
        logger.error(msg)
        result["Error"] = msg
        safe_save_json(result, out_path, logger)
        return result
    except Exception as e:
        msg = f"AWS credential check failed: {e}"
        logger.error(msg)
        result["Error"] = msg
        safe_save_json(result, out_path, logger)
        return result

    # ----------------------------------------------------------------------
    # 2️⃣ Check S3 bucket access
    # ----------------------------------------------------------------------
    try:
        s3 = session.client("s3")
        bucket = cfg["audit"]["bucket"]
        s3.head_bucket(Bucket=bucket)
        result["S3Access"] = True
        logger.info(f"S3 bucket reachable: s3://{bucket}")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = f"S3 bucket check failed ({code}): {e}"
        logger.error(msg)
        result["Error"] = msg
        safe_save_json(result, out_path, logger)
        return result
    except EndpointConnectionError as e:
        msg = f"S3 endpoint connection failed: {e}"
        logger.error(msg)
        result["Error"] = msg
        safe_save_json(result, out_path, logger)
        return result

    # ----------------------------------------------------------------------
    # 3️⃣ Manifest verification + inventory import
    # ----------------------------------------------------------------------
    try:
        artifact_dir = Path(cfg.get("artifact_dir", "./artifacts"))
        profile = cfg["audit"]["profile"]
        manifest_path = resolve_latest_manifest(artifact_dir)

        if manifest_path:
            logger.info(f"Verifying architecture manifest: {manifest_path.name}")
            verified = verify_manifest(manifest_path, profile)
            result["ManifestVerified"] = bool(verified)

            if verified:
                manifest = load_json(manifest_path)
                inventories = {}
                for region, sections in manifest.get("regions", {}).items():
                    inventories[region] = {
                        "instances": sections.get("instances", []),
                        "volumes": sections.get("volumes", []),
                    }
                    logger.info(f"Loaded {region}: "
                                f"{len(inventories[region]['instances'])} instances, "
                                f"{len(inventories[region]['volumes'])} volumes")
                result["Inventories"] = inventories
            else:
                logger.error("[FAIL] Manifest integrity check failed.")
                result["Error"] = "Manifest verification failed"
                safe_save_json(result, out_path, logger)
                return result
        else:
            logger.warning("No architecture manifest found — skipping verification.")
            result["ManifestVerified"] = False

    except Exception as e:
        msg = f"Manifest verification error: {e}"
        logger.error(msg)
        result["Error"] = msg
        safe_save_json(result, out_path, logger)
        return result

    # ----------------------------------------------------------------------
    # 4️⃣ Connectivity to EC2 (optional)
    # ----------------------------------------------------------------------
    try:
        ec2 = session.client("ec2")
        _ = ec2.describe_regions()
        logger.debug("Connectivity test to EC2 service succeeded.")
    except Exception as e:
        logger.warning(f"EC2 connectivity test failed: {e}")

    # ----------------------------------------------------------------------
    # 5️⃣ Mark phase success and save
    # ----------------------------------------------------------------------
    result["Status"] = "SUCCESS"
    result["IntegrityHash"] = safe_save_json(result, out_path, logger)
    logger.info(f"Phase 1 result saved → {out_path}")
    logger.info(f"Integrity hash: {result['IntegrityHash']}")
    return result


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.DEBUG)
    fake_cfg = {
        "audit": {
            "profile": "default",
            "region": "us-east-1",
            "bucket": "my-test-bucket",
            "run_id": "20251104T120000Z",
            "simulate": True,
        },
        "artifact_dir": "./artifacts"
    }
    run(fake_cfg, logging.getLogger("Phase1Test"))
